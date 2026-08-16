"""Construct the structured example's Bokeh models and page layout."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from bokeh.layouts import column
from bokeh.models import (
    BasicTicker,
    BoxAnnotation,
    Button,
    ColorBar,
    ColumnDataSource,
    CustomJS,
    Div,
    HoverTool,
    LinearColorMapper,
    Plot,
    Range1d,
    Select,
    Slider,
    Span,
    Title,
    Toggle,
)
from bokeh.models.layouts import Column, Row
from bokeh.palettes import Inferno256
from bokeh.plotting import figure

from apps._common import load_javascript, match_background, responsive_row, style_figure, wrap_row
from apps._common.colors import CORAL, GOLD, GRID, PLUM, WARM
from apps.spectrum.simulation import (
    BLOCK_SIZE,
    NYQUIST,
    SAMPLE_RATE,
    SEED,
    SPECTRUM_CEILING,
    SPECTRUM_FLOOR,
)

HISTORY_ROWS = 84
HISTORY_SECONDS = 18.0
UPDATE_TICKS = {"Measured": 4, "Live": 2, "Fast": 1}
FILTERS = (
    "No filter",
    "Low-pass",
    "High-pass",
    "Band-pass",
    "Wide band-stop",
    "Dual band-pass",
    "Adaptive notch",
    "Peaking",
    "Elliptic band-pass",
    "Notch",
    "Comb reject",
)
SCENES = {
    "Telemetry link": "A narrow carrier with nearby sidebands and slow frequency modulation.",
    "Radar sweep": "A chirped transmitter repeatedly crosses the observed band.",
    "Frequency hopping": "A transmitter jumps among six channels on a fixed schedule.",
    "Crowded band": "Several persistent emitters share the band with short broadband bursts.",
    "Satellite Doppler pass": "A fading carrier curves across the band as its modeled radial velocity changes.",
    "Drifting interferer": "A strong moving tone crosses a weaker fixed telemetry carrier.",
    "Intermodulation products": "Two strong carriers drive a nonlinear stage and produce predictable mixing products.",
    "Packet radio traffic": "Short transmissions occupy several channels with irregular gaps between packets.",
    "Spread-spectrum link": "A rapidly coded carrier spreads its energy across a broad, noise-like band.",
}
DARK_GRID = "#604c59"
CHALK = "#f4ede5"

type FilterGuide = tuple[BoxAnnotation, Span]


@dataclass(slots=True)
class Controls:
    scene: Select
    filter_mode: Select
    center_frequency: Slider
    second_frequency: Slider
    bandwidth: Slider
    boost_gain: Slider
    noise: Slider
    update_rate: Select
    playing: Toggle
    inject_transient: Button
    restart: Button
    primary: Row
    specialized: Row
    watch_note: Div


@dataclass(slots=True)
class Sources:
    history: ColumnDataSource
    latest: ColumnDataSource
    power: ColumnDataSource
    response: ColumnDataSource
    empty_history: np.ndarray


@dataclass(slots=True)
class Plots:
    spectrum: Plot
    response: Plot
    spectrogram: Plot
    response_range: Range1d
    filter_guides: list[FilterGuide]
    second_filter_guides: list[FilterGuide]


@dataclass(slots=True)
class SpectrumView:
    controls: Controls
    sources: Sources
    plots: Plots
    status: Div
    root: Column


def build_controls() -> Controls:
    scene = Select(title="Signal scene", value="Telemetry link", options=list(SCENES), width=190)
    filter_mode = Select(
        title="Receiver filter", value="Band-pass", options=list(FILTERS), width=160
    )
    center_frequency = Slider(
        title="Center frequency (Hz)",
        start=50,
        end=1150,
        value=420,
        step=5,
        sizing_mode="stretch_width",
        name="spectrum-center-frequency",
    )
    second_frequency = Slider(
        title="Second center frequency (Hz)",
        start=50,
        end=1150,
        value=780,
        step=5,
        sizing_mode="stretch_width",
        visible=False,
        name="spectrum-second-frequency",
    )
    bandwidth = Slider(
        title="Filter bandwidth (Hz)",
        start=25,
        end=500,
        value=100,
        step=5,
        max_width=420,
        sizing_mode="stretch_width",
        name="spectrum-bandwidth",
    )
    boost_gain = Slider(
        title="Boost gain (dB)",
        start=3,
        end=18,
        value=12,
        step=1,
        max_width=420,
        sizing_mode="stretch_width",
        visible=False,
        name="spectrum-boost-gain",
    )
    noise = Slider(
        title="Noise amplitude",
        start=0.02,
        end=0.9,
        value=0.22,
        step=0.02,
        max_width=420,
        sizing_mode="stretch_width",
        name="spectrum-noise",
    )
    update_rate = Select(title="Update rate", value="Fast", options=list(UPDATE_TICKS), width=120)
    playing = Toggle(label="Pause", active=True, button_type="primary")
    inject_transient = Button(label="Inject transient")
    restart = Button(label="Restart")
    primary = responsive_row(
        scene,
        filter_mode,
        update_rate,
        center_frequency,
        bandwidth,
        sizing_mode="stretch_width",
        name="spectrum-primary-controls",
    )
    specialized = wrap_row(
        boost_gain,
        noise,
        playing,
        inject_transient,
        restart,
        sizing_mode="stretch_width",
        name="spectrum-specialized-controls",
    )
    watch_note = Div(
        name="spectrum-watch-note",
        styles={"border-top": f"1px solid {GRID}", "padding-top": "10px", "margin-top": "2px"},
    )
    return Controls(
        scene,
        filter_mode,
        center_frequency,
        second_frequency,
        bandwidth,
        boost_gain,
        noise,
        update_rate,
        playing,
        inject_transient,
        restart,
        primary,
        specialized,
        watch_note,
    )


def build_sources() -> Sources:
    frequency_axis = np.fft.rfftfreq(BLOCK_SIZE, 1 / SAMPLE_RATE)
    empty_history = np.full((HISTORY_ROWS, len(frequency_axis)), SPECTRUM_FLOOR, dtype=np.float32)
    history = ColumnDataSource(
        data={
            "image": [empty_history],
            "x": [0.0],
            "y": [-HISTORY_SECONDS],
            "dw": [NYQUIST],
            "dh": [HISTORY_SECONDS],
        },
        name="spectrum-history",
    )
    latest = ColumnDataSource(
        data={"image": [empty_history[-1][np.newaxis, :].copy()]}, name="spectrum-latest-row"
    )
    # Send one row per update; BokehJS shifts it into the existing waterfall buffer.
    latest.js_on_change(
        "data",
        CustomJS(args={"history": history}, code=load_javascript(__file__, "shift_history.js")),
    )
    # Keep the unrendered row source in the document graph through the rendered source.
    history.js_on_change("data", CustomJS(args={"latest": latest}, code="void latest"))
    power = ColumnDataSource(
        data={"frequency": [], "raw": [], "filtered": []}, name="spectrum-power"
    )
    response = ColumnDataSource(data={"frequency": [], "gain": []}, name="spectrum-filter-response")
    return Sources(history, latest, power, response, empty_history)


def style_instrument(plot: Plot) -> None:
    style_figure(plot)
    plot.background_fill_color = PLUM
    plot.border_fill_color = PLUM
    plot.outline_line_color = DARK_GRID
    plot.grid.grid_line_color = DARK_GRID
    plot.grid.grid_line_alpha = 0.42
    plot.axis.axis_line_color = DARK_GRID
    plot.axis.major_tick_line_color = DARK_GRID
    plot.axis.major_label_text_color = CHALK
    plot.axis.axis_label_text_color = CHALK
    assert isinstance(plot.title, Title)
    plot.title.text_color = CHALK


def add_filter_guides(plot: Plot) -> FilterGuide:
    region = BoxAnnotation(
        fill_color=GOLD, fill_alpha=0.10, line_color=GOLD, line_alpha=0.48, line_width=1
    )
    center = Span(
        dimension="height", line_color=GOLD, line_alpha=0.9, line_dash="dashed", line_width=1.5
    )
    plot.add_layout(region)
    plot.add_layout(center)
    return region, center


def build_plots(sources: Sources) -> Plots:
    frequency_range = Range1d(start=0, end=NYQUIST)
    mapper = LinearColorMapper(palette=Inferno256, low=SPECTRUM_FLOOR, high=SPECTRUM_CEILING)

    spectrum = figure(
        title="Live spectrum · raw signal and receiver output",
        height=270,
        sizing_mode="stretch_width",
        x_range=frequency_range,
        y_range=Range1d(start=SPECTRUM_FLOOR, end=SPECTRUM_CEILING),
        tools="",
        toolbar_location=None,
        name="spectrum-power-plot",
    )
    spectrum.line(
        "frequency",
        "raw",
        source=sources.power,
        color="#aa98a2",
        line_alpha=0.58,
        line_width=1.2,
        legend_label="Received",
    )
    filtered_line = spectrum.line(
        "frequency",
        "filtered",
        source=sources.power,
        color=CORAL,
        line_width=2.2,
        legend_label="After filter",
    )
    spectrum.add_tools(
        HoverTool(
            renderers=[filtered_line],
            mode="vline",
            tooltips=[("Frequency", "@frequency{0} Hz"), ("Filtered power", "@filtered{0.0} dB")],
        )
    )
    spectrum.yaxis.axis_label = "Power (dB)"
    spectrum.xaxis.visible = False
    spectrum.legend.location = "top_right"
    spectrum.legend.orientation = "horizontal"
    spectrum.legend.click_policy = "mute"
    spectrum.legend.background_fill_color = PLUM
    spectrum.legend.background_fill_alpha = 0.82
    spectrum.legend.border_line_color = DARK_GRID
    spectrum.legend.label_text_color = CHALK
    style_instrument(spectrum)

    response_range = Range1d(start=-60, end=1)
    response = figure(
        title="Receiver filter response · gain (dB)",
        height=105,
        sizing_mode="stretch_width",
        x_range=frequency_range,
        y_range=response_range,
        tools="",
        toolbar_location=None,
        name="spectrum-filter-response-plot",
    )
    response.varea(
        x="frequency", y1=-60, y2="gain", source=sources.response, fill_color=GOLD, fill_alpha=0.12
    )
    response.line("frequency", "gain", source=sources.response, color=GOLD, line_width=2)
    response.xaxis.visible = False
    response.yaxis.ticker = BasicTicker(desired_num_ticks=3)
    style_instrument(response)

    spectrogram = figure(
        title=f"Filtered waterfall · newest signal at top, {HISTORY_SECONDS:.0f} seconds of history",
        height=475,
        sizing_mode="stretch_width",
        x_range=frequency_range,
        y_range=Range1d(start=-HISTORY_SECONDS, end=0),
        tools="tap",
        toolbar_location=None,
        name="spectrum-spectrogram-plot",
    )
    image = spectrogram.image(
        image="image",
        x="x",
        y="y",
        dw="dw",
        dh="dh",
        source=sources.history,
        color_mapper=mapper,  # pyright: ignore[reportCallIssue]
    )
    spectrogram.add_tools(
        HoverTool(
            renderers=[image],
            tooltips=[
                ("Frequency", "$x{0} Hz"),
                ("Power", "@image{0.0} dB"),
                ("Age", "$y{0.0} s"),
                ("Action", "Tap to retune manual filters"),
            ],
        )
    )
    spectrogram.xaxis.axis_label = "Frequency (Hz) · tap anywhere to retune"
    spectrogram.yaxis.axis_label = "Seconds before now"
    spectrogram.add_layout(
        ColorBar(
            color_mapper=mapper,
            title="Power (dB)",
            width=14,
            location=(6, 0),
            background_fill_color=PLUM,
            border_line_color=None,
            major_label_text_color=CHALK,
            title_text_color=CHALK,
            major_tick_line_color=CHALK,
        ),
        "right",
    )
    style_instrument(spectrogram)

    plots_with_guides = (spectrum, spectrogram)
    filter_guides = [add_filter_guides(plot) for plot in plots_with_guides]
    second_filter_guides = [add_filter_guides(plot) for plot in plots_with_guides]
    return Plots(
        spectrum, response, spectrogram, response_range, filter_guides, second_filter_guides
    )


def build_layout(controls: Controls, plots: Plots, status: Div) -> Column:
    controls_layout = column(
        Div(
            text=(
                '<h2 style="margin:0 0 5px">Tune the receiver</h2>'
                '<p style="margin:0">All three displays share the same frequency axis. Manual filters can be '
                "retuned across the visible history; adaptive changes apply only to new measurements.</p>"
            )
        ),
        controls.primary,
        controls.specialized,
        controls.watch_note,
        sizing_mode="stretch_width",
        styles={"background": WARM, "padding": "14px 16px", "border": f"1px solid {GRID}"},
    )
    match_background(controls_layout, WARM)
    console = column(
        status,
        plots.spectrum,
        plots.response,
        plots.spectrogram,
        sizing_mode="stretch_width",
        spacing=0,
        name="spectrum-console",
        styles={"background": PLUM, "border": f"1px solid {DARK_GRID}"},
    )
    match_background(console, PLUM)
    note = Div(
        text=(
            f"<p><strong>Simulation:</strong> every signal is generated from a reproducible model with seed "
            f"<code>{SEED}</code>. Each update streams one filtered <code>float32</code> spectrum row through "
            "Bokeh's binary transport. Manual filter changes reprocess the visible history, while adaptive "
            "settings affect only subsequent rows. The display contains no captured or licensed radio traffic.</p>"
        )
    )
    return column(controls_layout, console, note, sizing_mode="stretch_width", spacing=10)


def build_view() -> SpectrumView:
    controls = build_controls()
    sources = build_sources()
    plots = build_plots(sources)
    status = Div(
        name="spectrum-receiver-status",
        sizing_mode="stretch_width",
        styles={"border-bottom": f"1px solid {DARK_GRID}", "box-sizing": "border-box"},
    )
    return SpectrumView(controls, sources, plots, status, build_layout(controls, plots, status))
