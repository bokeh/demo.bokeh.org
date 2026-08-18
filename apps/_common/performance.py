"""Measure per-session callback time and event-loop lag for demo applications."""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from math import ceil
from threading import Lock
from time import perf_counter
from typing import Any, ParamSpec, TypeVar
from weakref import WeakKeyDictionary

from bokeh.document import Document

from catalog import DEMOS

P = ParamSpec("P")
R = TypeVar("R")

LOGGER = logging.getLogger("demo.performance")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.propagate = False
LOGGER.setLevel(logging.INFO)

PERFORMANCE_ENABLED = os.getenv("DEMO_PERFORMANCE", "1").casefold() not in {"0", "false", "no"}
LOOP_INTERVAL_SECONDS = 1.0
REPORT_INTERVAL_SECONDS = 60.0
RECENT_SAMPLE_LIMIT = 256
LAG_REPORT_THRESHOLD_MS = 20.0
PUBLIC_WINDOW_SECONDS = 60.0
PUBLIC_CALLBACK_SAMPLE_LIMIT = 4096
PUBLIC_EVENT_LOOP_SAMPLE_LIMIT = 1024
PUBLIC_APP_ROW_LIMIT = 8
PUBLIC_CALLBACK_ROW_LIMIT = 12

# Callback labels are code identifiers from this public repository, but they are
# still explicitly allowlisted so an accidental runtime label can never become
# browser-visible telemetry.
PUBLIC_CALLBACKS_BY_ROUTE = {
    "/airport-access": frozenset({"choose_airport", "choose_state", "tap_airport"}),
    "/cellular-automata": frozenset(
        {
            "advance",
            "brush_changed",
            "clear_field",
            "comparison_custom_rule_changed",
            "comparison_rule_changed",
            "density_changed",
            "edit_field",
            "experiment_changed",
            "flip_brush",
            "load_seed",
            "primary_custom_rule_changed",
            "rotate_brush",
            "rule_changed",
            "seed_changed",
            "step_once",
            "toggle_playing",
            "toggle_wrap",
        }
    ),
    "/chaotic-motion": frozenset(
        {"advance_active", "parameters_changed", "reset_oscillator", "running_changed"}
    ),
    "/climate": frozenset({"update"}),
    "/image-processing": frozenset(
        {"configure_filter", "restore_crop", "update_crop", "update_strength"}
    ),
    "/market-monitor": frozenset(
        {"advance", "inject_selloff", "playback_changed", "regime_changed", "reset_simulation"}
    ),
    "/mobility": frozenset({"update_filter", "update_selection"}),
    "/research-lineage": frozenset(
        {"graph_changed", "graph_selected", "lineage_changed", "paper_changed", "view_changed"}
    ),
    "/spectrum-monitor": frozenset(
        {
            "filter_mode_changed",
            "filter_settings_changed",
            "playback_changed",
            "queue_transient",
            "reset_signal",
            "scene_changed",
            "tune_filter",
            "update_receiver",
        }
    ),
    "/task-scheduler": frozenset(
        {
            "advance",
            "critical_changed",
            "interrupt_worker",
            "playback_changed",
            "reset_simulation",
            "selection_changed",
            "settings_changed",
            "slow_task",
        }
    ),
    "/terrain-contours": frozenset(
        {"choose_landform", "move_transect", "reset_transect", "toggle_outlines"}
    ),
    "/wave-field": frozenset({"update_cross_section", "update_field", "update_palette"}),
}
PUBLIC_APP_ROUTES = frozenset(demo.route for demo in DEMOS if demo.route != "/monitor")


@dataclass(slots=True)
class Samples:
    """Accumulate bounded timing statistics for one reporting window."""

    count: int = 0
    total_ms: float = 0.0
    maximum_ms: float = 0.0
    recent_ms: deque[float] = field(default_factory=lambda: deque(maxlen=RECENT_SAMPLE_LIMIT))

    def add(self, elapsed_ms: float) -> None:
        """Record one duration in milliseconds."""
        self.count += 1
        self.total_ms += elapsed_ms
        self.maximum_ms = max(self.maximum_ms, elapsed_ms)
        self.recent_ms.append(elapsed_ms)

    def summary(self) -> dict[str, int | float]:
        """Return count, mean, p95, and maximum duration values."""
        ordered = sorted(self.recent_ms)
        p95_index = max(0, ceil(0.95 * len(ordered)) - 1)
        return {
            "count": self.count,
            "mean_ms": round(self.total_ms / self.count, 3),
            "p95_ms": round(ordered[p95_index], 3),
            "max_ms": round(self.maximum_ms, 3),
        }


@dataclass(frozen=True, slots=True)
class AppTiming:
    """A browser-safe aggregate for one public application route."""

    app: str
    count: int
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class CallbackTiming:
    """A browser-safe aggregate for one explicitly public callback label."""

    app: str
    callback: str
    count: int
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class PerformanceSnapshot:
    """Sanitized process-wide timing values safe to place in a public document."""

    window_seconds: float
    callback_count: int
    callback_p95_ms: float | None
    callback_max_ms: float | None
    event_loop_p95_ms: float | None
    event_loop_max_ms: float | None
    callbacks_by_app: tuple[AppTiming, ...] = ()
    event_loop_by_app: tuple[AppTiming, ...] = ()
    slowest_callbacks: tuple[CallbackTiming, ...] = ()


class PublicPerformance:
    """Keep a bounded process view with only explicitly public labels."""

    def __init__(self, *, window_seconds: float = PUBLIC_WINDOW_SECONDS) -> None:
        self.window_seconds = window_seconds
        self._callbacks: deque[tuple[float, float, str | None, str | None]] = deque(
            maxlen=PUBLIC_CALLBACK_SAMPLE_LIMIT
        )
        self._event_loop: deque[tuple[float, float]] = deque(maxlen=PUBLIC_EVENT_LOOP_SAMPLE_LIMIT)
        self._event_loop_by_app: deque[tuple[float, float, str]] = deque(
            maxlen=PUBLIC_EVENT_LOOP_SAMPLE_LIMIT
        )
        self._last_loop_bucket: int | None = None
        self._last_app_loop_bucket: dict[str, int] = {}
        self._lock = Lock()

    def record_callback(
        self,
        elapsed_ms: float,
        *,
        route: str | None = None,
        callback: str | None = None,
        now: float | None = None,
    ) -> None:
        """Record a duration with only allowlisted public labels attached."""
        sampled_at = perf_counter() if now is None else now
        public_route = route if route in PUBLIC_APP_ROUTES else None
        allowed_callbacks = (
            PUBLIC_CALLBACKS_BY_ROUTE.get(public_route, ()) if public_route is not None else ()
        )
        public_callback = callback if callback in allowed_callbacks else None
        with self._lock:
            self._callbacks.append((sampled_at, elapsed_ms, public_route, public_callback))
            self._prune(sampled_at)

    def record_event_loop(
        self, lag_ms: float, *, route: str | None = None, now: float | None = None
    ) -> None:
        """Record bounded process-wide and public-route lag observations."""
        sampled_at = perf_counter() if now is None else now
        bucket = int(sampled_at / LOOP_INTERVAL_SECONDS)
        with self._lock:
            if bucket != self._last_loop_bucket:
                self._last_loop_bucket = bucket
                self._event_loop.append((sampled_at, lag_ms))
            if route in PUBLIC_APP_ROUTES and bucket != self._last_app_loop_bucket.get(route):
                self._last_app_loop_bucket[route] = bucket
                self._event_loop_by_app.append((sampled_at, lag_ms, route))
            self._prune(sampled_at)

    def snapshot(self, *, now: float | None = None) -> PerformanceSnapshot:
        """Return only aggregate numeric timing values for the rolling window."""
        sampled_at = perf_counter() if now is None else now
        with self._lock:
            self._prune(sampled_at)
            callbacks = [value for _timestamp, value, _app, _callback in self._callbacks]
            event_loop = [value for _timestamp, value in self._event_loop]
            callbacks_by_app = self._callback_app_timings(self._callbacks)
            event_loop_by_app = self._event_loop_app_timings(self._event_loop_by_app)
            slowest_callbacks = self._callback_timings(self._callbacks)
        return PerformanceSnapshot(
            window_seconds=self.window_seconds,
            callback_count=len(callbacks),
            callback_p95_ms=self._percentile(callbacks),
            callback_max_ms=max(callbacks, default=None),
            event_loop_p95_ms=self._percentile(event_loop),
            event_loop_max_ms=max(event_loop, default=None),
            callbacks_by_app=callbacks_by_app,
            event_loop_by_app=event_loop_by_app,
            slowest_callbacks=slowest_callbacks,
        )

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for samples in (self._callbacks, self._event_loop, self._event_loop_by_app):
            while samples and samples[0][0] < cutoff:
                samples.popleft()

    @classmethod
    def _callback_app_timings(
        cls, samples: deque[tuple[float, float, str | None, str | None]]
    ) -> tuple[AppTiming, ...]:
        grouped: dict[str, list[float]] = {}
        for _timestamp, elapsed_ms, app, _callback in samples:
            if app is not None:
                grouped.setdefault(app, []).append(elapsed_ms)
        return cls._summarize_apps(grouped)

    @classmethod
    def _event_loop_app_timings(
        cls, samples: deque[tuple[float, float, str]]
    ) -> tuple[AppTiming, ...]:
        grouped: dict[str, list[float]] = {}
        for _timestamp, lag_ms, app in samples:
            grouped.setdefault(app, []).append(lag_ms)
        return cls._summarize_apps(grouped)

    @classmethod
    def _summarize_apps(cls, grouped: dict[str, list[float]]) -> tuple[AppTiming, ...]:
        timings = (
            AppTiming(
                app=app,
                count=len(values),
                p95_ms=cls._percentile(values) or 0.0,
                max_ms=max(values),
            )
            for app, values in grouped.items()
        )
        return tuple(sorted(timings, key=lambda timing: timing.max_ms, reverse=True))[
            :PUBLIC_APP_ROW_LIMIT
        ]

    @classmethod
    def _callback_timings(
        cls, samples: deque[tuple[float, float, str | None, str | None]]
    ) -> tuple[CallbackTiming, ...]:
        grouped: dict[tuple[str, str], list[float]] = {}
        for _timestamp, elapsed_ms, app, callback in samples:
            if app is not None and callback is not None:
                grouped.setdefault((app, callback), []).append(elapsed_ms)
        timings = (
            CallbackTiming(
                app=app,
                callback=callback,
                count=len(values),
                p95_ms=cls._percentile(values) or 0.0,
                max_ms=max(values),
            )
            for (app, callback), values in grouped.items()
        )
        return tuple(sorted(timings, key=lambda timing: timing.max_ms, reverse=True))[
            :PUBLIC_CALLBACK_ROW_LIMIT
        ]

    @staticmethod
    def _percentile(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[max(0, ceil(0.95 * len(ordered)) - 1)]


PUBLIC_PERFORMANCE = PublicPerformance()


class PerformanceMonitor:
    """Collect callback and event-loop timing for one Bokeh document."""

    def __init__(self, route: str, *, enabled: bool = PERFORMANCE_ENABLED) -> None:
        self.route = route
        self.enabled = enabled
        self.callbacks: dict[str, Samples] = {}
        self.event_loop_lag = Samples()
        self.started = False
        self.last_loop_time = 0.0
        self.last_report_time = 0.0

    def measure(self, callback: Callable[P, R], *, name: str | None = None) -> Callable[P, R]:
        """Wrap a Python callback and aggregate its execution duration."""
        if not self.enabled:
            return callback
        callback_name = name or callback.__name__

        @wraps(callback)
        def timed_callback(*args: P.args, **kwargs: P.kwargs) -> R:
            started = perf_counter()
            try:
                return callback(*args, **kwargs)
            finally:
                elapsed_ms = 1000 * (perf_counter() - started)
                self.callbacks.setdefault(callback_name, Samples()).add(elapsed_ms)
                PUBLIC_PERFORMANCE.record_callback(
                    elapsed_ms, route=self.route, callback=callback_name
                )

        return timed_callback

    def start(self, document: Document) -> None:
        """Begin periodic lag sampling after the application is assembled."""
        if self.started or not self.enabled:
            return
        self.started = True
        now = perf_counter()
        self.last_loop_time = now
        self.last_report_time = now
        document.add_periodic_callback(self.observe_event_loop, int(1000 * LOOP_INTERVAL_SECONDS))

        def session_destroyed(_session_context: Any) -> None:
            self.report(force=True)

        document.on_session_destroyed(session_destroyed)

    def observe_event_loop(self) -> None:
        """Sample scheduling delay and emit summaries at the reporting interval."""
        now = perf_counter()
        elapsed = now - self.last_loop_time
        self.last_loop_time = now
        lag_ms = 1000 * max(0.0, elapsed - LOOP_INTERVAL_SECONDS)
        self.event_loop_lag.add(lag_ms)
        PUBLIC_PERFORMANCE.record_event_loop(lag_ms, route=self.route, now=now)
        self.report(now=now)

    def report(self, *, now: float | None = None, force: bool = False) -> None:
        """Write structured summaries suitable for CloudWatch Logs Insights."""
        current = perf_counter() if now is None else now
        if not force and current - self.last_report_time < REPORT_INTERVAL_SECONDS:
            return
        window_seconds = round(current - self.last_report_time, 3)
        self.last_report_time = current
        callback_activity = False
        for callback_name, samples in self.callbacks.items():
            if samples.count:
                callback_activity = True
                self.log_summary("demo.callback", samples, window_seconds, callback=callback_name)
        if self.event_loop_lag.count and (
            callback_activity or self.event_loop_lag.maximum_ms >= LAG_REPORT_THRESHOLD_MS
        ):
            self.log_summary("demo.event_loop_lag", self.event_loop_lag, window_seconds)
        self.callbacks.clear()
        self.event_loop_lag = Samples()

    def log_summary(
        self, event: str, samples: Samples, window_seconds: float, **fields: str
    ) -> None:
        """Emit one compact JSON timing summary."""
        payload = {
            "event": event,
            "app": self.route,
            "window_seconds": window_seconds,
            **fields,
            **samples.summary(),
        }
        LOGGER.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))


MONITORS: WeakKeyDictionary[Document, PerformanceMonitor] = WeakKeyDictionary()


def monitor_document(document: Document, route: str) -> PerformanceMonitor:
    """Return the performance monitor associated with a Bokeh document."""
    monitor = MONITORS.get(document)
    if monitor is None:
        monitor = PerformanceMonitor(route)
        MONITORS[document] = monitor
    elif monitor.route != route:
        raise ValueError(f"Document already belongs to {monitor.route}, not {route}")
    return monitor
