"""Test shared demo performance instrumentation."""

from __future__ import annotations

import json
from time import perf_counter

from bokeh.document import Document

from apps._common.performance import LOGGER, PerformanceMonitor, monitor_document


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
