"""Test the oscillator demo."""

from __future__ import annotations

import numpy as np
from bokeh.document import Document
from bokeh.models import (
    BasicTicker,
    Button,
    ColumnDataSource,
    CustomJSTickFormatter,
    Div,
    Slider,
    Tabs,
    Toggle,
)

from catalog import load_applications


def test_oscillator_phase_plots_share_the_light_preview_treatment() -> None:
    document = Document()
    load_applications()["/chaotic-motion"](document)
    names = (
        (
            "chaotic-phase-plot",
            "chaotic-phase-path",
            "duffing-phase-history",
            "duffing-diagnostic-plot",
            "duffing-diagnostic-samples",
        ),
        (
            "van-der-pol-phase-plot",
            "van-der-pol-phase-path",
            "van-der-pol-phase-history",
            "van-der-pol-diagnostic-plot",
            "van-der-pol-diagnostic-samples",
        ),
        (
            "pendulum-phase-plot",
            "pendulum-phase-path",
            "pendulum-phase-history",
            "pendulum-diagnostic-plot",
            "pendulum-diagnostic-samples",
        ),
        (
            "mathieu-phase-plot",
            "mathieu-phase-path",
            "mathieu-phase-history",
            "mathieu-diagnostic-plot",
            "mathieu-diagnostic-samples",
        ),
    )
    for phase_name, path_name, history_name, diagnostic_name, samples_name in names:
        phase = document.select_one({"name": phase_name})
        path = document.select_one({"name": path_name})
        history = document.select_one({"name": history_name})
        diagnostic = document.select_one({"name": diagnostic_name})
        samples = document.select_one({"name": samples_name})
        assert phase.title.text == "Phase path"
        assert diagnostic.title.text in {"Peak convergence", "Stroboscopic section"}
        assert phase.tools == []
        assert diagnostic.tools == []
        assert phase.background_fill_color == "#e5ddd4"
        assert diagnostic.background_fill_color == phase.background_fill_color
        assert phase.grid[0].grid_line_color == "#2a1723"
        assert diagnostic.grid[0].grid_line_color == "#2a1723"
        assert diagnostic.grid[0].grid_line_width == 0.5
        assert diagnostic.grid[0].grid_line_alpha <= 0.12
        assert path.glyph.line_width <= 0.8
        assert path.glyph.line_alpha <= 0.55
        assert history.glyph.line_alpha < path.glyph.line_alpha
        assert samples.glyph.fill_color == samples.glyph.line_color
        assert samples.glyph.fill_color != "#fffdf9"
        assert samples.glyph.fill_alpha == 0.78
    for key in ("duffing", "van-der-pol", "pendulum", "mathieu"):
        explanation = document.select_one({"type": Div, "name": f"{key}-explanation"})
        assert "margin-bottom:18px" in explanation.text
    pendulum = document.select_one({"name": "pendulum-phase-plot"})
    assert pendulum.xaxis[0].axis_label == r"$$\theta$$"
    assert isinstance(pendulum.xaxis[0].ticker, BasicTicker)
    assert pendulum.xaxis[0].ticker.min_interval == 1
    assert isinstance(pendulum.xaxis[0].formatter, CustomJSTickFormatter)
    assert "π" in pendulum.xaxis[0].formatter.code
    pendulum_diagnostic = document.select_one({"name": "pendulum-diagnostic-plot"})
    assert pendulum_diagnostic.xaxis[0].ticker is pendulum.xaxis[0].ticker
    assert pendulum_diagnostic.xaxis[0].formatter is pendulum.xaxis[0].formatter
    peak_convergence = document.select_one({"name": "van-der-pol-diagnostic-plot"})
    assert peak_convergence.min_border_left == 65


def test_oscillator_phase_range_expands_to_contain_the_orbit() -> None:
    document = Document()
    load_applications()["/chaotic-motion"](document)
    tabs = document.select_one({"type": Tabs, "name": "oscillator-tabs"})
    tabs.active = 1
    nonlinearity = next(
        slider
        for slider in tabs.tabs[1].child.select({"type": Slider})
        if "nonlinearity" in slider.title
    )
    nonlinearity.value = nonlinearity.end
    for _ in range(50):
        min(document.session_callbacks, key=lambda callback: callback.period).callback()

    phase = document.select_one({"name": "van-der-pol-phase-plot"})
    source = document.select_one({"type": ColumnDataSource, "name": "van-der-pol-phase"})
    assert phase.x_range.start < min(source.data["x"])
    assert phase.x_range.end > max(source.data["x"])
    assert phase.y_range.start < min(source.data["velocity"])
    assert phase.y_range.end > max(source.data["velocity"])


def test_pendulum_ticks_remain_readable_across_multiple_rotations() -> None:
    document = Document()
    load_applications()["/chaotic-motion"](document)
    tabs = document.select_one({"type": Tabs, "name": "oscillator-tabs"})
    tabs.active = 2
    damping = next(
        slider
        for slider in tabs.tabs[2].child.select({"type": Slider})
        if "damping" in slider.title
    )
    damping.value = damping.start
    for _ in range(40):
        min(document.session_callbacks, key=lambda callback: callback.period).callback()

    phase = document.select_one({"name": "pendulum-phase-plot"})
    phase_source = document.select_one({"name": "pendulum-phase"})
    trace_source = document.select_one({"name": "pendulum-trace"})
    diagnostic = document.select_one({"name": "pendulum-diagnostic-plot"})
    assert np.isclose(phase_source.data["x"][-1], trace_source.data["x"][-1] / np.pi)
    assert max(abs(np.asarray(phase_source.data["x"]))) > 8
    assert phase.x_range.start < min(phase_source.data["x"])
    assert phase.x_range.end > max(phase_source.data["x"])
    assert diagnostic.xaxis[0].ticker is phase.xaxis[0].ticker


def test_mathieu_oscillator_streams_a_finite_stroboscopic_section() -> None:
    document = Document()
    load_applications()["/chaotic-motion"](document)
    tabs = document.select_one({"type": Tabs, "name": "oscillator-tabs"})
    tabs.active = 3
    for _ in range(20):
        min(document.session_callbacks, key=lambda callback: callback.period).callback()

    phase = document.select_one({"type": ColumnDataSource, "name": "mathieu-phase"})
    diagnostic = document.select_one({"type": ColumnDataSource, "name": "mathieu-diagnostic"})
    trace = document.select_one({"type": ColumnDataSource, "name": "mathieu-trace"})
    assert np.isfinite(phase.data["x"]).all()
    assert np.isfinite(phase.data["velocity"]).all()
    assert len(diagnostic.data["x"]) >= 6
    assert trace.data["cycles"][-1] > 0
    assert len(trace.data["cycles"]) == len(trace.data["time"])


def test_oscillator_tabs_own_their_controls_and_only_advance_when_active() -> None:
    document = Document()
    load_applications()["/chaotic-motion"](document)
    tabs = document.select_one({"type": Tabs, "name": "oscillator-tabs"})
    assert [panel.title for panel in tabs.tabs] == [
        "Duffing",
        "Van der Pol",
        "Driven pendulum",
        "Mathieu",
    ]
    for panel in tabs.tabs:
        assert len(list(panel.child.select({"type": Slider}))) >= 1
        assert len(list(panel.child.select({"type": Toggle}))) == 1
        assert any(
            button.label == "Reset initial state" for button in panel.child.select({"type": Button})
        )

    traces = {
        source.name: source
        for source in document.select({"type": ColumnDataSource})
        if source.name and source.name.endswith("-trace")
    }
    lengths = {name: len(source.data["time"]) for name, source in traces.items()}
    tabs.active = 1
    min(document.session_callbacks, key=lambda callback: callback.period).callback()
    assert len(traces["duffing-trace"].data["time"]) == lengths["duffing-trace"]
    assert len(traces["van-der-pol-trace"].data["time"]) > lengths["van-der-pol-trace"]
    assert len(traces["pendulum-trace"].data["time"]) == lengths["pendulum-trace"]
    assert len(traces["mathieu-trace"].data["time"]) == lengths["mathieu-trace"]
    for key in ("duffing", "pendulum", "mathieu"):
        trace_plot = document.select_one({"name": f"{key}-trace-plot"})
        assert trace_plot.xaxis[0].axis_label == r"$$t/T$$"
    van_der_pol_trace = document.select_one({"name": "van-der-pol-trace-plot"})
    assert van_der_pol_trace.xaxis[0].axis_label == r"$$t$$"
    assert not any("MathText is used" in div.text for div in document.select({"type": Div}))
