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
from time import perf_counter
from typing import Any, ParamSpec, TypeVar
from weakref import WeakKeyDictionary

from bokeh.document import Document

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
        self.event_loop_lag.add(1000 * max(0.0, elapsed - LOOP_INTERVAL_SECONDS))
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
