"""Show a privacy-bounded view of the server currently serving this session."""

from __future__ import annotations

from html import escape
from typing import Any, cast

import numpy as np
from bokeh.layouts import column
from bokeh.models import ColumnDataSource, DataRange1d, Div, Range1d
from bokeh.plotting import figure

from apps._common import (
    metric,
    metric_row,
    prepare_document,
    responsive_row,
    set_metric,
    style_figure,
)
from apps._common.colors import CORAL, GOLD, MUTED, PLUM, TEAL, VIOLET, WARM
from apps._common.performance import AppTiming, CallbackTiming

from .metrics import CoalescedSampler, MonitorSample, create_adapter

ROUTE = "/monitor"
HISTORY_POINTS = 90
SAMPLER = CoalescedSampler(create_adapter())


def modify_document(document) -> None:
    """Build the public monitor using the process-wide coalesced sampler."""
    build_document(document, SAMPLER)


def build_document(document, sampler: CoalescedSampler) -> None:
    """Build a monitor document around an injectable sampler for tests."""
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
    status = Div(
        name="monitor-source",
        sizing_mode="stretch_width",
        stylesheets=[".bk-clearfix { display: block; width: 100%; }"],
    )
    cpu_card = metric("CPU", "Sampling…", accent=CORAL)
    memory_card = metric("Memory", "Sampling…", accent=TEAL)
    callbacks_card = metric("Python callbacks", "Sampling…", accent=GOLD)
    lag_card = metric("Event-loop lag", "Sampling…", accent=VIOLET)
    callback_apps = _table_panel("Callback latency by app", name="monitor-callback-apps")
    event_loop_apps = _table_panel("Event-loop lag by app", name="monitor-event-loop-apps")
    slowest_callbacks = _table_panel("Slowest callbacks", name="monitor-slowest-callbacks")

    time_range = DataRange1d(follow="end", follow_interval=120_000, range_padding=0.02)
    utilization = figure(
        title="CPU and memory · last two minutes",
        height=300,
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
    utilization.legend.location = "top_left"
    utilization.legend.orientation = "horizontal"
    utilization.legend.click_policy = "mute"
    style_figure(utilization)

    latency = figure(
        title="Callback and event-loop latency · rolling p95",
        height=300,
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
    latency.legend.location = "top_left"
    latency.legend.orientation = "horizontal"
    latency.legend.click_policy = "mute"
    style_figure(latency)

    network = figure(
        title="Network traffic · this task or local container",
        height=225,
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
    network.legend.location = "top_left"
    network.legend.orientation = "horizontal"
    network.legend.click_policy = "mute"
    style_figure(network)

    state: dict[str, Any] = {"generation": None, "source_label": None}

    def refresh() -> None:
        sample = sampler.sample()
        if sample.generation == state["generation"]:
            return
        state["generation"] = sample.generation
        source.stream(cast(Any, _stream_values(sample)), rollover=HISTORY_POINTS)
        _update_cards(sample, cpu_card, memory_card, callbacks_card, lag_card)
        _update_timing_tables(sample, callback_apps, event_loop_apps, slowest_callbacks)
        if sample.source_label != state["source_label"]:
            status.text = _source_status(sample)
            state["source_label"] = sample.source_label

    refresh()
    document.add_periodic_callback(refresh, 2_000)

    explanation = Div(
        text=(
            "<h2>What this page measures</h2>"
            "<p>In production, CPU, memory, and network describe the ECS task handling this session. "
            "Callback timing and event-loop lag come from that task's Python process. This is not a "
            "service-wide view, so another visitor may see a different server.</p>"
        ),
        styles={
            "background": WARM,
            "border": "1px solid #ded7ce",
            "color": MUTED,
            "line-height": "1.65",
            "padding": "18px 20px",
        },
        sizing_mode="stretch_width",
    )
    privacy = Div(
        text=(
            "<p><strong>What reaches your browser.</strong> Your browser receives only the numbers and labels "
            "shown on this page. App routes come from the public gallery, and callback names come from a "
            "fixed list in the source code. The page does not send task metadata, AWS identifiers, "
            "credentials, logs, IP addresses, request headers, referrers, or query strings. The server reads "
            "ECS stats at most once every two seconds and shares each reading among the monitor sessions on "
            "that process.</p>"
        ),
        styles={
            "border-left": f"3px solid {GOLD}",
            "color": MUTED,
            "font-size": "12px",
            "line-height": "1.65",
            "padding": "8px 16px",
        },
        sizing_mode="stretch_width",
    )

    document.add_root(
        column(
            status,
            metric_row(
                cpu_card, memory_card, callbacks_card, lag_card, sizing_mode="stretch_width"
            ),
            explanation,
            responsive_row(utilization, latency, sizing_mode="stretch_width"),
            Div(
                text=(
                    "<h2 style='margin:8px 0 2px'>Where Python time is going</h2>"
                    "<p style='margin:0'>These tables summarize the past 60 seconds of work handled by this "
                    "Python process. App routes and callback names come from a fixed public list.</p>"
                ),
                styles={"color": MUTED, "line-height": "1.55"},
                sizing_mode="stretch_width",
            ),
            responsive_row(callback_apps, event_loop_apps, sizing_mode="stretch_width"),
            slowest_callbacks,
            network,
            privacy,
            sizing_mode="stretch_width",
            spacing=16,
        )
    )
    prepare_document(document, ROUTE, measure_performance=False)


def _stream_values(sample: MonitorSample) -> dict[str, np.ndarray]:
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


def _update_cards(sample: MonitorSample, cpu, memory, callbacks, lag) -> None:
    if sample.scope == "task":
        cpu_label = "Current task CPU"
        memory_label = "Current task memory"
    elif sample.scope == "process":
        cpu_label = "Current process CPU"
        memory_label = "Process resident memory"
    else:
        cpu_label = "Simulated CPU"
        memory_label = "Simulated memory"
    set_metric(cpu, _percent(sample.cpu_percent), label=cpu_label)
    if sample.memory_percent is not None:
        memory_value = f"{sample.memory_percent:.1f}% · {_mib(sample.memory_bytes)}"
    else:
        memory_value = _mib(sample.memory_bytes)
    set_metric(memory, memory_value, label=memory_label)
    set_metric(callbacks, f"{sample.callback_rate:.1f} / s", label="Current process callbacks")
    set_metric(lag, _milliseconds(sample.event_loop_p95_ms), label="Current process loop-lag p95")


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
    sample: MonitorSample, callback_apps: Div, event_loop_apps: Div, slowest_callbacks: Div
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
        f"<h3 style='color:{PLUM};font:600 18px Georgia,serif;margin:0 0 12px'>{title}</h3>"
        f"<p style='color:{MUTED};font-size:12px;margin:0'>No activity in this process during the "
        "rolling window.</p>"
    )


def _table(title: str, headings: tuple[str, ...], rows: str, *, widths: tuple[str, ...]) -> str:
    columns = "".join(f"<col style='width:{width}'>" for width in widths)
    header = "".join(f"<th style='{_TH_STYLE}'>{escape(heading)}</th>" for heading in headings)
    return (
        f"<h3 style='color:{PLUM};font:600 18px Georgia,serif;margin:0 0 12px'>{title}</h3>"
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


def _source_status(sample: MonitorSample) -> str:
    if sample.deterministic:
        eyebrow = "SIMULATED DATA"
        detail = "These repeatable values are for trying the page locally. They do not describe this server."
    elif sample.scope == "task":
        eyebrow = "LIVE DATA · THIS ECS TASK"
        detail = (
            "CPU, memory, and network cover this task. Callback timing covers its Python process."
        )
    else:
        eyebrow = "LIVE DATA · THIS PYTHON PROCESS"
        detail = "CPU and memory come from this process. Network appears when the local container exposes it."
    return (
        f'<div style="width:100%;box-sizing:border-box;background:{PLUM};color:#f7f3ec;padding:18px 20px;'
        f'border-left:5px solid {CORAL}">'
        f'<div style="color:{GOLD};font:700 10px monospace;letter-spacing:.12em">{eyebrow}</div>'
        f'<div style="font:400 25px Georgia,serif;margin-top:5px">{sample.source_label}</div>'
        f'<div style="color:rgba(247,243,236,.7);font-size:12px;margin-top:6px">{detail}</div></div>'
    )


def _percent(value: float | None) -> str:
    return "Warming up" if value is None else f"{value:.1f}%"


def _mib(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value / (1024 * 1024):.0f} MiB"


def _milliseconds(value: float | None) -> str:
    return "Quiet" if value is None else f"{value:.1f} ms"
