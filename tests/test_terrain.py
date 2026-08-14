"""Test the terrain contour demo."""

from __future__ import annotations

import math

import numpy as np
import pytest
from bokeh.document import Document
from bokeh.events import ButtonClick
from bokeh.models import (
    Button,
    ColumnDataSource,
    ContourRenderer,
    HoverTool,
    Plot,
    PointDrawTool,
    Scatter,
    Select,
    Span,
    Toggle,
)

from apps.terrain import (
    BATHYMETRY_COLORS,
    ELEVATION_COLORS,
    LANDFORMS,
    LEVELS,
    TRANSECT_CHALK,
    TRANSECT_HANDLE_OUTLINE,
    generate_terrain,
)
from catalog import load_applications


def test_terrain_keeps_filled_bands_when_outlines_are_hidden() -> None:
    document = Document()
    load_applications()["/terrain-contours"](document)
    contours = list(document.select({"type": ContourRenderer}))
    assert len(contours) == 1
    assert contours[0].fill_renderer.visible
    assert LEVELS[0] < 0
    assert len(BATHYMETRY_COLORS) == int(np.count_nonzero(LEVELS[:-1] < 0))
    assert len(ELEVATION_COLORS) == int(np.count_nonzero(LEVELS[:-1] >= 0))
    line_data = contours[0].line_renderer.data_source.data
    assert line_data["line_dash"] == [[6, 4] if level < 0 else [] for level in line_data["levels"]]
    negative_widths = [
        width
        for level, width in zip(line_data["levels"], line_data["line_width"], strict=True)
        if level < 0
    ]
    positive_widths = [
        width
        for level, width in zip(line_data["levels"], line_data["line_width"], strict=True)
        if level >= 0
    ]
    assert min(negative_widths) > max(positive_widths)
    assert min(float(generate_terrain(kind).min()) for kind in LANDFORMS) < 0
    assert float(generate_terrain("Glacial basin").min()) < -600
    profile_plot = next(
        plot
        for plot in document.select({"type": Plot})
        if plot.yaxis and plot.yaxis[0].axis_label == "Elevation (m)"
    )
    assert profile_plot.y_range.start < 0
    assert profile_plot.xaxis[0].axis_label == "Distance (km)"
    assert profile_plot.toolbar.tools == []
    sea_level = document.select_one({"type": Span, "name": "terrain-sea-level"})
    assert sea_level.location == 0
    assert sea_level.dimension == "width"
    outline_toggle = next(
        toggle for toggle in document.select({"type": Toggle}) if "contour outlines" in toggle.label
    )
    outline_toggle.active = False
    assert contours[0].fill_renderer.visible
    assert not contours[0].line_renderer.visible


def test_terrain_has_multiple_landforms_and_a_movable_transect() -> None:
    document = Document()
    load_applications()["/terrain-contours"](document)
    landform = next(
        select for select in document.select({"type": Select}) if select.title == "Modeled landform"
    )
    assert len(landform.options) >= 10
    for option in landform.options:
        landform.value = option
    tools = list(document.select({"type": PointDrawTool}))
    assert len(tools) == 1
    guide = document.select_one({"name": "terrain-transect-guide"})
    assert guide.glyph.line_alpha == 1
    assert guide.selection_glyph.line_alpha == 1
    assert guide.nonselection_glyph.line_alpha == 1
    assert guide.glyph.line_color == TRANSECT_CHALK
    assert guide.glyph.line_width == 2.25
    assert guide.selection_glyph.line_color == guide.glyph.line_color
    assert guide.nonselection_glyph.line_color == guide.glyph.line_color
    handles = document.select_one({"name": "terrain-transect-handles"})
    assert isinstance(handles.hover_glyph, Scatter)
    assert handles.glyph.size == 15
    assert handles.hover_glyph.size == 23
    assert handles.glyph.fill_color == TRANSECT_CHALK
    assert handles.hover_glyph.fill_color.value == TRANSECT_CHALK
    assert handles.selection_glyph.fill_color == TRANSECT_CHALK
    assert handles.nonselection_glyph.fill_color == TRANSECT_CHALK
    assert handles.glyph.line_color == TRANSECT_HANDLE_OUTLINE
    assert handles.hover_glyph.line_color.value == TRANSECT_HANDLE_OUTLINE
    assert handles.selection_glyph.line_color == TRANSECT_HANDLE_OUTLINE
    assert handles.nonselection_glyph.line_color == TRANSECT_HANDLE_OUTLINE
    handle_hovers = [
        tool for tool in document.select({"type": HoverTool}) if tool.renderers == [handles]
    ]
    assert len(handle_hovers) == 1
    assert handle_hovers[0].tooltips is None
    source = document.select_one({"type": ColumnDataSource, "name": "terrain-transect"})
    profile = document.select_one({"type": ColumnDataSource, "name": "terrain-profile"})
    source.data = {"x": [-3.0, 3.0], "y": [-2.0, 2.0], "label": ["A", "B"]}
    assert profile.data["distance"][-1] == pytest.approx(math.hypot(6, 4), abs=5e-8)
    reset = next(
        button
        for button in document.select({"type": Button})
        if button.label == "Reset horizontal transect"
    )
    reset._trigger_event(ButtonClick(reset))
    assert source.data["x"] == [-4.5, 4.5]
    assert source.data["y"] == [0.0, 0.0]
