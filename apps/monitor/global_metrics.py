"""Exchange and combine sanitized monitor heartbeats across demo tasks."""

from __future__ import annotations

import json
import logging
import math
import os
import secrets
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from threading import Event, Lock, Thread
from time import monotonic, time
from typing import Any, Protocol

import boto3
from botocore.config import Config

from apps._common.performance import (
    PUBLIC_APP_ROUTES,
    PUBLIC_CALLBACKS_BY_ROUTE,
    PUBLIC_LATENCY_BUCKETS_MS,
    AppTiming,
    CallbackTiming,
    histogram_percentile,
)

from .metrics import CoalescedSampler, MonitorSample

LOGGER = logging.getLogger("demo.monitor.global")
HEARTBEAT_INTERVAL_SECONDS = 30.0
HEARTBEAT_MAX_AGE_SECONDS = 75.0
HEARTBEAT_TTL_SECONDS = 180
MAX_ENCODED_BYTES = 32_768
MAX_HEARTBEATS = 32


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """One task's sanitized contribution to the service view."""

    published_at: float
    expires_at: int
    cpu_percent: float | None
    cpu_capacity_vcpus: float | None
    memory_bytes: float | None
    memory_capacity_bytes: float | None
    rx_bytes_per_second: float | None
    tx_bytes_per_second: float | None
    active_sessions: int
    page_entries_per_minute: float
    callback_count: int
    callback_window_seconds: float
    callback_max_ms: float | None
    callback_histogram: tuple[int, ...]
    event_loop_max_ms: float | None
    event_loop_histogram: tuple[int, ...]
    callbacks_by_app: tuple[AppTiming, ...]
    event_loop_by_app: tuple[AppTiming, ...]
    slowest_callbacks: tuple[CallbackTiming, ...]


@dataclass(frozen=True, slots=True)
class ServiceSample:
    """Browser-safe aggregate for all fresh reporting tasks."""

    generation: int
    timestamp_ms: float
    status: str
    reason: str | None
    source_label: str
    deterministic: bool
    freshness_seconds: float | None
    reporting_tasks: int
    active_sessions: int
    page_entries_per_minute: float
    cpu_vcpus: float | None
    cpu_percent: float | None
    memory_bytes: float | None
    memory_capacity_bytes: float | None
    memory_percent: float | None
    rx_bytes_per_second: float | None
    tx_bytes_per_second: float | None
    callback_rate: float
    callback_p95_ms: float | None
    event_loop_p95_ms: float | None
    callbacks_by_app: tuple[AppTiming, ...]
    event_loop_by_app: tuple[AppTiming, ...]
    slowest_callbacks: tuple[CallbackTiming, ...]


class HeartbeatStore(Protocol):
    """Store sanitized task heartbeats."""

    source_label: str
    deterministic: bool

    def put(self, publisher: str, heartbeat: Heartbeat) -> None: ...

    def read(self) -> tuple[Heartbeat, ...]: ...


class InMemoryHeartbeatStore:
    """Real process-local adapter for development without AWS credentials."""

    source_label = "Local process registry"
    deterministic = False

    def __init__(self) -> None:
        self._items: dict[str, Heartbeat] = {}
        self._lock = Lock()

    def put(self, publisher: str, heartbeat: Heartbeat) -> None:
        with self._lock:
            self._items[publisher] = heartbeat

    def read(self) -> tuple[Heartbeat, ...]:
        with self._lock:
            return tuple(self._items.values())


class DeterministicHeartbeatStore(InMemoryHeartbeatStore):
    """Repeatable multi-task adapter for screenshots and local UI work."""

    source_label = "Simulated whole service"
    deterministic = True

    def read(self) -> tuple[Heartbeat, ...]:
        items = super().read()
        if not items:
            return ()
        base = items[0]
        return (
            base,
            replace(
                base,
                cpu_percent=_scaled(base.cpu_percent, 0.72),
                memory_bytes=_scaled(base.memory_bytes, 0.88),
                rx_bytes_per_second=_scaled(base.rx_bytes_per_second, 0.65),
                tx_bytes_per_second=_scaled(base.tx_bytes_per_second, 0.81),
                active_sessions=max(1, base.active_sessions - 2),
                page_entries_per_minute=base.page_entries_per_minute * 0.78,
            ),
            replace(
                base,
                cpu_percent=_scaled(base.cpu_percent, 1.16),
                memory_bytes=_scaled(base.memory_bytes, 1.08),
                rx_bytes_per_second=_scaled(base.rx_bytes_per_second, 1.24),
                tx_bytes_per_second=_scaled(base.tx_bytes_per_second, 1.13),
                active_sessions=base.active_sessions + 1,
                page_entries_per_minute=base.page_entries_per_minute * 1.12,
            ),
        )


class DynamoHeartbeatStore:
    """Read and write the dedicated sanitized DynamoDB table."""

    source_label = "Live aggregate from reporting ECS tasks"
    deterministic = False

    def __init__(self, table_name: str, *, client: Any | None = None) -> None:
        if not table_name or any(character.isspace() for character in table_name):
            raise ValueError("monitor table name must be non-empty and contain no whitespace")
        if client is None:
            client = boto3.client(
                "dynamodb",
                config=Config(connect_timeout=0.5, read_timeout=1.0, retries={"max_attempts": 2}),
            )
        self._table_name = table_name
        self._client = client

    def put(self, publisher: str, heartbeat: Heartbeat) -> None:
        self._client.put_item(
            TableName=self._table_name,
            Item={
                "publisher": {"S": publisher},
                "updated_at": {"N": str(round(heartbeat.published_at, 3))},
                "expires_at": {"N": str(heartbeat.expires_at)},
                "payload": {"B": encode_heartbeat(heartbeat)},
            },
        )

    def read(self) -> tuple[Heartbeat, ...]:
        response = self._client.scan(
            TableName=self._table_name,
            ProjectionExpression="payload",
            ConsistentRead=False,
            Limit=MAX_HEARTBEATS,
        )
        heartbeats = []
        for item in response.get("Items", ()):  # Publisher keys never leave DynamoDB.
            payload = item.get("payload", {}).get("B") if isinstance(item, dict) else None
            if isinstance(payload, (bytes, bytearray)):
                try:
                    heartbeats.append(decode_heartbeat(bytes(payload)))
                except (TypeError, ValueError, zlib.error):
                    LOGGER.warning("Discarded an invalid sanitized monitor heartbeat")
        return tuple(heartbeats)


class ServiceMonitor:
    """Run one coalesced publisher and reader loop for the process."""

    def __init__(
        self,
        sampler: CoalescedSampler,
        store: HeartbeatStore,
        *,
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        allow_deterministic: bool = False,
    ) -> None:
        self._sampler = sampler
        self._store = store
        self._interval_seconds = interval_seconds
        self._allow_deterministic = allow_deterministic
        self._publisher = secrets.token_hex(16)
        self._generation = 0
        self._sample = _unavailable_sample(0, "warming_up", self._store.source_label)
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start the process-wide exchange loop once."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name="demo-monitor-heartbeat", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the exchange loop during ASGI shutdown."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def sample(self) -> ServiceSample:
        """Return the latest in-process aggregate without an AWS call."""
        with self._lock:
            return self._sample

    def tick(self, *, now: float | None = None, sampled_at: float | None = None) -> ServiceSample:
        """Publish this process and rebuild the service aggregate once."""
        wall_time = time() if now is None else now
        monotonic_time = monotonic() if sampled_at is None else sampled_at
        local = self._sampler.sample(now=monotonic_time, wall_time=wall_time)
        try:
            if not local.deterministic or self._allow_deterministic:
                self._store.put(self._publisher, heartbeat_from_sample(local, wall_time))
            heartbeats = tuple(
                heartbeat
                for heartbeat in self._store.read()
                if 0 <= wall_time - heartbeat.published_at <= HEARTBEAT_MAX_AGE_SECONDS
            )
            self._generation += 1
            result = aggregate_heartbeats(
                heartbeats,
                generation=self._generation,
                now=wall_time,
                source_label=self._store.source_label,
                deterministic=self._store.deterministic,
            )
        except Exception:
            LOGGER.warning("Service monitor exchange failed", exc_info=True)
            self._generation += 1
            result = _unavailable_sample(
                self._generation, "service_data_unavailable", self._store.source_label
            )
        with self._lock:
            self._sample = result
        return result

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._interval_seconds)


def create_service_monitor(
    sampler: CoalescedSampler, environment: Mapping[str, str] = os.environ
) -> ServiceMonitor:
    """Select DynamoDB, local, or deterministic service aggregation."""
    mode = environment.get("DEMO_MONITOR_GLOBAL_SOURCE", "auto").casefold()
    deterministic = environment.get("DEMO_MONITOR_SOURCE", "auto").casefold() in {
        "demo",
        "deterministic",
    }
    if mode == "deterministic" or deterministic:
        return ServiceMonitor(sampler, DeterministicHeartbeatStore(), allow_deterministic=True)
    if mode not in {"auto", "dynamodb", "local"}:
        raise ValueError(
            "DEMO_MONITOR_GLOBAL_SOURCE must be auto, dynamodb, local, or deterministic"
        )
    table_name = environment.get("DEMO_MONITOR_TABLE")
    if mode != "local" and table_name:
        return ServiceMonitor(sampler, DynamoHeartbeatStore(table_name))
    if mode == "dynamodb":
        raise ValueError("DynamoDB monitor source requested without DEMO_MONITOR_TABLE")
    return ServiceMonitor(sampler, InMemoryHeartbeatStore())


def heartbeat_from_sample(sample: MonitorSample, published_at: float) -> Heartbeat:
    """Copy only the explicit public fields into a storage heartbeat."""
    return Heartbeat(
        published_at=published_at,
        expires_at=math.ceil(published_at + HEARTBEAT_TTL_SECONDS),
        cpu_percent=sample.cpu_percent,
        cpu_capacity_vcpus=sample.cpu_capacity_vcpus,
        memory_bytes=sample.memory_bytes,
        memory_capacity_bytes=sample.memory_capacity_bytes,
        rx_bytes_per_second=sample.rx_bytes_per_second,
        tx_bytes_per_second=sample.tx_bytes_per_second,
        active_sessions=max(0, sample.active_sessions),
        page_entries_per_minute=max(0.0, sample.requests_per_minute),
        callback_count=max(0, sample.callback_count),
        callback_window_seconds=max(1.0, sample.callback_window_seconds),
        callback_max_ms=sample.callback_max_ms,
        callback_histogram=sample.callback_histogram,
        event_loop_max_ms=sample.event_loop_max_ms,
        event_loop_histogram=sample.event_loop_histogram,
        callbacks_by_app=sample.callbacks_by_app,
        event_loop_by_app=sample.event_loop_by_app,
        slowest_callbacks=sample.slowest_callbacks,
    )


def aggregate_heartbeats(
    heartbeats: tuple[Heartbeat, ...],
    *,
    generation: int,
    now: float,
    source_label: str,
    deterministic: bool,
) -> ServiceSample:
    """Combine fresh task rows without exposing their publisher keys."""
    if not heartbeats:
        return _unavailable_sample(generation, "no_fresh_heartbeats", source_label)
    cpu_capacity = _sum_optional(heartbeat.cpu_capacity_vcpus for heartbeat in heartbeats)
    cpu_vcpus = _sum_optional(
        heartbeat.cpu_capacity_vcpus * heartbeat.cpu_percent / 100
        for heartbeat in heartbeats
        if heartbeat.cpu_capacity_vcpus is not None and heartbeat.cpu_percent is not None
    )
    memory = _sum_optional(heartbeat.memory_bytes for heartbeat in heartbeats)
    memory_capacity = _sum_optional(heartbeat.memory_capacity_bytes for heartbeat in heartbeats)
    callback_histogram = _merge_histograms(heartbeat.callback_histogram for heartbeat in heartbeats)
    event_loop_histogram = _merge_histograms(
        heartbeat.event_loop_histogram for heartbeat in heartbeats
    )
    callback_max = _max_optional(heartbeat.callback_max_ms for heartbeat in heartbeats)
    event_loop_max = _max_optional(heartbeat.event_loop_max_ms for heartbeat in heartbeats)
    return ServiceSample(
        generation=generation,
        timestamp_ms=1000 * now,
        status="simulated" if deterministic else "ok",
        reason=None,
        source_label=source_label,
        deterministic=deterministic,
        freshness_seconds=max(0.0, now - max(item.published_at for item in heartbeats)),
        reporting_tasks=len(heartbeats),
        active_sessions=sum(item.active_sessions for item in heartbeats),
        page_entries_per_minute=sum(item.page_entries_per_minute for item in heartbeats),
        cpu_vcpus=cpu_vcpus,
        cpu_percent=(
            None if cpu_vcpus is None or not cpu_capacity else 100 * cpu_vcpus / cpu_capacity
        ),
        memory_bytes=memory,
        memory_capacity_bytes=memory_capacity,
        memory_percent=(
            None if memory is None or not memory_capacity else 100 * memory / memory_capacity
        ),
        rx_bytes_per_second=_sum_optional(
            heartbeat.rx_bytes_per_second for heartbeat in heartbeats
        ),
        tx_bytes_per_second=_sum_optional(
            heartbeat.tx_bytes_per_second for heartbeat in heartbeats
        ),
        callback_rate=sum(
            heartbeat.callback_count / heartbeat.callback_window_seconds for heartbeat in heartbeats
        ),
        callback_p95_ms=histogram_percentile(callback_histogram, maximum=callback_max),
        event_loop_p95_ms=histogram_percentile(event_loop_histogram, maximum=event_loop_max),
        callbacks_by_app=_merge_app_timings(
            timing for heartbeat in heartbeats for timing in heartbeat.callbacks_by_app
        ),
        event_loop_by_app=_merge_app_timings(
            timing for heartbeat in heartbeats for timing in heartbeat.event_loop_by_app
        ),
        slowest_callbacks=_merge_callback_timings(
            timing for heartbeat in heartbeats for timing in heartbeat.slowest_callbacks
        ),
    )


def encode_heartbeat(heartbeat: Heartbeat) -> bytes:
    """Encode the allowlisted contract as bounded compressed JSON."""
    payload = {
        "v": 1,
        "at": heartbeat.published_at,
        "ttl": heartbeat.expires_at,
        "cpu": heartbeat.cpu_percent,
        "cpu_cap": heartbeat.cpu_capacity_vcpus,
        "mem": heartbeat.memory_bytes,
        "mem_cap": heartbeat.memory_capacity_bytes,
        "rx": heartbeat.rx_bytes_per_second,
        "tx": heartbeat.tx_bytes_per_second,
        "sessions": heartbeat.active_sessions,
        "pages": heartbeat.page_entries_per_minute,
        "cb_count": heartbeat.callback_count,
        "window": heartbeat.callback_window_seconds,
        "cb_max": heartbeat.callback_max_ms,
        "cb_hist": heartbeat.callback_histogram,
        "loop_max": heartbeat.event_loop_max_ms,
        "loop_hist": heartbeat.event_loop_histogram,
        "apps": [_encode_app(timing) for timing in heartbeat.callbacks_by_app],
        "loops": [_encode_app(timing) for timing in heartbeat.event_loop_by_app],
        "callbacks": [_encode_callback(timing) for timing in heartbeat.slowest_callbacks],
    }
    encoded = zlib.compress(json.dumps(payload, separators=(",", ":")).encode(), level=9)
    if len(encoded) > MAX_ENCODED_BYTES:
        raise ValueError("sanitized heartbeat exceeds its storage bound")
    return encoded


def decode_heartbeat(encoded: bytes) -> Heartbeat:
    """Validate a stored heartbeat before it enters the public aggregate."""
    if len(encoded) > MAX_ENCODED_BYTES:
        raise ValueError("encoded heartbeat exceeds its storage bound")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(encoded, MAX_ENCODED_BYTES + 1)
    if decoder.unconsumed_tail or len(raw) > MAX_ENCODED_BYTES:
        raise ValueError("decoded heartbeat exceeds its storage bound")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("unknown monitor heartbeat schema")
    return Heartbeat(
        published_at=_finite(payload.get("at")),
        expires_at=int(_finite(payload.get("ttl"))),
        cpu_percent=_optional_finite(payload.get("cpu")),
        cpu_capacity_vcpus=_optional_finite(payload.get("cpu_cap")),
        memory_bytes=_optional_finite(payload.get("mem")),
        memory_capacity_bytes=_optional_finite(payload.get("mem_cap")),
        rx_bytes_per_second=_optional_finite(payload.get("rx")),
        tx_bytes_per_second=_optional_finite(payload.get("tx")),
        active_sessions=max(0, int(_finite(payload.get("sessions")))),
        page_entries_per_minute=max(0.0, _finite(payload.get("pages"))),
        callback_count=max(0, int(_finite(payload.get("cb_count")))),
        callback_window_seconds=max(1.0, _finite(payload.get("window"))),
        callback_max_ms=_optional_finite(payload.get("cb_max")),
        callback_histogram=_histogram(payload.get("cb_hist")),
        event_loop_max_ms=_optional_finite(payload.get("loop_max")),
        event_loop_histogram=_histogram(payload.get("loop_hist")),
        callbacks_by_app=_decode_apps(payload.get("apps")),
        event_loop_by_app=_decode_apps(payload.get("loops")),
        slowest_callbacks=_decode_callbacks(payload.get("callbacks")),
    )


def _encode_app(timing: AppTiming) -> list[Any]:
    return [timing.app, timing.count, timing.max_ms, timing.histogram]


def _encode_callback(timing: CallbackTiming) -> list[Any]:
    return [timing.app, timing.callback, timing.count, timing.max_ms, timing.histogram]


def _decode_apps(value: object) -> tuple[AppTiming, ...]:
    if not isinstance(value, list):
        raise ValueError("app timings must be a list")
    result = []
    for row in value:
        if not isinstance(row, list) or len(row) != 4 or row[0] not in PUBLIC_APP_ROUTES:
            raise ValueError("app timing contains a non-public route")
        histogram = _histogram(row[3])
        maximum = max(0.0, _finite(row[2]))
        result.append(
            AppTiming(
                app=row[0],
                count=max(0, int(_finite(row[1]))),
                p95_ms=histogram_percentile(histogram, maximum=maximum) or 0.0,
                max_ms=maximum,
                histogram=histogram,
            )
        )
    return tuple(result)


def _decode_callbacks(value: object) -> tuple[CallbackTiming, ...]:
    if not isinstance(value, list):
        raise ValueError("callback timings must be a list")
    result = []
    for row in value:
        if (
            not isinstance(row, list)
            or len(row) != 5
            or row[0] not in PUBLIC_APP_ROUTES
            or row[1] not in PUBLIC_CALLBACKS_BY_ROUTE.get(row[0], ())
        ):
            raise ValueError("callback timing contains a non-public label")
        histogram = _histogram(row[4])
        maximum = max(0.0, _finite(row[3]))
        result.append(
            CallbackTiming(
                app=row[0],
                callback=row[1],
                count=max(0, int(_finite(row[2]))),
                p95_ms=histogram_percentile(histogram, maximum=maximum) or 0.0,
                max_ms=maximum,
                histogram=histogram,
            )
        )
    return tuple(result)


def _merge_app_timings(timings: Any) -> tuple[AppTiming, ...]:
    grouped: dict[str, tuple[int, float, tuple[int, ...]]] = {}
    for timing in timings:
        count, maximum, histogram = grouped.get(
            timing.app, (0, 0.0, tuple(0 for _ in timing.histogram))
        )
        grouped[timing.app] = (
            count + timing.count,
            max(maximum, timing.max_ms),
            _merge_histograms((histogram, timing.histogram)),
        )
    result = (
        AppTiming(
            app=app,
            count=count,
            p95_ms=histogram_percentile(histogram, maximum=maximum) or 0.0,
            max_ms=maximum,
            histogram=histogram,
        )
        for app, (count, maximum, histogram) in grouped.items()
    )
    return tuple(sorted(result, key=lambda item: item.max_ms, reverse=True))[:8]


def _merge_callback_timings(timings: Any) -> tuple[CallbackTiming, ...]:
    grouped: dict[tuple[str, str], tuple[int, float, tuple[int, ...]]] = {}
    for timing in timings:
        key = (timing.app, timing.callback)
        count, maximum, histogram = grouped.get(key, (0, 0.0, tuple(0 for _ in timing.histogram)))
        grouped[key] = (
            count + timing.count,
            max(maximum, timing.max_ms),
            _merge_histograms((histogram, timing.histogram)),
        )
    result = (
        CallbackTiming(
            app=app,
            callback=callback,
            count=count,
            p95_ms=histogram_percentile(histogram, maximum=maximum) or 0.0,
            max_ms=maximum,
            histogram=histogram,
        )
        for (app, callback), (count, maximum, histogram) in grouped.items()
    )
    return tuple(sorted(result, key=lambda item: item.max_ms, reverse=True))[:12]


def _histogram(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != len(PUBLIC_LATENCY_BUCKETS_MS) + 1:
        raise ValueError("latency histogram has an invalid shape")
    result = tuple(int(_finite(count)) for count in value)
    if any(count < 0 for count in result):
        raise ValueError("latency histogram counts must be non-negative")
    return result


def _merge_histograms(histograms: Any) -> tuple[int, ...]:
    result: list[int] = []
    for histogram in histograms:
        if not result:
            result = [0] * len(histogram)
        if len(histogram) != len(result):
            raise ValueError("latency histogram shapes do not match")
        for index, count in enumerate(histogram):
            result[index] += count
    return tuple(result)


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("monitor measurement must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("monitor measurement must be finite")
    return result


def _optional_finite(value: object) -> float | None:
    return None if value is None else _finite(value)


def _sum_optional(values: Any) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _max_optional(values: Any) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _unavailable_sample(generation: int, reason: str, source_label: str) -> ServiceSample:
    return ServiceSample(
        generation=generation,
        timestamp_ms=1000 * time(),
        status="degraded",
        reason=reason,
        source_label=source_label,
        deterministic=False,
        freshness_seconds=None,
        reporting_tasks=0,
        active_sessions=0,
        page_entries_per_minute=0.0,
        cpu_vcpus=None,
        cpu_percent=None,
        memory_bytes=None,
        memory_capacity_bytes=None,
        memory_percent=None,
        rx_bytes_per_second=None,
        tx_bytes_per_second=None,
        callback_rate=0.0,
        callback_p95_ms=None,
        event_loop_p95_ms=None,
        callbacks_by_app=(),
        event_loop_by_app=(),
        slowest_callbacks=(),
    )
