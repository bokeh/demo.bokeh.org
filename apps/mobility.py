"""Compare vehicle attributes with linked selections and distributions."""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd
from bokeh.layouts import column
from bokeh.models import ColumnDataSource, Div, FactorRange, HoverTool, Range1d, RangeSlider, Select
from bokeh.plotting import figure
from vega_datasets import local_data

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


def modify_document(document) -> None:
    performance = monitor_document(document, "/mobility")
    frame = cast(pd.DataFrame, local_data.cars()).dropna().copy()
    frame["Model_year"] = frame["Year"].dt.year
    colors = {"USA": CORAL, "Europe": TEAL, "Japan": VIOLET}
    frame["Color"] = frame["Origin"].map(colors.__getitem__)
    measures = {
        "Fuel economy (mpg)": "Miles_per_Gallon",
        "Horsepower": "Horsepower",
        "Weight (lb)": "Weight_in_lbs",
        "Acceleration (s)": "Acceleration",
        "Displacement": "Displacement",
    }

    origin_filter = Select(
        title="Origin", value="All origins", options=["All origins", "USA", "Europe", "Japan"]
    )
    year_filter = RangeSlider(title="Model year", start=1970, end=1982, value=(1970, 1982), step=1)
    cylinder_filter = Select(
        title="Cylinders", value="All", options=["All", "3", "4", "5", "6", "8"]
    )
    x_axis = Select(title="Horizontal measure", value="Horsepower", options=list(measures))
    y_axis = Select(title="Vertical measure", value="Fuel economy (mpg)", options=list(measures))

    vehicle_source = ColumnDataSource(data={}, name="vehicle-scatter-source")
    histogram_source = ColumnDataSource(data={"top": [], "left": [], "right": []})
    origin_source = ColumnDataSource(
        data={
            "origin": ["USA", "Europe", "Japan"],
            "economy": [0, 0, 0],
            "color": [CORAL, TEAL, VIOLET],
        }
    )
    active_rows = np.arange(len(frame))
    selected_count = metric("Vehicles in analysis", str(len(frame)), accent=CORAL)
    economy_card = metric("Median fuel economy", "...", accent=TEAL)
    power_card = metric("Mean horsepower", "...", accent=GOLD)
    year_card = metric("Model-year span", "...", accent=VIOLET)
    filter_status = Div(text="", name="vehicle-filter-status")

    scatter_x_range = Range1d(start=0, end=1)
    scatter_y_range = Range1d(start=0, end=1)
    scatter = figure(
        name="vehicle-scatter",
        height=470,
        sizing_mode="stretch_width",
        x_range=scatter_x_range,
        y_range=scatter_y_range,
        tools="pan,wheel_zoom,lasso_select,box_select,reset",
        active_scroll=None,
    )
    scatter.scatter(
        "x",
        "y",
        source=vehicle_source,
        size=10,
        color="color",
        alpha=0.68,
        line_color=None,
        selection_color=GOLD,
        selection_alpha=0.95,
        nonselection_alpha=0.08,
    )
    scatter.add_tools(
        HoverTool(
            tooltips=[
                ("Vehicle", "@name"),
                ("Origin", "@origin"),
                ("Model year", "@year"),
                ("Fuel economy", "@economy{0.0} mpg"),
                ("Horsepower", "@horsepower{0}"),
            ]
        )
    )
    style_figure(scatter)

    histogram = figure(height=285, sizing_mode="stretch_width", toolbar_location=None)
    histogram.quad(
        top="top",
        bottom=0,
        left="left",
        right="right",
        source=histogram_source,
        fill_color=TEAL,
        fill_alpha=0.75,
        line_color="#fffdf9",
    )
    histogram.xaxis.axis_label = "Fuel economy (mpg)"
    histogram.yaxis.axis_label = "Vehicles"
    style_figure(histogram)

    by_origin = figure(
        height=285,
        width=390,
        x_range=FactorRange(factors=["USA", "Europe", "Japan"]),
        y_range=Range1d(start=0, end=45),
        toolbar_location=None,
    )
    by_origin.vbar(x="origin", top="economy", source=origin_source, width=0.62, color="color")
    by_origin.yaxis.axis_label = "Mean fuel economy (mpg)"
    style_figure(by_origin)

    def padded_bounds(values: np.ndarray) -> tuple[float, float]:
        low = float(np.min(values))
        high = float(np.max(values))
        padding = max((high - low) * 0.06, abs(low) * 0.02, 0.5)
        return low - padding, high + padding

    def update_analysis(local_indices: np.ndarray) -> None:
        if not len(active_rows):
            histogram_source.data = {"top": [], "left": [], "right": []}
            set_metric(selected_count, "0")
            set_metric(economy_card, "No vehicles")
            set_metric(power_card, "No vehicles")
            set_metric(year_card, "No vehicles")
            return
        chosen = active_rows[local_indices] if len(local_indices) else active_rows
        selected = frame.iloc[chosen]
        values = selected["Miles_per_Gallon"].to_numpy()
        bins = np.linspace(8, 48, 21)
        hist, edges = np.histogram(values, bins=bins)
        histogram_source.data = {"top": hist, "left": edges[:-1], "right": edges[1:]}
        set_metric(selected_count, str(len(selected)))
        set_metric(economy_card, f"{np.median(values):.1f} mpg")
        set_metric(power_card, f"{selected['Horsepower'].mean():.0f} hp")
        set_metric(year_card, f"{selected['Model_year'].min()} to {selected['Model_year'].max()}")

    def calculate_filter() -> None:
        nonlocal active_rows
        low, high = (int(value) for value in year_filter.value)
        keep = frame["Model_year"].between(low, high)
        if origin_filter.value != "All origins":
            keep &= frame["Origin"] == origin_filter.value
        if cylinder_filter.value != "All":
            keep &= frame["Cylinders"] == int(cylinder_filter.value)
        active_rows = np.flatnonzero(keep.to_numpy())
        filtered = frame.iloc[active_rows]
        x_values = filtered[measures[x_axis.value]].to_numpy()
        y_values = filtered[measures[y_axis.value]].to_numpy()
        vehicle_source.data = {
            "x": x_values,
            "y": y_values,
            "name": filtered["Name"].to_numpy(),
            "origin": filtered["Origin"].to_numpy(),
            "year": filtered["Model_year"].to_numpy(),
            "economy": filtered["Miles_per_Gallon"].to_numpy(),
            "horsepower": filtered["Horsepower"].to_numpy(),
            "color": filtered["Color"].to_numpy(),
        }
        scatter.xaxis.axis_label = x_axis.value
        scatter.yaxis.axis_label = y_axis.value
        if len(filtered):
            scatter_x_range.start, scatter_x_range.end = padded_bounds(x_values)
            scatter_y_range.start, scatter_y_range.end = padded_bounds(y_values)
            filter_status.text = ""
        else:
            filter_status.text = (
                f'<div style="border-left:4px solid {CORAL};padding:8px 12px">'
                "<strong>No vehicles match these filters.</strong> "
                "Broaden the model year, origin, or cylinder selection.</div>"
            )
        averages = [
            filtered.loc[filtered["Origin"] == origin, "Miles_per_Gallon"].mean()
            for origin in ("USA", "Europe", "Japan")
        ]
        origin_source.data = {
            "origin": ["USA", "Europe", "Japan"],
            "economy": [0 if np.isnan(value) else value for value in averages],
            "color": [CORAL, TEAL, VIOLET],
        }
        vehicle_source.selected.indices = []
        update_analysis(np.array([], dtype=int))

    @performance.measure
    def update_filter(_attr: str, _old: object, _new: object) -> None:
        calculate_filter()

    @performance.measure
    def update_selection(_attr: str, _old: list[int], indices: list[int]) -> None:
        update_analysis(np.asarray(indices, dtype=int))

    for control in (origin_filter, cylinder_filter, x_axis, y_axis):
        control.on_change("value", update_filter)
    year_filter.on_change("value", update_filter)
    vehicle_source.selected.on_change("indices", update_selection)
    calculate_filter()

    attribution = Div(
        text=(
            "<p><strong>Data:</strong> Vega Datasets cars collection, originally published by "
            "Donoho et al. (1982) and made public by Carnegie Mellon University.</p>"
        )
    )
    controls = column(
        Div(
            text="<h2>Compare vehicle efficiency</h2><p>Filter the dataset, then lasso or box-select vehicles. Python recomputes the histogram and summary values from the selected rows.</p>"
        ),
        origin_filter,
        year_filter,
        cylinder_filter,
        filter_status,
        x_axis,
        y_axis,
        width=300,
        sizing_mode="stretch_height",
        styles={"background": "#f7f3ec", "padding": "20px", "border": "1px solid #ded7ce"},
    )
    match_background(controls, WARM)
    document.add_root(
        column(
            metric_row(
                selected_count, economy_card, power_card, year_card, sizing_mode="stretch_width"
            ),
            responsive_row(controls, scatter, sizing_mode="stretch_width"),
            responsive_row(histogram, by_origin, sizing_mode="stretch_width"),
            attribution,
            sizing_mode="stretch_width",
            spacing=16,
        )
    )
    prepare_document(document, "/mobility")
