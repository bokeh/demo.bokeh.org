"""Explore US airport reach and traffic from a selected hub."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
from bokeh.layouts import column
from bokeh.models import (
    ColumnDataSource,
    DataRange1d,
    Div,
    FactorRange,
    HoverTool,
    Range1d,
    Select,
    TapTool,
    Title,
)
from bokeh.plotting import figure
from bokeh.sampledata.us_states import (
    data as _US_STATES,  # pyright: ignore[reportAttributeAccessIssue]
)
from vega_datasets import local_data

from apps._common import (
    match_background,
    metric,
    metric_row,
    prepare_document,
    responsive_row,
    set_metric,
    style_figure,
)
from apps._common.colors import CORAL, GOLD, PAPER, TEAL, VIOLET, WARM

EARTH_RADIUS_M = 6_378_137
EARTH_RADIUS_MI = 3_958.7613
REACH_RADIUS_MILES = 500
REACH_COUNT_MAX = 1_200
REACH_RADII = np.linspace(0, REACH_RADIUS_MILES, 101)
US_STATES = cast(dict[str, dict[str, Any]], _US_STATES)
STATE_NAMES = {code: boundary["name"] for code, boundary in US_STATES.items()} | {
    "AS": "American Samoa",
    "CQ": "Northern Mariana Islands",
    "GU": "Guam",
    "PR": "Puerto Rico",
    "VI": "U.S. Virgin Islands",
}


def web_mercator(longitude: np.ndarray, latitude: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    longitude_radians = np.radians(longitude)
    latitude_radians = np.radians(np.clip(latitude, -85.0, 85.0))
    x = EARTH_RADIUS_M * longitude_radians
    y = EARTH_RADIUS_M * np.log(np.tan(np.pi / 4 + latitude_radians / 2))
    return x, y


STATE_BOUNDARY_XS, STATE_BOUNDARY_YS = zip(
    *(
        web_mercator(np.asarray(boundary["lons"]), np.asarray(boundary["lats"]))
        for boundary in US_STATES.values()
    ),
    strict=True,
)


def distance_miles(
    latitude: float, longitude: float, other_latitudes: np.ndarray, other_longitudes: np.ndarray
) -> np.ndarray:
    latitude_1 = np.radians(latitude)
    latitude_2 = np.radians(other_latitudes)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = np.radians(other_longitudes - longitude)
    haversine = (
        np.sin(delta_latitude / 2) ** 2
        + np.cos(latitude_1) * np.cos(latitude_2) * np.sin(delta_longitude / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(np.clip(haversine, 0, 1)))


def modify_document(document) -> None:
    airports = cast(pd.DataFrame, local_data.airports()).dropna().copy()
    airports = cast(pd.DataFrame, airports[airports["state"].isin(STATE_NAMES)])
    airports = airports.sort_values(by=["state", "city", "name"]).reset_index(drop=True)
    x, y = web_mercator(airports["longitude"].to_numpy(), airports["latitude"].to_numpy())
    airports["x"] = x
    airports["y"] = y
    airport_latitudes = airports["latitude"].to_numpy()
    airport_longitudes = airports["longitude"].to_numpy()
    airport_iatas = airports["iata"].to_numpy()
    airport_indices = {iata: index for index, iata in enumerate(airport_iatas)}
    airport_data = {
        column: airports[column].to_numpy()
        for column in ("x", "y", "iata", "name", "city", "state")
    }

    state = Select(
        title="State or territory",
        value="WA",
        options=[
            (code, f"{name} ({code})")
            for code, name in sorted(STATE_NAMES.items(), key=lambda item: item[1])
        ],
    )
    anchor = Select(title="Anchor airport", value="SEA", options=[])

    airport_source = ColumnDataSource(data={}, name="airport-map")
    viewport_source = ColumnDataSource(data={"x": [], "y": []}, name="airport-map-viewport")
    anchor_source = ColumnDataSource(data={"x": [], "y": [], "iata": []}, name="airport-anchor")
    route_source = ColumnDataSource(data={"xs": [], "ys": []}, name="airport-routes")
    ranking_source = ColumnDataSource(data={"label": [], "distance": []}, name="airport-neighbors")
    access_source = ColumnDataSource(
        data={"distance": [], "count": []}, name="airport-access-curve"
    )

    count_card = metric("Airports in selected region", "...", accent=TEAL)
    nearest_card = metric("Closest alternative", "...", accent=CORAL)
    radius_card = metric("Within 100 miles", "...", accent=GOLD)
    spacing_card = metric("Median of 5 nearest", "...", accent=VIOLET)
    reading = Div(
        styles={"padding": "14px", "background": WARM, "border-left": f"4px solid {GOLD}"}
    )

    map_x_range = DataRange1d(range_padding=0)
    map_y_range = DataRange1d(range_padding=0)
    map_title = Title()
    map_plot = figure(
        title=map_title,
        height=590,
        sizing_mode="stretch_width",
        x_axis_type="mercator",
        y_axis_type="mercator",
        x_range=map_x_range,
        y_range=map_y_range,
        tools="pan,wheel_zoom,reset",
        active_drag="pan",
        active_scroll=None,
        match_aspect=True,
        name="airport-map-plot",
    )
    map_plot.add_tile("CartoDB Positron", retina=True)
    map_plot.multi_line(
        xs=STATE_BOUNDARY_XS,
        ys=STATE_BOUNDARY_YS,
        line_color="#756b65",
        line_alpha=0.55,
        line_width=1.3,
        name="airport-state-boundaries",
    )
    viewport = map_plot.scatter(
        "x", "y", source=viewport_source, visible=False, name="airport-map-viewport-renderer"
    )
    map_x_range.renderers = [viewport]
    map_y_range.renderers = [viewport]
    map_plot.multi_line(
        xs="xs", ys="ys", source=route_source, color=CORAL, line_width=2.5, line_alpha=0.68
    )
    points = map_plot.scatter(
        "x",
        "y",
        source=airport_source,
        size=10,
        fill_color=TEAL,
        fill_alpha=0.86,
        line_color=PAPER,
        line_width=1.5,
        selection_fill_color=GOLD,
        selection_line_color="#8a6500",
        selection_fill_alpha=1,
        nonselection_fill_alpha=0.78,
        nonselection_line_alpha=0.9,
    )
    map_plot.scatter(
        "x",
        "y",
        source=anchor_source,
        size=22,
        marker="star",
        fill_color=GOLD,
        line_color="#542437",
        line_width=2,
    )
    map_plot.add_tools(TapTool(renderers=[points]))
    airport_hover = HoverTool(renderers=[points])
    map_plot.add_tools(airport_hover)
    map_plot.axis.visible = False
    style_figure(map_plot)
    map_plot.grid.visible = False

    ranking_x_range = Range1d(start=0, end=100)
    ranking_y_range = FactorRange()
    ranking_title = Title(text="Closest alternatives")
    ranking = figure(
        title=ranking_title,
        height=300,
        sizing_mode="stretch_width",
        x_range=ranking_x_range,
        y_range=ranking_y_range,
        tools="",
        toolbar_location=None,
        name="airport-distance-ranking",
    )
    ranking.hbar(
        y="label",
        right="distance",
        source=ranking_source,
        height=0.62,
        fill_color=TEAL,
        fill_alpha=0.82,
        line_color=None,
    )
    ranking.xaxis.axis_label = "Distance (miles)"
    style_figure(ranking)
    ranking.ygrid.visible = False

    access_title = Title(text="Airports within radius")
    access = figure(
        title=access_title,
        height=300,
        sizing_mode="stretch_width",
        x_range=Range1d(start=0, end=REACH_RADIUS_MILES),
        y_range=Range1d(start=0, end=REACH_COUNT_MAX),
        tools="",
        toolbar_location=None,
        name="airport-access-plot",
    )
    access.varea(
        x="distance", y1=0, y2="count", source=access_source, fill_color=GOLD, fill_alpha=0.18
    )
    access.line("distance", "count", source=access_source, color=VIOLET, line_width=2.5)
    access.xaxis.axis_label = "Distance (miles)"
    access.yaxis.axis_label = "Airports"
    style_figure(access)

    def update_airport() -> None:
        selected_index = airport_indices.get(anchor.value)
        if selected_index is None:
            return
        selected = airports.iloc[selected_index]
        distances = distance_miles(
            float(selected["latitude"]),
            float(selected["longitude"]),
            airport_latitudes,
            airport_longitudes,
        )
        airport_source.data = dict(airport_data, distance=distances)
        airport_source.selected.indices = [selected_index]
        anchor_source.data = {
            "x": [selected["x"]],
            "y": [selected["y"]],
            "iata": [selected["iata"]],
        }

        nearest_indices = np.argsort(distances)
        nearest_indices = nearest_indices[nearest_indices != selected_index][:6]
        nearest = airports.iloc[nearest_indices]
        nearest_distances = distances[nearest_indices]
        nearest_rows = list(nearest[["x", "y", "iata", "city"]].itertuples(index=False, name=None))
        route_source.data = {
            "xs": [[selected["x"], row[0]] for row in nearest_rows],
            "ys": [[selected["y"], row[1]] for row in nearest_rows],
        }
        labels = [f"{row[2]} · {row[3]}" for row in nearest_rows]
        ranking_source.data = {"label": labels, "distance": nearest_distances}
        ranking_y_range.factors = labels[::-1]
        ranking_x_range.end = (
            max(float(nearest_distances.max()) * 1.12, 10) if len(nearest_distances) else 10
        )

        other_distances = np.sort(distances[distances > 0])
        access_source.data = {
            "distance": REACH_RADII,
            "count": np.searchsorted(other_distances, REACH_RADII, side="right"),
        }

        map_title.text = f"Airport proximity from {selected['iata']}"
        ranking_title.text = f"Closest alternatives to {selected['iata']}"
        access_title.text = f"Regional reach from {selected['iata']}"
        airport_hover.tooltips = [
            ("Airport", "@iata — @name"),
            ("Location", "@city, @state"),
            (f"From {selected['iata']}", "@distance{0.0} miles"),
        ]

        closest_label = "No alternative"
        if len(nearest):
            closest_label = f"{nearest.iloc[0]['iata']} · {nearest_distances[0]:.0f} mi"
        set_metric(nearest_card, closest_label)
        set_metric(radius_card, str(np.count_nonzero((distances > 0) & (distances <= 100))))
        typical_spacing = (
            f"{np.median(nearest_distances[:5]):.0f} mi"
            if len(nearest_distances)
            else "No alternative"
        )
        set_metric(spacing_card, typical_spacing)
        reading.text = (
            f"<p><strong>{selected['iata']} · {selected['name']}</strong><br>"
            f"{selected['city']}, {selected['state']} · {selected['latitude']:.3f}°, "
            f"{selected['longitude']:.3f}°</p>"
        )

    def update_state() -> None:
        region = cast(pd.DataFrame, airports[airports["state"] == state.value]).reset_index(
            drop=True
        )
        anchor.options = [
            (iata, f"{iata} — {city} · {name}")
            for iata, city, name in region[["iata", "city", "name"]].itertuples(
                index=False, name=None
            )
        ]
        x_padding = max(float(np.ptp(region["x"])) * 0.18, 70_000)
        y_padding = max(float(np.ptp(region["y"])) * 0.18, 70_000)
        viewport_source.data = {
            "x": [float(region["x"].min()) - x_padding, float(region["x"].max()) + x_padding],
            "y": [float(region["y"].min()) - y_padding, float(region["y"].max()) + y_padding],
        }
        set_metric(count_card, f"{len(region):,}")

        if anchor.value in set(region["iata"]):
            update_airport()
        else:
            middle_x = float(np.median(region["x"]))
            middle_y = float(np.median(region["y"]))
            squared_distance = np.asarray(
                (region["x"] - middle_x) ** 2 + (region["y"] - middle_y) ** 2
            )
            representative = int(np.argmin(squared_distance))
            anchor.value = str(region.loc[representative, "iata"])

    def choose_state(_attr: str, _old: object, _new: object) -> None:
        update_state()

    def choose_airport(_attr: str, _old: object, _new: object) -> None:
        update_airport()

    def tap_airport(_attr: str, _old: list[int], indices: list[int]) -> None:
        if indices:
            selected_iata = str(airport_source.data["iata"][indices[0]])
            options = cast(list[str | tuple[str, str]], anchor.options)
            if selected_iata not in {
                option if isinstance(option, str) else option[0] for option in options
            }:
                selected = airports.iloc[airport_indices[selected_iata]]
                label = f"{selected['iata']} — {selected['city']} · {selected['name']}"
                anchor.options = [(selected_iata, label), *options]
            anchor.value = selected_iata

    state.on_change("value", choose_state)
    anchor.on_change("value", choose_airport)
    airport_source.selected.on_change("indices", tap_airport)
    update_state()

    introduction = Div(
        text=(
            "<h2>Compare regional airport access</h2>"
            "<p>The state selector moves the map without filtering the airport network. Choose an anchor from "
            "that region or tap any visible airport. Routes and rankings use airports across every state and territory.</p>"
        ),
        styles={"background": WARM},
    )
    controls = column(
        introduction,
        state,
        anchor,
        reading,
        width=330,
        sizing_mode="stretch_height",
        styles={"background": WARM, "padding": "20px", "border": "1px solid #ded7ce"},
    )
    match_background(controls, WARM)
    note = Div(
        text=(
            "<p><strong>Data and method:</strong> Airport locations come from the Vega Datasets airports "
            "collection. Neighbor calculations always use the full dataset. Distances use the haversine formula; "
            "straight routes show proximity, not scheduled "
            "service. Map tiles © OpenStreetMap contributors © CARTO and require a network connection.</p>"
        )
    )
    document.add_root(
        column(
            metric_row(
                count_card, nearest_card, radius_card, spacing_card, sizing_mode="stretch_width"
            ),
            responsive_row(controls, map_plot, sizing_mode="stretch_width"),
            responsive_row(ranking, access, sizing_mode="stretch_width"),
            note,
            sizing_mode="stretch_width",
            spacing=16,
        )
    )
    prepare_document(document, "/airport-access")
