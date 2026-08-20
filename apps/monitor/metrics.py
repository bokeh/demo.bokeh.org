"""Collect sanitized, coalesced measurements for the public monitor."""

from __future__ import annotations

import json
import logging
import math
import os
import resource
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic, process_time, time
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from apps._common.activity import PUBLIC_ACTIVITY, PublicActivity
from apps._common.performance import (
    PUBLIC_PERFORMANCE,
    AppTiming,
    CallbackTiming,
    PerformanceSnapshot,
    PublicPerformance,
    latency_histogram,
)

LOGGER = logging.getLogger("demo.monitor")
SAMPLE_INTERVAL_SECONDS = 2.0
MAX_RESPONSE_BYTES = 1_000_000
MIB = 1024 * 1024
ECS_METADATA_HOSTS = frozenset({"169.254.170.2"})


@dataclass(frozen=True, slots=True)
class SystemSample:
    """Allowlisted system values returned by a monitor adapter."""

    source_label: str
    scope: str
    deterministic: bool
    cpu_percent: float | None
    memory_bytes: float | None
    memory_percent: float | None
    cpu_capacity_vcpus: float | None
    memory_capacity_bytes: float | None
    rx_bytes_per_second: float | None
    tx_bytes_per_second: float | None


@dataclass(frozen=True, slots=True)
class MonitorSample:
    """One browser-safe point combining system and process measurements."""

    generation: int
    timestamp_ms: float
    source_label: str
    scope: str
    deterministic: bool
    cpu_percent: float | None
    memory_bytes: float | None
    memory_percent: float | None
    cpu_capacity_vcpus: float | None
    memory_capacity_bytes: float | None
    rx_bytes_per_second: float | None
    tx_bytes_per_second: float | None
    active_sessions: int
    requests_per_minute: float
    callback_rate: float
    callback_count: int
    callback_window_seconds: float
    callback_p95_ms: float | None
    callback_max_ms: float | None
    callback_histogram: tuple[int, ...]
    event_loop_p95_ms: float | None
    event_loop_max_ms: float | None
    event_loop_histogram: tuple[int, ...]
    callbacks_by_app: tuple[AppTiming, ...]
    event_loop_by_app: tuple[AppTiming, ...]
    slowest_callbacks: tuple[CallbackTiming, ...]


class MetricsAdapter(Protocol):
    """Read one set of system measurements."""

    def sample(self, *, now: float) -> SystemSample: ...


class EcsTaskStatsAdapter:
    """Extract numeric task measurements from the link-local ECS v4 endpoint."""

    def __init__(
        self,
        metadata_uri: str,
        *,
        cpu_limit: float,
        memory_limit_mib: float,
        timeout_seconds: float = 0.25,
        opener: Any = urlopen,
    ) -> None:
        parsed = urlsplit(metadata_uri)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ECS_METADATA_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ECS metadata URI must use the known link-local endpoint")
        if not math.isfinite(cpu_limit) or cpu_limit <= 0:
            raise ValueError("task CPU limit must be positive")
        if not math.isfinite(memory_limit_mib) or memory_limit_mib <= 0:
            raise ValueError("task memory limit must be positive")
        self._endpoint = f"{metadata_uri.rstrip('/')}/task/stats"
        self._cpu_limit = cpu_limit
        self._memory_limit_bytes = memory_limit_mib * MIB
        self._timeout_seconds = timeout_seconds
        self._opener = opener
        self._previous_network: tuple[float, float, float] | None = None

    def sample(self, *, now: float) -> SystemSample:
        """Fetch task stats and retain only numeric aggregates."""
        request = Request(self._endpoint, headers={"Accept": "application/json"})
        with self._opener(request, timeout=self._timeout_seconds) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("ECS task stats response is unexpectedly large")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("ECS task stats response must be an object")

        task_cpu_percent = 0.0
        memory_bytes = 0.0
        network_rates: list[tuple[float, float]] = []
        network_totals: list[tuple[float, float]] = []
        containers = 0

        # The response keys and fields such as name/id are intentionally ignored.
        for raw_stats in payload.values():
            if not isinstance(raw_stats, dict):
                continue
            containers += 1
            task_cpu_percent += self._container_cpu_percent(raw_stats)
            memory_bytes += self._memory_usage(raw_stats)
            if rate := self._network_rate(raw_stats):
                network_rates.append(rate)
            if total := self._network_total(raw_stats):
                network_totals.append(total)

        if not containers:
            raise ValueError("ECS task stats response contains no containers")

        if network_rates:
            rx_rate = max(rate[0] for rate in network_rates)
            tx_rate = max(rate[1] for rate in network_rates)
        else:
            totals = (
                max((total[0] for total in network_totals), default=0.0),
                max((total[1] for total in network_totals), default=0.0),
            )
            rx_rate, tx_rate = self._rate_from_totals(now, totals)

        return SystemSample(
            source_label="Live stats from this ECS task",
            scope="task",
            deterministic=False,
            cpu_percent=max(0.0, task_cpu_percent / self._cpu_limit),
            memory_bytes=memory_bytes,
            memory_percent=max(0.0, 100 * memory_bytes / self._memory_limit_bytes),
            cpu_capacity_vcpus=self._cpu_limit,
            memory_capacity_bytes=self._memory_limit_bytes,
            rx_bytes_per_second=rx_rate,
            tx_bytes_per_second=tx_rate,
        )

    @staticmethod
    def _container_cpu_percent(stats: dict[str, Any]) -> float:
        current = stats.get("cpu_stats", {})
        previous = stats.get("precpu_stats", {})
        if not isinstance(current, dict) or not isinstance(previous, dict):
            return 0.0
        current_usage = current.get("cpu_usage", {})
        previous_usage = previous.get("cpu_usage", {})
        if not isinstance(current_usage, dict) or not isinstance(previous_usage, dict):
            return 0.0
        cpu_delta = _number(current_usage.get("total_usage")) - _number(
            previous_usage.get("total_usage")
        )
        system_delta = _number(current.get("system_cpu_usage")) - _number(
            previous.get("system_cpu_usage")
        )
        online_cpus = _number(current.get("online_cpus"))
        if online_cpus <= 0:
            per_cpu = current_usage.get("percpu_usage", [])
            online_cpus = float(len(per_cpu)) if isinstance(per_cpu, list) else 1.0
        if cpu_delta <= 0 or system_delta <= 0:
            return 0.0
        return 100 * cpu_delta / system_delta * max(1.0, online_cpus)

    @staticmethod
    def _memory_usage(stats: dict[str, Any]) -> float:
        memory = stats.get("memory_stats", {})
        return _number(memory.get("usage")) if isinstance(memory, dict) else 0.0

    @staticmethod
    def _network_rate(stats: dict[str, Any]) -> tuple[float, float] | None:
        rates = stats.get("network_rate_stats", {})
        if not isinstance(rates, dict):
            return None
        rx = _optional_number(rates.get("rx_bytes_per_sec"))
        tx = _optional_number(rates.get("tx_bytes_per_sec"))
        return None if rx is None or tx is None else (max(0.0, rx), max(0.0, tx))

    @staticmethod
    def _network_total(stats: dict[str, Any]) -> tuple[float, float] | None:
        networks = stats.get("networks", {})
        if not isinstance(networks, dict):
            return None
        rx = 0.0
        tx = 0.0
        found = False
        for raw_network in networks.values():
            if not isinstance(raw_network, dict):
                continue
            rx += _number(raw_network.get("rx_bytes"))
            tx += _number(raw_network.get("tx_bytes"))
            found = True
        return (rx, tx) if found else None

    def _rate_from_totals(
        self, now: float, totals: tuple[float, float]
    ) -> tuple[float | None, float | None]:
        previous = self._previous_network
        self._previous_network = (now, *totals)
        if previous is None or now <= previous[0]:
            return None, None
        elapsed = now - previous[0]
        return (
            max(0.0, totals[0] - previous[1]) / elapsed,
            max(0.0, totals[1] - previous[2]) / elapsed,
        )


class LocalProcessAdapter:
    """Measure the current process without AWS credentials or services."""

    def __init__(self) -> None:
        self._previous_cpu: tuple[float, float] | None = None
        self._previous_network: tuple[float, float, float] | None = None
        self._containerized = Path("/.dockerenv").exists()

    def sample(self, *, now: float) -> SystemSample:
        cpu_time = process_time()
        cpu_percent: float | None = None
        if self._previous_cpu is not None and now > self._previous_cpu[0]:
            cpu_percent = max(
                0.0, 100 * (cpu_time - self._previous_cpu[1]) / (now - self._previous_cpu[0])
            )
        self._previous_cpu = (now, cpu_time)

        rx_rate: float | None = None
        tx_rate: float | None = None
        if self._containerized and (totals := self._linux_network_totals()) is not None:
            if self._previous_network is not None and now > self._previous_network[0]:
                elapsed = now - self._previous_network[0]
                rx_rate = max(0.0, totals[0] - self._previous_network[1]) / elapsed
                tx_rate = max(0.0, totals[1] - self._previous_network[2]) / elapsed
            self._previous_network = (now, *totals)

        return SystemSample(
            source_label="Live stats from this Python process",
            scope="process",
            deterministic=False,
            cpu_percent=cpu_percent,
            memory_bytes=self._resident_memory(),
            memory_percent=None,
            cpu_capacity_vcpus=None,
            memory_capacity_bytes=None,
            rx_bytes_per_second=rx_rate,
            tx_bytes_per_second=tx_rate,
        )

    @staticmethod
    def _resident_memory() -> float:
        statm = Path("/proc/self/statm")
        if statm.is_file():
            fields = statm.read_text().split()
            if len(fields) >= 2:
                return float(int(fields[1]) * os.sysconf("SC_PAGE_SIZE"))
        maximum_rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return maximum_rss if sys.platform == "darwin" else maximum_rss * 1024

    @staticmethod
    def _linux_network_totals() -> tuple[float, float] | None:
        path = Path("/proc/net/dev")
        if not path.is_file():
            return None
        rx = 0.0
        tx = 0.0
        for line in path.read_text().splitlines()[2:]:
            interface, separator, values = line.partition(":")
            fields = values.split()
            if separator and interface.strip() != "lo" and len(fields) >= 9:
                rx += float(fields[0])
                tx += float(fields[8])
        return rx, tx


class DeterministicAdapter:
    """Produce clearly labeled repeatable values for presentation fallback."""

    def __init__(self, *, source_label: str = "Deterministic sample data") -> None:
        self.source_label = source_label
        self._index = 0

    def sample(self, *, now: float) -> SystemSample:
        del now
        phase = self._index / 6
        self._index += 1
        return SystemSample(
            source_label=self.source_label,
            scope="simulated",
            deterministic=True,
            cpu_percent=31 + 13 * math.sin(phase) + 4 * math.sin(phase * 2.7),
            memory_bytes=(790 + 28 * math.sin(phase / 2)) * MIB,
            memory_percent=38.5 + 1.4 * math.sin(phase / 2),
            cpu_capacity_vcpus=1.0,
            memory_capacity_bytes=2048 * MIB,
            rx_bytes_per_second=42_000 + 24_000 * (1 + math.sin(phase * 1.4)),
            tx_bytes_per_second=18_000 + 11_000 * (1 + math.cos(phase * 1.1)),
        )


class CoalescedSampler:
    """Share one bounded-rate source sample among every monitor viewer."""

    def __init__(
        self,
        adapter: MetricsAdapter,
        *,
        performance: PublicPerformance = PUBLIC_PERFORMANCE,
        activity: PublicActivity = PUBLIC_ACTIVITY,
        interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
        fallback: MetricsAdapter | None = None,
    ) -> None:
        self._adapter = adapter
        self._performance = performance
        self._activity = activity
        self._interval_seconds = interval_seconds
        self._fallback = fallback or DeterministicAdapter(
            source_label="Deterministic fallback · live source unavailable"
        )
        self._last_sampled_at: float | None = None
        self._last_sample: MonitorSample | None = None
        self._generation = 0
        self._lock = Lock()
        self._fallback_active = False

    def sample(self, *, now: float | None = None, wall_time: float | None = None) -> MonitorSample:
        """Return a cached point unless the process-wide interval has elapsed."""
        sampled_at = monotonic() if now is None else now
        timestamp = time() if wall_time is None else wall_time
        with self._lock:
            if (
                self._last_sample is not None
                and self._last_sampled_at is not None
                and sampled_at - self._last_sampled_at < self._interval_seconds
            ):
                return self._last_sample
            system = self._read_system(sampled_at)
            performance = self._performance.snapshot(now=sampled_at)
            activity = self._activity.snapshot(now=sampled_at)
            if system.deterministic:
                performance = _deterministic_performance(self._generation)
                active_sessions, requests_per_minute = _deterministic_activity(self._generation)
            else:
                active_sessions = activity.active_sessions
                requests_per_minute = activity.requests_per_minute
            self._generation += 1
            self._last_sampled_at = sampled_at
            self._last_sample = MonitorSample(
                generation=self._generation,
                timestamp_ms=1000 * timestamp,
                source_label=system.source_label,
                scope=system.scope,
                deterministic=system.deterministic,
                cpu_percent=system.cpu_percent,
                memory_bytes=system.memory_bytes,
                memory_percent=system.memory_percent,
                cpu_capacity_vcpus=system.cpu_capacity_vcpus,
                memory_capacity_bytes=system.memory_capacity_bytes,
                rx_bytes_per_second=system.rx_bytes_per_second,
                tx_bytes_per_second=system.tx_bytes_per_second,
                active_sessions=active_sessions,
                requests_per_minute=requests_per_minute,
                callback_rate=performance.callback_count / performance.window_seconds,
                callback_count=performance.callback_count,
                callback_window_seconds=performance.window_seconds,
                callback_p95_ms=performance.callback_p95_ms,
                callback_max_ms=performance.callback_max_ms,
                callback_histogram=performance.callback_histogram,
                event_loop_p95_ms=performance.event_loop_p95_ms,
                event_loop_max_ms=performance.event_loop_max_ms,
                event_loop_histogram=performance.event_loop_histogram,
                callbacks_by_app=performance.callbacks_by_app,
                event_loop_by_app=performance.event_loop_by_app,
                slowest_callbacks=performance.slowest_callbacks,
            )
            return self._last_sample

    def _read_system(self, now: float) -> SystemSample:
        try:
            sample = self._adapter.sample(now=now)
        except Exception:  # noqa: BLE001 - adapter failures must not break the public application
            if not self._fallback_active:
                LOGGER.warning(
                    "Monitor live source unavailable; using labeled deterministic fallback"
                )
            self._fallback_active = True
            return self._fallback.sample(now=now)
        self._fallback_active = False
        return sample


def create_adapter(environment: Mapping[str, str] = os.environ) -> MetricsAdapter:
    """Select ECS, local, or explicit deterministic input without credentials."""
    mode = environment.get("DEMO_MONITOR_SOURCE", "auto").casefold()
    if mode in {"demo", "deterministic"}:
        return DeterministicAdapter()
    if mode not in {"auto", "ecs", "local"}:
        raise ValueError("DEMO_MONITOR_SOURCE must be auto, ecs, local, or deterministic")
    metadata_uri = environment.get("ECS_CONTAINER_METADATA_URI_V4")
    if mode != "local" and metadata_uri:
        return EcsTaskStatsAdapter(
            metadata_uri,
            cpu_limit=float(environment["DEMO_MONITOR_TASK_CPU_LIMIT"]),
            memory_limit_mib=float(environment["DEMO_MONITOR_TASK_MEMORY_LIMIT_MIB"]),
        )
    if mode == "ecs":
        raise ValueError("ECS monitor source requested outside an ECS task")
    return LocalProcessAdapter()


def _number(value: object) -> float:
    number = _optional_number(value)
    return 0.0 if number is None else number


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _deterministic_performance(index: int) -> PerformanceSnapshot:
    phase = index / 6
    callbacks_by_app = (
        _deterministic_app("/image-processing", 18, 24.8 + 3 * math.sin(phase), 41.2),
        _deterministic_app("/market-monitor", 84, 5.2 + math.sin(phase), 8.7),
        _deterministic_app("/chaotic-motion", 126, 2.8 + 0.5 * math.sin(phase), 4.9),
        _deterministic_app("/cellular-automata", 210, 1.1 + 0.2 * math.sin(phase), 1.8),
    )
    event_loop_by_app = (
        _deterministic_app("/chaotic-motion", 34, 8.4 + 2 * math.sin(phase), 13.7),
        _deterministic_app("/climate", 18, 4.2 + math.sin(phase), 7.9),
        _deterministic_app("/image-processing", 42, 1.3 + 0.2 * math.sin(phase), 2.4),
        _deterministic_app("/market-monitor", 52, 0.8 + 0.1 * math.sin(phase), 1.4),
    )
    slowest_callbacks = (
        _deterministic_callback("/image-processing", "update_strength", 18, 24.8, 41.2),
        _deterministic_callback("/market-monitor", "advance", 78, 5.4, 8.7),
        _deterministic_callback("/chaotic-motion", "advance_active", 121, 2.9, 4.9),
        _deterministic_callback("/cellular-automata", "advance", 204, 1.1, 1.8),
    )
    callback_p95 = 7.5 + 2.8 * (1 + math.sin(phase * 1.7))
    event_loop_p95 = 1.6 + 0.9 * (1 + math.cos(phase * 1.3))
    callback_count = round(480 + 140 * (1 + math.sin(phase * 1.2)))
    return PerformanceSnapshot(
        window_seconds=60.0,
        callback_count=callback_count,
        callback_p95_ms=callback_p95,
        callback_max_ms=18 + 5 * (1 + math.sin(phase)),
        event_loop_p95_ms=event_loop_p95,
        event_loop_max_ms=5 + 2 * (1 + math.cos(phase)),
        callback_histogram=latency_histogram([callback_p95] * callback_count),
        event_loop_histogram=latency_histogram([event_loop_p95] * 60),
        callbacks_by_app=callbacks_by_app,
        event_loop_by_app=event_loop_by_app,
        slowest_callbacks=slowest_callbacks,
    )


def _deterministic_app(app: str, count: int, p95_ms: float, max_ms: float) -> AppTiming:
    return AppTiming(app, count, p95_ms, max_ms, latency_histogram([p95_ms] * count))


def _deterministic_callback(
    app: str, callback: str, count: int, p95_ms: float, max_ms: float
) -> CallbackTiming:
    return CallbackTiming(app, callback, count, p95_ms, max_ms, latency_histogram([p95_ms] * count))


def _deterministic_activity(index: int) -> tuple[int, float]:
    phase = index / 6
    return 5 + round(2 * (1 + math.sin(phase))), 18 + 7 * (1 + math.sin(phase * 1.3))
