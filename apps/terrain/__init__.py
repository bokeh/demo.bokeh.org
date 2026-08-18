"""Explore modeled terrain through contours and an adjustable transect."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
from bokeh.layouts import column
from bokeh.models import (
    Button,
    ColumnDataSource,
    CustomJS,
    Div,
    HoverTool,
    LabelSet,
    PointDrawTool,
    Range1d,
    Select,
    Span,
    Toggle,
)
from bokeh.plotting import figure
from bokeh.plotting.contour import contour_data

from apps._common import (
    match_background,
    metric,
    metric_row,
    monitor_document,
    prepare_document,
    responsive_row,
    set_metric,
    style_figure,
)
from apps._common.colors import CORAL, GOLD, TEAL, VIOLET, WARM

from .simulation import LANDFORMS, LEVELS, LandformName, X, Y, generate_terrain, sample_transect

DEFAULT_TRANSECT = {"x": [-4.5, 4.5], "y": [0.0, 0.0], "label": ["A", "B"]}
BATHYMETRY_COLORS = ["#173a4a", "#356a77", "#76a09b"]
ELEVATION_COLORS = [
    "#9fa884",
    "#adb083",
    "#bdbc88",
    "#d0c28c",
    "#d8b879",
    "#cd9664",
    "#bd7d58",
    "#a96450",
    "#7c4548",
    "#542437",
]
TERRAIN_COLORS = [*BATHYMETRY_COLORS, *ELEVATION_COLORS]
CONTOUR_DASHES = [[6, 4] if level < 0 else [] for level in LEVELS]
CONTOUR_LINE_COLORS = ["#173a4a" if level < 0 else "#665d62" for level in LEVELS]
CONTOUR_LINE_ALPHAS = [1.0 if level < 0 else 0.72 for level in LEVELS]
CONTOUR_LINE_WIDTHS = [2.0 if level < 0 else 1.25 for level in LEVELS]
TRANSECT_CHALK = "#f1dfbd"
TRANSECT_HANDLE_OUTLINE = "#211f20"
TOGGLE_STYLESHEET = """
:host { background: #f7f3ec; }
.bk-btn.bk-btn-primary { background: #4f7b7c !important; border-color: #3e6667 !important; color: white; }
.bk-btn.bk-btn-primary:hover { background: #426d6e !important; border-color: #365d5e !important; }
"""


def modify_document(document) -> None:
    performance = monitor_document(document, "/terrain-contours")
    landform_options = list(LANDFORMS)
    landform = Select(
        title="Modeled landform",
        value=landform_options[0],
        options=cast(list[str | None], landform_options),
    )
    outlines = Toggle(
        label="Hide contour outlines",
        active=True,
        button_type="primary",
        styles={"background": WARM},
        stylesheets=[TOGGLE_STYLESHEET],
    )
    reset = Button(label="Reset horizontal transect")

    # Keep drag feedback in BokehJS and send at most ten profile requests per second.
    transect_source = ColumnDataSource(
        data=dict(DEFAULT_TRANSECT), name="terrain-transect", syncable=False
    )
    transect_request = ColumnDataSource(
        data=dict(DEFAULT_TRANSECT), name="terrain-transect-request"
    )
    transect_source.js_on_change(
        "data",
        CustomJS(
            args={"request": transect_request},
            code="""
                const throttle = cb_obj.tags[0] ?? {last_sent: 0, timeout: null}
                const send_request = () => {
                    const data = cb_obj.data
                    const unchanged = ["x", "y", "label"].every((name) =>
                        data[name].length == request.data[name].length &&
                        data[name].every((value, index) => value == request.data[name][index])
                    )
                    if (!unchanged) {
                        request.data = {
                            x: Array.from(data.x),
                            y: Array.from(data.y),
                            label: Array.from(data.label),
                        }
                        request.change.emit()
                    }
                    throttle.last_sent = Date.now()
                    throttle.timeout = null
                }

                const remaining = 100 - (Date.now() - throttle.last_sent)
                if (remaining <= 0) {
                    clearTimeout(throttle.timeout)
                    send_request()
                } else {
                    clearTimeout(throttle.timeout)
                    throttle.timeout = setTimeout(send_request, remaining)
                }
                cb_obj.tags = [throttle]
            """,
        ),
    )
    profile_source = ColumnDataSource(
        data={"distance": np.zeros(241), "elevation": np.zeros(241)}, name="terrain-profile"
    )
    high_card = metric("High point", "...", accent=CORAL)
    relief_card = metric("Modeled relief", "...", accent=TEAL)
    alpine_card = metric("Area above 1,500 m", "...", accent=GOLD)
    grade_card = metric("Steepest grade", "...", accent=VIOLET)
    reading = Div(
        styles={"padding": "14px", "background": WARM, "border-left": f"4px solid {GOLD}"}
    )

    terrain = figure(
        height=540,
        sizing_mode="stretch_width",
        x_range=Range1d(start=-6, end=6),
        y_range=Range1d(start=-4.5, end=4.5),
        toolbar_location=None,
    )
    z = generate_terrain(cast(LandformName, landform.value))
    contours = terrain.contour(
        X,
        Y,
        z,
        LEVELS,
        fill_color=TERRAIN_COLORS,
        fill_alpha=0.9,
        line_color=CONTOUR_LINE_COLORS,
        line_alpha=CONTOUR_LINE_ALPHAS,
        line_width=CONTOUR_LINE_WIDTHS,
        line_dash=CONTOUR_DASHES,
        line_cap="round",
    )
    color_bar = contours.construct_color_bar(title="Elevation (m)")
    terrain.add_layout(color_bar, "right")
    terrain.xaxis.axis_label = "Distance east (km)"
    terrain.yaxis.axis_label = "Distance north (km)"
    style_figure(terrain)
    terrain.line(
        "x",
        "y",
        source=transect_source,
        color=TRANSECT_CHALK,
        line_width=2.25,
        line_dash="dashed",
        line_alpha=1,
        selection_alpha=1,
        nonselection_alpha=1,
        name="terrain-transect-guide",
    )
    handles = terrain.scatter(
        "x",
        "y",
        source=transect_source,
        size=15,
        hit_dilation=1.35,
        fill_color=TRANSECT_CHALK,
        fill_alpha=1,
        line_color=TRANSECT_HANDLE_OUTLINE,
        line_width=2,
        selection_alpha=1,
        nonselection_alpha=1,
        name="terrain-transect-handles",
    )
    handles.hover_glyph = handles.glyph.clone(size=23)
    terrain.add_layout(
        LabelSet(
            x="x",
            y="y",
            text="label",
            source=transect_source,
            x_offset=10,
            y_offset=10,
            text_color="#542437",
            text_font_style="bold",
            text_font_size="12px",
        )
    )
    point_draw = PointDrawTool(renderers=cast(Any, [handles]), add=False, num_objects=2)
    terrain.add_tools(HoverTool(renderers=[handles], tooltips=None))
    terrain.add_tools(point_draw)
    terrain.toolbar.active_drag = point_draw

    profile_range = Range1d(start=0, end=9)
    profile = figure(
        height=265,
        sizing_mode="stretch_width",
        x_range=profile_range,
        y_range=Range1d(start=float(LEVELS[0] - 50), end=2900),
        tools="",
        toolbar_location=None,
    )
    profile.varea(
        x="distance", y1=0, y2="elevation", source=profile_source, fill_color=TEAL, fill_alpha=0.24
    )
    profile.line("distance", "elevation", source=profile_source, color=TEAL, line_width=3)
    profile.add_layout(
        Span(
            location=0,
            dimension="width",
            line_color="#6f686c",
            line_dash="dashed",
            line_width=1.5,
            name="terrain-sea-level",
        )
    )
    profile.xaxis.axis_label = "Distance (km)"
    profile.yaxis.axis_label = "Elevation (m)"
    style_figure(profile)

    current_z = z

    def update_profile() -> None:
        coordinates = transect_request.data
        if len(coordinates["x"]) != 2 or len(coordinates["y"]) != 2:
            reading.text = "<p><strong>Two handles are required.</strong><br>Reset the transect to restore them.</p>"
            return
        x0, x1 = map(float, coordinates["x"])
        y0, y1 = map(float, coordinates["y"])
        distance, values = sample_transect(current_z, x0, y0, x1, y1)
        profile_source.patch(
            {
                "distance": [(slice(len(distance)), distance)],
                "elevation": [(slice(len(values)), values)],
            }
        )
        profile_range.end = max(float(distance[-1]), 0.1)
        peak_index = int(np.argmax(values))
        angle = np.degrees(np.arctan2(y1 - y0, x1 - x0))
        reading.text = (
            f"<p><strong>{distance[-1]:.2f} km transect at {angle:+.0f}°</strong><br>"
            f"The highest sampled point is <strong>{values[peak_index]:,.0f} m</strong>, "
            f"{distance[peak_index]:.2f} km from handle A.</p>"
        )

    def update_terrain() -> None:
        nonlocal current_z
        z = generate_terrain(cast(LandformName, landform.value))
        current_z = z
        contours.set_data(contour_data(X, Y, z, LEVELS))
        dy, dx = np.gradient(z, Y, X)
        cell_area = (X[1] - X[0]) * (Y[1] - Y[0])
        set_metric(high_card, f"{z.max():,.0f} m")
        set_metric(relief_card, f"{np.ptp(z):,.0f} m")
        set_metric(alpine_card, f"{np.count_nonzero(z >= 1500) * cell_area:.1f} km²")
        set_metric(grade_card, f"{np.hypot(dx, dy).max() / 10:.0f}%")
        update_profile()

    @performance.measure
    def choose_landform(_attr: str, _old: object, _new: object) -> None:
        update_terrain()

    @performance.measure
    def move_transect(_attr: str, _old: object, _new: object) -> None:
        update_profile()

    @performance.measure
    def toggle_outlines(_attr: str, _old: bool, active: bool) -> None:
        contours.fill_renderer.visible = True
        contours.line_renderer.visible = active
        outlines.label = "Hide contour outlines" if active else "Show contour outlines"

    @performance.measure
    def reset_transect() -> None:
        transect_source.data = dict(DEFAULT_TRANSECT)
        transect_request.data = dict(DEFAULT_TRANSECT)

    landform.on_change("value", choose_landform)
    transect_request.on_change("data", move_transect)
    outlines.on_change("active", toggle_outlines)
    reset.on_click(reset_transect)
    update_terrain()

    introduction = Div(
        text=(
            "<h2>Read the shape of a landscape</h2>"
            "<p>Switch between modeled landforms, then drag handles A and B to position or rotate the "
            "transect. The profile below follows the line at any angle. Filled bands show broad structure "
            "while contour lines preserve elevation intervals; dotted contours are below sea level.</p>"
        ),
        styles={"background": WARM},
    )
    controls = column(
        introduction,
        landform,
        outlines,
        reset,
        reading,
        width=320,
        sizing_mode="stretch_height",
        styles={"background": WARM, "padding": "20px", "border": "1px solid #ded7ce"},
    )
    match_background(controls, WARM)
    note = Div(
        text=(
            "<p><strong>Computation:</strong> NumPy builds each synthetic elevation field on a regular grid, "
            "then Bokeh computes the contour geometry and bilinearly samples the movable cross-section. "
            "Values illustrate topology and cross-section analysis; they are not surveyed terrain.</p>"
        )
    )
    document.add_root(
        column(
            metric_row(
                high_card, relief_card, alpine_card, grade_card, sizing_mode="stretch_width"
            ),
            responsive_row(controls, terrain, sizing_mode="stretch_width"),
            profile,
            note,
            sizing_mode="stretch_width",
            spacing=16,
        )
    )
    prepare_document(document, "/terrain-contours")
