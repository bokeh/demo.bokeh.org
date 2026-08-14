"""Explore synthetic wave fields and their cross-sections."""

from __future__ import annotations

import numpy as np
from bokeh.layouts import column
from bokeh.models import (
    ColorBar,
    ColumnDataSource,
    Div,
    LinearColorMapper,
    Range1d,
    Select,
    Slider,
    Span,
)
from bokeh.palettes import Inferno256, Turbo256, Viridis256
from bokeh.plotting import figure
from scipy.special import j1

from apps._common import (
    match_background,
    metric,
    metric_row,
    prepare_document,
    responsive_row,
    set_metric,
    style_figure,
)
from apps._common.colors import CORAL, GOLD, TEAL, VIOLET, WARM

FIELD_AXIS = np.linspace(-3, 3, 61)
SECTION_AXIS = np.linspace(-3, 3, 401)
CELL_SIZE = 6 / (len(FIELD_AXIS) - 1)
FIELD_EDGE = 3 + CELL_SIZE / 2
OPTIONS = (
    "Interference",
    "Standing modes",
    "Twin sources",
    "Quasicrystal interference",
    "Airy diffraction",
    "Wave packet",
    "Ripple tank",
    "Vortex",
    "Peaks",
)


def evaluate_field(
    model: str, x: np.ndarray, y: np.ndarray, frequency: float, coupling: float
) -> np.ndarray:
    match model:
        case "Interference":
            return np.sin(frequency * x) * np.cos(frequency * y) + coupling * np.sin(x * y)
        case "Standing modes":
            x_mode = 1.0 + frequency
            y_mode = 1.0 + 0.75 * frequency
            return np.sin(x_mode * x) * np.sin(y_mode * y) + 0.35 * coupling * np.cos(2 * y)
        case "Twin sources":
            separation = 0.7 + 0.65 * coupling
            left_radius = np.sqrt((x + separation) ** 2 + y**2)
            right_radius = np.sqrt((x - separation) ** 2 + y**2)
            return 0.5 * (
                np.cos(2.5 * frequency * left_radius) + np.cos(2.5 * frequency * right_radius)
            )
        case "Quasicrystal interference":
            angles = np.linspace(0, 2 * np.pi, 5, endpoint=False)
            wave_number = 2.2 * frequency
            primary = np.sum(
                [np.cos(wave_number * (np.cos(angle) * x + np.sin(angle) * y)) for angle in angles],
                axis=0,
            )
            rotated = np.sum(
                [
                    np.cos(
                        wave_number
                        * (np.cos(angle + np.pi / 10) * x + np.sin(angle + np.pi / 10) * y)
                    )
                    for angle in angles
                ],
                axis=0,
            )
            return (primary + 0.5 * coupling * rotated) / (5 * (1 + 0.5 * coupling))
        case "Airy diffraction":
            argument = 3.2 * frequency * np.hypot(x, y)
            amplitude = np.divide(
                2 * j1(argument), argument, out=np.ones_like(argument), where=argument != 0
            )
            fringes = np.cos(1.5 * coupling * frequency * x) ** 2
            intensity = amplitude**2 * fringes
            return np.log1p(1000 * intensity) / np.log1p(1000)
        case "Wave packet":
            left_envelope = np.exp(-0.7 * ((x + 1.15) ** 2 + 0.55 * y**2))
            right_envelope = np.exp(-0.7 * ((x - 1.15) ** 2 + 0.55 * y**2))
            return left_envelope * np.sin(2.5 * frequency * x) - coupling * right_envelope * np.cos(
                2 * frequency * x
            )
        case "Ripple tank":
            source_offset = 0.8 + 0.45 * coupling
            source_radii = (
                np.sqrt((x + source_offset) ** 2 + (y + 0.7) ** 2),
                np.sqrt((x - source_offset) ** 2 + (y + 0.7) ** 2),
                np.sqrt(x**2 + (y - 1.1) ** 2),
            )
            ripples = [
                np.cos(2.4 * frequency * radius) / (1 + 0.35 * radius) for radius in source_radii
            ]
            return np.sum(ripples, axis=0) / 2
        case "Vortex":
            radius = np.sqrt(x**2 + y**2)
            angle = np.arctan2(y, x)
            return np.sin(frequency * radius * 2 + angle * (1 + coupling)) * np.exp(
                -0.13 * radius**2
            )
        case "Peaks":
            return (
                np.exp(-((x - coupling / 2) ** 2 + (y + 0.5) ** 2))
                - 0.8 * np.exp(-((x + 1) ** 2 + (y - coupling / 2) ** 2) * 1.4)
            ) * frequency
        case _:
            raise ValueError(f"Unknown field model: {model}")


def modify_document(document) -> None:
    xx, yy = np.meshgrid(FIELD_AXIS, FIELD_AXIS)
    field_source = ColumnDataSource(
        data={"x": xx.ravel(), "y": yy.ravel(), "z": np.zeros(xx.size)}, name="wave-field-values"
    )
    section_source = ColumnDataSource(
        data={"x": SECTION_AXIS, "z": np.zeros_like(SECTION_AXIS)}, name="wave-cross-section"
    )
    distribution_source = ColumnDataSource(data={"top": [], "left": [], "right": []})
    palettes = {"Viridis": Viridis256, "Turbo": Turbo256, "Inferno": Inferno256}
    mapper = LinearColorMapper(palette=Viridis256, low=-1, high=1)

    field = Select(title="Field model", value=OPTIONS[0], options=list(OPTIONS))
    frequency = Slider(title="Spatial frequency", start=0.5, end=4.0, step=0.1, value=1.8)
    coupling = Slider(title="Coupling", start=0, end=2.0, step=0.05, value=0.7)
    cross_section = Slider(title="Cross-section y", start=-3, end=3, step=0.05, value=0)
    palette = Select(title="Palette", value="Viridis", options=list(palettes))
    minimum_card = metric("Minimum", "...", accent=CORAL)
    maximum_card = metric("Maximum", "...", accent=TEAL)
    energy_card = metric("Mean energy", "...", accent=GOLD)
    section_card = metric("Cross-section mean", "...", accent=VIOLET)

    field_plot = figure(
        height=520,
        sizing_mode="stretch_width",
        x_range=Range1d(start=-FIELD_EDGE, end=FIELD_EDGE),
        y_range=Range1d(start=-FIELD_EDGE, end=FIELD_EDGE),
        tools="",
        output_backend="webgl",
        name="wave-field-plot",
    )
    field_plot.rect(
        "x",
        "y",
        width=CELL_SIZE,
        height=CELL_SIZE,
        source=field_source,
        line_color=None,
        fill_color={"field": "z", "transform": mapper},
    )
    section_marker = Span(
        location=0, dimension="width", line_color=GOLD, line_width=3, line_dash="dashed"
    )
    field_plot.add_layout(section_marker)
    field_plot.add_layout(
        ColorBar(color_mapper=mapper, width=14, margin=0, padding=0, location=(6, 0)), "right"
    )
    field_plot.xaxis.axis_label = "Parameter x"
    field_plot.yaxis.axis_label = "Parameter y"
    style_figure(field_plot)

    profile = figure(
        height=260,
        sizing_mode="stretch_width",
        x_range=field_plot.x_range,
        tools="",
        toolbar_location=None,
    )
    profile.line("x", "z", source=section_source, line_color=CORAL, line_width=3)
    profile.varea(x="x", y1=0, y2="z", source=section_source, fill_color=TEAL, fill_alpha=0.2)
    profile.xaxis.axis_label = "Parameter x"
    profile.yaxis.axis_label = "Field value at selected y"
    style_figure(profile)

    distribution = figure(height=260, width=400, tools="", toolbar_location=None)
    distribution.quad(
        top="top",
        bottom=0,
        left="left",
        right="right",
        source=distribution_source,
        fill_color=VIOLET,
        fill_alpha=0.75,
        line_color="#fffdf9",
    )
    distribution.xaxis.axis_label = "Field value"
    distribution.yaxis.axis_label = "Cells"
    style_figure(distribution)

    def calculate() -> None:
        f = frequency.value
        c = coupling.value
        values = evaluate_field(field.value, xx, yy, f, c)
        section_y = float(cross_section.value)
        section = evaluate_field(
            field.value, SECTION_AXIS, np.full_like(SECTION_AXIS, section_y), f, c
        )
        counts, edges = np.histogram(values, bins=24)

        mapper.low = float(values.min())
        mapper.high = float(values.max())
        mapper.palette = palettes[palette.value]
        field_source.data = {"x": xx.ravel(), "y": yy.ravel(), "z": values.ravel()}
        section_source.data = {"x": SECTION_AXIS, "z": section}
        distribution_source.data = {"top": counts, "left": edges[:-1], "right": edges[1:]}
        section_marker.location = section_y
        set_metric(minimum_card, f"{values.min():.2f}")
        set_metric(maximum_card, f"{values.max():.2f}")
        set_metric(energy_card, f"{np.mean(values**2):.2f}")
        set_metric(section_card, f"{np.mean(section):+.2f}")

    def update(_attr: str, _old: object, _new: object) -> None:
        calculate()

    for control in (field, frequency, coupling, cross_section, palette):
        control.on_change("value", update)
    calculate()

    controls = column(
        Div(
            text=f"<h2>Recompute a wave field</h2><p>Change the model, move the cross-section, or adjust its parameters. NumPy and SciPy update {FIELD_AXIS.size**2:,} field cells and independently sample 401 points for the profile.</p>"
        ),
        field,
        frequency,
        coupling,
        cross_section,
        palette,
        width=300,
        sizing_mode="stretch_height",
        styles={"background": "#f7f3ec", "padding": "20px", "border": "1px solid #ded7ce"},
    )
    match_background(controls, WARM)
    document.add_root(
        column(
            metric_row(
                minimum_card, maximum_card, energy_card, section_card, sizing_mode="stretch_width"
            ),
            responsive_row(controls, field_plot, sizing_mode="stretch_width"),
            responsive_row(profile, distribution, sizing_mode="stretch_width"),
            Div(
                text=f"<p><strong>Data:</strong> computed in the application from {len(OPTIONS)} selectable NumPy and SciPy field models.</p>"
            ),
            sizing_mode="stretch_width",
            spacing=16,
        )
    )
    prepare_document(document, "/wave-field")
