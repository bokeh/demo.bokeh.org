"""Test shared demo performance instrumentation."""

from __future__ import annotations

import json
from dataclasses import asdict
from time import perf_counter

from bokeh.document import Document

from apps._common.performance import LOGGER, PerformanceMonitor, PublicPerformance, monitor_document


def test_performance_monitor_reports_callback_duration(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(LOGGER, "info", messages.append)
    monitor = PerformanceMonitor("/example")

    @monitor.measure
    def calculate(value: int) -> int:
        return value * 2

    assert calculate(3) == 6
    monitor.report(force=True)

    payload = json.loads(messages[-1])
    assert payload["event"] == "demo.callback"
    assert payload["app"] == "/example"
    assert payload["callback"] == "calculate"
    assert payload["count"] == 1
    assert payload["mean_ms"] >= 0
    assert payload["p95_ms"] >= 0
    assert payload["max_ms"] >= 0


def test_monitor_document_samples_event_loop_lag_once_per_document(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(LOGGER, "info", messages.append)
    document = Document()
    monitor = monitor_document(document, "/example")
    monitor.start(document)
    monitor.start(document)
    assert len(document.session_callbacks) == 1

    monitor.last_loop_time = perf_counter() - 1.025
    document.session_callbacks[0].callback()
    monitor.report(force=True)

    payload = json.loads(messages[-1])
    assert payload["event"] == "demo.event_loop_lag"
    assert payload["app"] == "/example"
    assert payload["count"] == 1
    assert payload["max_ms"] >= 20


def test_disabled_performance_monitor_is_a_no_op() -> None:
    document = Document()
    monitor = PerformanceMonitor("/example", enabled=False)

    def calculate(value: int) -> int:
        return value * 2

    assert monitor.measure(calculate) is calculate
    monitor.start(document)
    assert document.session_callbacks == []


def test_performance_monitor_suppresses_normal_idle_lag(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(LOGGER, "info", messages.append)
    monitor = PerformanceMonitor("/example")
    monitor.event_loop_lag.add(1.5)

    monitor.report(force=True)

    assert messages == []


def test_public_performance_is_numeric_bounded_and_coalesces_loop_samples() -> None:
    performance = PublicPerformance(window_seconds=10)
    performance.record_callback(2.0, now=1.0)
    performance.record_callback(8.0, now=2.0)
    performance.record_event_loop(1.0, now=2.1)
    performance.record_event_loop(99.0, now=2.2)
    performance.record_event_loop(3.0, now=3.1)

    snapshot = performance.snapshot(now=4.0)

    assert snapshot.callback_count == 2
    assert snapshot.callback_p95_ms == 8.0
    assert snapshot.callback_max_ms == 8.0
    assert snapshot.event_loop_p95_ms == 3.0
    assert snapshot.event_loop_max_ms == 3.0

    assert performance.snapshot(now=20.0).callback_count == 0


def test_public_performance_exposes_only_catalog_and_allowlisted_labels() -> None:
    performance = PublicPerformance(window_seconds=10)
    performance.record_callback(8.0, route="/market-monitor", callback="advance", now=1.0)
    performance.record_callback(
        21.0, route="/market-monitor", callback="private-runtime-label", now=2.0
    )
    performance.record_callback(99.0, route="arn:aws:ecs:private", callback="advance", now=2.5)
    performance.record_event_loop(3.0, route="/market-monitor", now=2.1)
    performance.record_event_loop(5.0, route="/market-monitor", now=3.1)
    performance.record_event_loop(88.0, route="private-service-name", now=4.1)

    snapshot = performance.snapshot(now=5.0)

    assert len(snapshot.callbacks_by_app) == 1
    assert snapshot.callbacks_by_app[0].app == "/market-monitor"
    assert snapshot.callbacks_by_app[0].count == 2
    assert snapshot.callbacks_by_app[0].max_ms == 21.0
    assert len(snapshot.slowest_callbacks) == 1
    assert snapshot.slowest_callbacks[0].callback == "advance"
    assert snapshot.event_loop_by_app[0].app == "/market-monitor"
    assert snapshot.event_loop_by_app[0].count == 2

    serialized = json.dumps(asdict(snapshot))
    assert "private-runtime-label" not in serialized
    assert "private-service-name" not in serialized
    assert "arn:aws" not in serialized
