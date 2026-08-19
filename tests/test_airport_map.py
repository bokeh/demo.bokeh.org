"""Test the airport route demo."""

from __future__ import annotations

import numpy as np
from bokeh.document import Document
from bokeh.models import ColumnDataSource, HoverTool, Range1d, Select, TileRenderer

from catalog import load_applications


def test_airport_map_uses_tiles_and_links_the_selected_airport() -> None:
    document = Document()
    load_applications()["/airport-access"](document)
    assert len(list(document.select({"type": TileRenderer}))) == 1
    state = next(
        select
        for select in document.select({"type": Select})
        if select.title == "State or territory"
    )
    anchor = next(
        select for select in document.select({"type": Select}) if select.title == "Anchor airport"
    )
    airports = document.select_one({"type": ColumnDataSource, "name": "airport-map"})
    ranking = document.select_one({"type": ColumnDataSource, "name": "airport-neighbors"})
    access = document.select_one({"type": ColumnDataSource, "name": "airport-access-curve"})
    map_plot = document.select_one({"name": "airport-map-plot"})
    ranking_plot = document.select_one({"name": "airport-distance-ranking"})
    access_plot = document.select_one({"name": "airport-access-plot"})
    state_boundaries = document.select_one({"name": "airport-state-boundaries"})
    assert map_plot.match_aspect
    assert isinstance(map_plot.x_range, Range1d)
    assert isinstance(map_plot.y_range, Range1d)
    assert state_boundaries.glyph.line_width == 1.3
    assert state_boundaries.glyph.line_alpha == 0.55
    assert ranking_plot.toolbar.tools == []
    assert access_plot.toolbar.tools == []
    assert ranking_plot.xaxis[0].axis_label == "Distance (miles)"
    assert not ranking_plot.ygrid[0].visible
    assert (access_plot.y_range.start, access_plot.y_range.end) == (0, 1_200)
    assert state.value == "WA"
    assert anchor.value == "SEA"
    assert len(ranking.data["distance"]) == 6
    airport_count = len(airports.data["iata"])
    assert airport_count > 500
    assert (np.diff(access.data["count"]) >= 0).all()
    previous_view = (map_plot.x_range.start, map_plot.x_range.end)
    access_updates = []
    access.on_change("data", lambda _attr, _old, new: access_updates.append(new))
    state.value = "CA"
    assert len(access_updates) == 1
    assert len(airports.data["iata"]) == airport_count
    assert any(value != "CA" for value in airports.data["state"])
    assert len(ranking.data["distance"]) == 6
    assert (map_plot.x_range.start, map_plot.x_range.end) != previous_view
    assert map_plot.x_range.reset_start == map_plot.x_range.start
    assert map_plot.x_range.reset_end == map_plot.x_range.end
    adjacent_index = next(
        index for index, value in enumerate(airports.data["state"]) if value == "NV"
    )
    airports.selected.indices = [adjacent_index]
    assert anchor.value == airports.data["iata"][adjacent_index]
    hover = next(tool for tool in map_plot.toolbar.tools if isinstance(tool, HoverTool))
    assert f"From {anchor.value}" in [label for label, _value in hover.tooltips]
    assert ranking_plot.title.text == f"Closest alternatives to {anchor.value}"
    state.value = "GU"
    assert len(airports.data["iata"]) == airport_count
    assert len(ranking.data["distance"]) == 6
