"""Test the weather comparison demo."""

from __future__ import annotations

from bokeh.document import Document
from bokeh.models import ColumnDataSource, Div, Select, Slider

from apps._common.colors import CORAL
from catalog import load_applications


def test_weather_compares_year_with_full_record() -> None:
    document = Document()
    load_applications()["/climate"](document)
    year = next(
        select for select in document.select({"type": Select}) if select.title == "Year to inspect"
    )
    threshold = next(
        slider
        for slider in document.select({"type": Slider})
        if slider.title == "Heavy-rain threshold (mm)"
    )
    normal = document.select_one({"type": ColumnDataSource, "name": "weather-four-year-normal"})
    selected = document.select_one({"type": ColumnDataSource, "name": "weather-selected-year"})
    monthly = document.select_one({"type": ColumnDataSource, "name": "weather-monthly-comparison"})
    summary = document.select_one({"type": Div, "name": "weather-year-summary"})
    threshold_span = document.select_one({"name": "weather-heavy-rain-threshold"})

    assert len(normal.data["day"]) == 366
    assert len(monthly.data["rain"]) == 48
    assert monthly.data["outline"].count(CORAL) == 12
    assert monthly.data["outline_width"].count(1.5) == 12
    initial_heavy_days = selected.data["rain_color"].tolist().count(CORAL)
    threshold.value = 5
    assert selected.data["rain_color"].tolist().count(CORAL) > initial_heavy_days
    assert threshold_span.location == 5
    assert "5 mm threshold" in summary.text
    year.value = "2012"
    assert "2012:" in summary.text
    assert monthly.data["outline"].count(CORAL) == 12
    assert monthly.data["outline_width"].count(1.5) == 12
