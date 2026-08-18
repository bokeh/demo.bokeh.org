"""Test the vehicle mobility demo."""

from __future__ import annotations

from bokeh.document import Document
from bokeh.models import ColumnDataSource, Div, RangeSlider, Select

from catalog import load_applications


def test_vehicle_measure_pairs_stay_in_view() -> None:
    document = Document()
    load_applications()["/mobility"](document)
    horizontal = next(
        select
        for select in document.select({"type": Select})
        if select.title == "Horizontal measure"
    )
    vertical = next(
        select for select in document.select({"type": Select}) if select.title == "Vertical measure"
    )
    scatter = document.select_one({"name": "vehicle-scatter"})
    source = document.select_one({"type": ColumnDataSource, "name": "vehicle-scatter-source"})

    for horizontal_measure in horizontal.options:
        for vertical_measure in vertical.options:
            horizontal.value = horizontal_measure
            vertical.value = vertical_measure
            assert len(source.data["x"]) > 0
            assert scatter.x_range.start < min(source.data["x"])
            assert scatter.x_range.end > max(source.data["x"])
            assert scatter.y_range.start < min(source.data["y"])
            assert scatter.y_range.end > max(source.data["y"])


def test_vehicle_empty_filters_are_explained() -> None:
    document = Document()
    load_applications()["/mobility"](document)
    origin = next(
        select for select in document.select({"type": Select}) if select.title == "Origin"
    )
    cylinders = next(
        select for select in document.select({"type": Select}) if select.title == "Cylinders"
    )
    status = document.select_one({"type": Div, "name": "vehicle-filter-status"})

    origin.value = "Europe"
    cylinders.value = "8"
    assert "No vehicles match" in status.text
    cylinders.value = "4"
    assert status.text == ""


def test_vehicle_year_filter_updates_while_dragging() -> None:
    document = Document()
    load_applications()["/mobility"](document)
    years = next(slider for slider in document.select({"type": RangeSlider}))
    source = document.select_one({"type": ColumnDataSource, "name": "vehicle-scatter-source"})

    years.value = (1980, 1982)

    assert min(source.data["year"]) >= 1980
