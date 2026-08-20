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
from apps._common.performance import PUBLIC_WINDOW_SECONDS, AppTiming, CallbackTiming

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
    service_status = Div(
        name="monitor-service-source",
        sizing_mode="stretch_width",
        stylesheets=[".bk-clearfix { display: block; width: 100%; }"],
    )
    tasks_card = metric("Reporting tasks", "Warming up", accent=GOLD)
    service_sessions_card = metric("Open sessions", "Warming up", accent=TEAL)
    service_pages_card = metric("Page entries", "Warming up", accent=CORAL)
    service_cpu_card = metric("CPU usage", "Warming up", accent=CORAL)
    service_memory_card = metric("Memory usage", "Warming up", accent=TEAL)
    service_network_card = metric("Network traffic", "Warming up", accent=VIOLET)
    service_lag_card = metric("Event-loop lag", "Warming up", accent=VIOLET)
    for card in (
        tasks_card,
        service_sessions_card,
        service_pages_card,
        service_cpu_card,
        service_memory_card,
        service_network_card,
        service_lag_card,
    ):
        card.stylesheets = [*card.stylesheets, DASHBOARD_METRIC_CSS]
    callback_apps = _table_panel("Callback latency by app", name="monitor-callback-apps")
    event_loop_apps = _table_panel("Event-loop lag by app", name="monitor-event-loop-apps")
    slowest_callbacks = _table_panel("Slowest callbacks", name="monitor-slowest-callbacks")

    time_range = DataRange1d(
        follow="end", follow_interval=HISTORY_SECONDS * 1_000, range_padding=0.02
    )
    utilization = figure(
        title="CPU and memory usage · five minutes",
        height=265,
        sizing_mode="stretch_width",
        x_axis_type="datetime",
        x_range=time_range,
        y_range=Range1d(start=0, end=105),
        tools="xpan,xwheel_zoom,reset",
        active_scroll=None,
        name="monitor-utilization",
    )
    utilization.varea(x="time", y1=0, y2="cpu", source=source, fill_color=CORAL, fill_alpha=0.10)
    utilization.line("time", "cpu", source=source, color=CORAL, line_width=2.7, legend_label="CPU")
    utilization.line(
        "time", "memory", source=source, color=TEAL, line_width=2.7, legend_label="Memory"
    )
    utilization.yaxis.axis_label = "Capacity used (%)"
    utilization.legend.click_policy = "mute"
    style_figure(utilization)

    latency = figure(
        title="Callback and event-loop p95 · five minutes",
        height=265,
        sizing_mode="stretch_width",
        x_axis_type="datetime",
        x_range=time_range,
        tools="xpan,xwheel_zoom,reset",
        active_scroll=None,
        name="monitor-latency",
    )
    latency.varea(
        x="time", y1=0, y2="event_loop_p95", source=source, fill_color=VIOLET, fill_alpha=0.12
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
        title="Network traffic · five minutes",
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
        service_status.text = _service_status(service_sample)
        _update_service_cards(
            service_sample,
            tasks_card,
            service_sessions_card,
            service_pages_card,
            service_cpu_card,
            service_memory_card,
            service_network_card,
            service_lag_card,
        )
        _update_timing_tables(service_sample, callback_apps, event_loop_apps, slowest_callbacks)

    refresh()
    document.add_periodic_callback(refresh, REFRESH_INTERVAL_MS)

    dashboard_heading = Div(
        text=(
            "<div style='display:flex;align-items:center;justify-content:space-between;gap:16px;"
            "flex-wrap:wrap'>"
            "<div><h2 style='font:600 18px Arial,sans-serif;margin:0'>Dashboard</h2>"
            "<p style='margin:3px 0 0'>Every value combines all reporting tasks.</p></div>"
            "<div style='font:600 11px monospace;letter-spacing:.04em;white-space:nowrap'>"
            "REPORTS 30 S&nbsp;&nbsp;·&nbsp;&nbsp;WINDOW 5 MIN</div></div>"
        ),
        styles={
            "background": PLUM,
            "border-left": f"5px solid {GOLD}",
            "box-sizing": "border-box",
            "color": "#f7f3ec",
            "line-height": "1.45",
            "padding": "13px 16px",
        },
        sizing_mode="stretch_width",
    )
    dashboard = column(
        dashboard_heading,
        service_status,
        metric_row(
            tasks_card, service_sessions_card, service_pages_card, sizing_mode="stretch_width"
        ),
        metric_row(
            service_cpu_card,
            service_memory_card,
            service_network_card,
            service_lag_card,
            sizing_mode="stretch_width",
        ),
        responsive_row(utilization, latency, network, sizing_mode="stretch_width"),
        Div(
            text=(
                f"<p style='margin:8px 0 0'>The tables below combine the past "
                f"{PUBLIC_WINDOW_SECONDS / 60:.0f} minutes across all reporting tasks. "
                "Percentiles come from merged fixed buckets, so they are approximate.</p>"
            ),
            styles={"color": MUTED, "line-height": "1.55"},
            sizing_mode="stretch_width",
        ),
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


def _update_service_cards(
    sample: ServiceSample, tasks, sessions, pages, cpu, memory, network, lag
) -> None:
    set_metric(tasks, str(sample.reporting_tasks), label="Reporting tasks")
    set_metric(sessions, str(sample.active_sessions), label="Open sessions")
    set_metric(pages, f"{sample.page_entries_per_minute:.0f} / min", label="Page entries")
    cpu_value = "Unavailable"
    if sample.cpu_vcpus is not None:
        cpu_value = f"{sample.cpu_vcpus:.2f} vCPU"
        if sample.cpu_percent is not None:
            cpu_value += f" · {sample.cpu_percent:.1f}%"
    set_metric(cpu, cpu_value, label="CPU usage")
    memory_value = _mib(sample.memory_bytes)
    if sample.memory_percent is not None:
        memory_value += f" · {sample.memory_percent:.1f}%"
    set_metric(memory, memory_value, label="Memory usage")
    if sample.rx_bytes_per_second is None or sample.tx_bytes_per_second is None:
        network_value = "Warming up"
    else:
        network_value = (
            f"↓ {sample.rx_bytes_per_second / 1024:.0f} · "
            f"↑ {sample.tx_bytes_per_second / 1024:.0f} KiB/s"
        )
    set_metric(network, network_value, label="Network traffic")
    set_metric(lag, _milliseconds(sample.event_loop_p95_ms), label="Event-loop lag p95")


def _service_status(sample: ServiceSample) -> str:
    source_label = sample.source_label
    if sample.status == "simulated":
        eyebrow = "SIMULATED SERVICE"
        detail = "Three repeatable task reports for layout and interaction checks."
    elif sample.source_label == "Local process registry":
        eyebrow = "WHOLE DEVELOPMENT SERVICE"
        source_label = "Development service aggregate"
        detail = "Combined from every reporting process in this development run."
    elif sample.status == "degraded":
        eyebrow = "SERVICE VIEW DEGRADED"
        reasons = {
            "warming_up": "The first service report has not arrived yet.",
            "no_fresh_heartbeats": "No task has reported in the last 75 seconds.",
            "service_data_unavailable": "The sanitized service exchange is temporarily unavailable.",
        }
        detail = reasons.get(
            sample.reason or "", "The service aggregate is temporarily unavailable."
        )
    else:
        eyebrow = "LIVE DATA · WHOLE DEMO SERVICE"
        detail = (
            f"{sample.reporting_tasks} task{'s' if sample.reporting_tasks != 1 else ''} reported "
            "within the last 75 seconds; updated every 30 seconds."
        )
    return _status_strip(eyebrow, source_label, detail, GOLD)


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
        "Callback latency by app", sample.callbacks_by_app, count_label="callbacks"
    )
    event_loop_apps.text = _app_table(
        "Event-loop lag by app", sample.event_loop_by_app, count_label="observations"
    )
    slowest_callbacks.text = _callback_table(sample.slowest_callbacks)


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
        title, ("app", count_label, "p95 ms", "max ms"), rows, widths=("52%", "16%", "16%", "16%")
    )


def _callback_table(timings: tuple[CallbackTiming, ...]) -> str:
    title = "Slowest callbacks"
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
        ("app", "callback", "calls", "p95 ms", "max ms"),
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


def _status_strip(eyebrow: str, source_label: str, detail: str, accent: str) -> str:
    return (
        f'<div style="align-items:center;background:#fffdf9;border:1px solid #d8d2cb;'
        f"border-left:4px solid {accent};box-sizing:border-box;display:flex;gap:10px 16px;"
        f'padding:10px 13px;width:100%;flex-wrap:wrap">'
        f'<div style="color:{accent};font:700 10px monospace;letter-spacing:.08em">'
        f"{escape(eyebrow)}</div>"
        f'<div style="color:{PLUM};font:600 13px Arial,sans-serif">{escape(source_label)}</div>'
        f'<div style="color:{MUTED};font-size:12px;min-width:240px;flex:1">'
        f"{escape(detail)}</div></div>"
    )


def _mib(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value / (1024 * 1024):.0f} MiB"


def _milliseconds(value: float | None) -> str:
    return "Quiet" if value is None else f"{value:.1f} ms"
