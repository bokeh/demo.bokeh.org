"""Show a privacy-bounded view of the whole demo service."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, cast

import numpy as np
from bokeh.layouts import column
from bokeh.models import ColumnDataSource, DataRange1d, DatetimeTickFormatter, Div, Range1d, Title
from bokeh.plotting import figure

from apps._common import (
    metric,
    metric_row,
    prepare_document,
    responsive_row,
    set_metric,
    style_figure,
)
from apps._common.colors import CORAL, GOLD, MUTED, PLUM, TEAL, VIOLET
from apps._common.performance import AppTiming, CallbackTiming

from .global_metrics import ServiceMonitor, ServiceSample, create_service_monitor
from .metrics import CoalescedSampler, create_adapter

ROUTE = "/monitor"
REFRESH_INTERVAL_MS = 2_000
HISTORY_SECONDS = 300
HISTORY_POINTS = HISTORY_SECONDS * 1_000 // REFRESH_INTERVAL_MS
SAMPLER = CoalescedSampler(create_adapter())
SERVICE_MONITOR = create_service_monitor(SAMPLER)
DASHBOARD_METRIC_CSS = Path(__file__).with_name("dashboard_metric.css").read_text()


def modify_document(document) -> None:
    """Build the public monitor using the process-wide coalesced sampler."""
    build_document(document, SERVICE_MONITOR)


def build_document(document, service_monitor: ServiceMonitor) -> None:
    """Build a monitor document around an injectable service monitor for tests."""
    source = ColumnDataSource(
        data={
            "time": np.array([], dtype=np.float64),
            "cpu": np.array([], dtype=np.float32),
            "memory": np.array([], dtype=np.float32),
            "callback_p95": np.array([], dtype=np.float32),
            "event_loop_p95": np.array([], dtype=np.float32),
            "rx_kib": np.array([], dtype=np.float32),
            "tx_kib": np.array([], dtype=np.float32),
        },
        name="monitor-history",
    )
    tasks_card = metric("Running containers", "Warming up", accent=GOLD)
    service_sessions_card = metric("Current viewers", "Warming up", accent=TEAL)
    service_pages_card = metric("Page views", "Warming up", accent=CORAL)
    service_lag_card = metric("Event-loop lag", "Warming up", accent=VIOLET)
    for card in (tasks_card, service_sessions_card, service_pages_card, service_lag_card):
        card.stylesheets = [*card.stylesheets, DASHBOARD_METRIC_CSS]
    callback_apps = _table_panel("Callback latency by route · 5 min", name="monitor-callback-apps")
    event_loop_apps = _table_panel(
        "Event-loop lag by route · 5 min", name="monitor-event-loop-apps"
    )
    slowest_callbacks = _table_panel("Slowest callbacks · 5 min", name="monitor-slowest-callbacks")

    time_range = DataRange1d(
        follow="end", follow_interval=HISTORY_SECONDS * 1_000, range_padding=0.02
    )
    utilization = figure(
        title="CPU and memory · 5 min",
        height=265,
        sizing_mode="stretch_width",
        x_axis_type="datetime",
        x_range=time_range,
        y_range=Range1d(start=0, end=105),
        tools="xpan,xwheel_zoom,reset",
        active_scroll=None,
        name="monitor-utilization",
    )
    utilization.line("time", "cpu", source=source, color=CORAL, line_width=2.7, legend_label="CPU")
    utilization.line(
        "time", "memory", source=source, color=TEAL, line_width=2.7, legend_label="Memory"
    )
    utilization.yaxis.axis_label = "Allocated capacity (%)"
    utilization.legend.click_policy = "mute"
    style_figure(utilization)

    latency = figure(
        title="Latency p95 · 5 min",
        height=265,
        sizing_mode="stretch_width",
        x_axis_type="datetime",
        x_range=time_range,
        tools="xpan,xwheel_zoom,reset",
        active_scroll=None,
        name="monitor-latency",
    )
    latency.line(
        "time",
        "callback_p95",
        source=source,
        color=GOLD,
        line_width=2.7,
        legend_label="Callback duration",
    )
    latency.line(
        "time",
        "event_loop_p95",
        source=source,
        color=VIOLET,
        line_width=2.7,
        legend_label="Event-loop lag",
    )
    latency.yaxis.axis_label = "Milliseconds"
    latency.legend.click_policy = "mute"
    style_figure(latency)

    network = figure(
        title="Network traffic · 5 min",
        height=265,
        sizing_mode="stretch_width",
        x_axis_type="datetime",
        x_range=time_range,
        tools="xpan,xwheel_zoom,reset",
        active_scroll=None,
        name="monitor-network",
    )
    network.line(
        "time", "rx_kib", source=source, color=TEAL, line_width=2.4, legend_label="Received"
    )
    network.line("time", "tx_kib", source=source, color=CORAL, line_width=2.4, legend_label="Sent")
    network.yaxis.axis_label = "KiB / second"
    network.legend.click_policy = "mute"
    style_figure(network)
    for plot in (utilization, latency, network):
        plot.background_fill_color = "#fffdf9"
        plot.border_fill_color = "#fffdf9"
        plot.outline_line_color = "#d8d2cb"
        if isinstance(plot.title, Title):
            plot.title.text_font = "Arial"
            plot.title.text_font_size = "12px"
            plot.title.text_font_style = "bold"
        legend = plot.legend[0]
        plot.add_layout(legend, "below")
        legend.orientation = "horizontal"
        legend.location = "center_left"
        legend.margin = 0
        legend.spacing = 8
        legend.background_fill_alpha = 0
        legend.border_line_alpha = 0
        legend.label_text_font_size = "10px"
        plot.xaxis.formatter = DatetimeTickFormatter(
            microseconds="%H:%M:%S",
            milliseconds="%H:%M:%S",
            seconds="%H:%M:%S",
            minsec="%H:%M:%S",
            minutes="%H:%M",
            hourmin="%H:%M",
            hours="%H:%M",
            days="%H:%M",
            hide_repeats=True,
        )
        plot.axis.major_label_text_font_size = "9px"
        plot.axis.axis_label_text_font_size = "10px"

    state: dict[str, int | None] = {"service_generation": None}

    def refresh() -> None:
        service_sample = service_monitor.sample()
        if service_sample.generation == state["service_generation"]:
            return
        state["service_generation"] = service_sample.generation
        source.stream(cast(Any, _stream_values(service_sample)), rollover=HISTORY_POINTS)
        _update_service_cards(
            service_sample, tasks_card, service_sessions_card, service_pages_card, service_lag_card
        )
        _update_timing_tables(service_sample, callback_apps, event_loop_apps, slowest_callbacks)

    refresh()
    document.add_periodic_callback(refresh, REFRESH_INTERVAL_MS)

    dashboard = column(
        metric_row(
            tasks_card,
            service_sessions_card,
            service_pages_card,
            service_lag_card,
            sizing_mode="stretch_width",
        ),
        responsive_row(utilization, latency, network, sizing_mode="stretch_width"),
        responsive_row(callback_apps, event_loop_apps, sizing_mode="stretch_width"),
        slowest_callbacks,
        sizing_mode="stretch_width",
        spacing=9,
        styles={
            "background": "#f1efec",
            "border": "1px solid #d8d2cb",
            "box-sizing": "border-box",
            "padding": "10px",
        },
    )
    document.add_root(dashboard)
    prepare_document(document, ROUTE, measure_performance=False)


def _stream_values(sample: ServiceSample) -> dict[str, np.ndarray]:
    def value(number: float | None) -> np.ndarray:
        return np.asarray([np.nan if number is None else number], dtype=np.float32)

    return {
        "time": np.asarray([sample.timestamp_ms], dtype=np.float64),
        "cpu": value(sample.cpu_percent),
        "memory": value(sample.memory_percent),
        "callback_p95": value(sample.callback_p95_ms),
        "event_loop_p95": value(sample.event_loop_p95_ms),
        "rx_kib": value(
            None if sample.rx_bytes_per_second is None else sample.rx_bytes_per_second / 1024
        ),
        "tx_kib": value(
            None if sample.tx_bytes_per_second is None else sample.tx_bytes_per_second / 1024
        ),
    }


def _update_service_cards(sample: ServiceSample, tasks, sessions, pages, lag) -> None:
    set_metric(tasks, str(sample.reporting_tasks), label="Running containers")
    set_metric(sessions, str(sample.active_sessions), label="Current viewers")
    set_metric(pages, f"{sample.page_entries_per_minute:.0f} / min", label="Page views")
    set_metric(lag, _milliseconds(sample.event_loop_p95_ms), label="Event-loop lag p95")


def _table_panel(title: str, *, name: str) -> Div:
    return Div(
        text=_empty_table(title),
        name=name,
        sizing_mode="stretch_width",
        styles={
            "background": "#fffdf9",
            "border": "1px solid #ded7ce",
            "box-sizing": "border-box",
            "min-height": "190px",
            "padding": "16px 18px",
        },
    )


def _update_timing_tables(
    sample: ServiceSample, callback_apps: Div, event_loop_apps: Div, slowest_callbacks: Div
) -> None:
    callback_apps.text = _app_table(
        "Callback latency by route · 5 min", sample.callbacks_by_app, count_label="callbacks"
    )
    event_loop_apps.text = _app_table(
        "Event-loop lag by route · 5 min", sample.event_loop_by_app, count_label="observations"
    )
    slowest_callbacks.text = _callback_table(
        sample.slowest_callbacks, title="Slowest callbacks · 5 min"
    )


def _app_table(title: str, timings: tuple[AppTiming, ...], *, count_label: str) -> str:
    if not timings:
        return _empty_table(title)
    rows = "".join(
        _table_row(
            escape(timing.app), str(timing.count), f"{timing.p95_ms:.2f}", f"{timing.max_ms:.2f}"
        )
        for timing in timings
    )
    return _table(
        title, ("route", count_label, "p95 ms", "max ms"), rows, widths=("52%", "16%", "16%", "16%")
    )


def _callback_table(
    timings: tuple[CallbackTiming, ...], *, title: str = "Slowest callbacks"
) -> str:
    if not timings:
        return _empty_table(title)
    rows = "".join(
        _table_row(
            escape(timing.app),
            escape(timing.callback),
            str(timing.count),
            f"{timing.p95_ms:.2f}",
            f"{timing.max_ms:.2f}",
        )
        for timing in timings
    )
    return _table(
        title,
        ("route", "callback", "calls", "p95 ms", "max ms"),
        rows,
        widths=("29%", "29%", "14%", "14%", "14%"),
    )


def _empty_table(title: str) -> str:
    return (
        f"<h3 style='color:{PLUM};font:600 15px Arial,sans-serif;margin:0 0 12px'>{title}</h3>"
        f"<p style='color:{MUTED};font-size:12px;margin:0'>No activity during the "
        "rolling window.</p>"
    )


def _table(title: str, headings: tuple[str, ...], rows: str, *, widths: tuple[str, ...]) -> str:
    columns = "".join(f"<col style='width:{width}'>" for width in widths)
    header = "".join(f"<th style='{_TH_STYLE}'>{escape(heading)}</th>" for heading in headings)
    return (
        f"<h3 style='color:{PLUM};font:600 15px Arial,sans-serif;margin:0 0 12px'>{title}</h3>"
        f"<table style='border-collapse:collapse;table-layout:fixed;width:100%;font-size:12px'>"
        f"<colgroup>{columns}</colgroup><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>"
    )


_TH_STYLE = (
    f"border-bottom:1px solid #cfc6bc;color:{MUTED};font:700 10px monospace;"
    "letter-spacing:.05em;padding:0 7px 7px;text-align:left;text-transform:uppercase"
)
_TD_STYLE = (
    f"border-bottom:1px solid #eee8e0;color:{PLUM};font-family:monospace;"
    "overflow-wrap:anywhere;padding:7px;text-align:left;vertical-align:top"
)


def _table_row(*values: str) -> str:
    return "<tr>" + "".join(f"<td style='{_TD_STYLE}'>{value}</td>" for value in values) + "</tr>"


def _milliseconds(value: float | None) -> str:
    return "Quiet" if value is None else f"{value:.1f} ms"
