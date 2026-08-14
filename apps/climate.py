"""Explore Seattle weather trends with linked seasonal views."""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd
from bokeh.layouts import column
from bokeh.models import (
    ColorBar,
    ColumnDataSource,
    Div,
    FactorRange,
    HoverTool,
    Label,
    LinearAxis,
    LinearColorMapper,
    Range1d,
    Select,
    Slider,
    Span,
)
from bokeh.plotting import figure
from bokeh.transform import transform
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
from apps._common.colors import CORAL, GOLD, GRID, PAPER, TEAL, VIOLET, WARM

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
YEARS = [2012, 2013, 2014, 2015]
RAIN_PALETTE = ["#f7f3ec", "#d8d2bd", "#a9b9aa", "#6d9792", "#4f7b7c", "#2a1723"]


def modify_document(document) -> None:
    frame = cast(pd.DataFrame, local_data.seattle_weather()).copy()
    frame["year"] = frame["date"].dt.year
    frame["day"] = [date.replace(year=2000).dayofyear for date in frame["date"]]
    frame["month"] = frame["date"].dt.month

    normal = cast(
        pd.DataFrame,
        frame.groupby("day")
        .agg(
            normal_max=("temp_max", "mean"),
            normal_min=("temp_min", "mean"),
            record_max=("temp_max", "max"),
            record_min=("temp_min", "min"),
            normal_rain=("precipitation", "mean"),
        )
        .reindex(range(1, 367))
        .interpolate(limit_direction="both"),
    )
    normal["rolling_rain"] = normal["normal_rain"].rolling(30, min_periods=1).sum()
    annual_rain = frame.groupby("year")["precipitation"].sum()

    monthly = (
        frame.groupby(["year", "month"])
        .agg(
            rain=("precipitation", "sum"),
            mean_high=("temp_max", "mean"),
            wet_days=("precipitation", lambda values: int(np.sum(values > 0))),
        )
        .reset_index()
    )
    monthly["month_name"] = [MONTHS[index - 1] for index in monthly["month"]]
    monthly["year_name"] = monthly["year"].astype(str)

    year = Select(title="Year to inspect", value="2015", options=[str(value) for value in YEARS])
    smoothing = Slider(title="Temperature smoothing (days)", start=1, end=30, value=7, step=1)
    heavy_rain = Slider(title="Heavy-rain threshold (mm)", start=5, end=30, value=15, step=1)

    weather_source = ColumnDataSource(data={}, name="weather-selected-year")
    normal_source = ColumnDataSource(
        data={
            "day": normal.index.to_numpy(),
            **{column: normal[column].to_numpy() for column in normal.columns},
        },
        name="weather-four-year-normal",
    )
    monthly_source = ColumnDataSource(
        data={
            "month": monthly["month_name"].to_list(),
            "year": monthly["year_name"].to_list(),
            "rain": monthly["rain"].to_list(),
            "mean_high": monthly["mean_high"].to_list(),
            "wet_days": monthly["wet_days"].to_list(),
            "outline": [PAPER] * len(monthly),
            "outline_width": [0.75] * len(monthly),
        },
        name="weather-monthly-comparison",
    )

    high_card = metric("Highest temperature", "...", accent=CORAL)
    rain_card = metric("Annual precipitation vs average", "...", accent=TEAL)
    heavy_card = metric("Heavy-rain days", "...", accent=GOLD)
    dry_card = metric("Longest dry spell", "...", accent=VIOLET)

    temperature = figure(
        name="weather-temperature-plot",
        height=410,
        sizing_mode="stretch_width",
        x_range=Range1d(start=1, end=366),
        tools="xpan,xwheel_zoom,reset",
        active_scroll=None,
    )
    temperature.varea(
        x="day",
        y1="record_min",
        y2="record_max",
        source=normal_source,
        fill_color=VIOLET,
        fill_alpha=0.08,
        legend_label="Observed 2012 to 2015 envelope",
    )
    temperature.line(
        "day",
        "normal_max",
        source=normal_source,
        color=VIOLET,
        line_dash="dashed",
        line_width=1.8,
        line_alpha=0.72,
        legend_label="Four-year mean high and low",
    )
    temperature.line(
        "day",
        "normal_min",
        source=normal_source,
        color=VIOLET,
        line_dash="dashed",
        line_width=1.8,
        line_alpha=0.72,
        legend_label="Four-year mean high and low",
    )
    temperature.varea(
        x="day",
        y1="temp_min",
        y2="temp_max",
        source=weather_source,
        fill_color=GOLD,
        fill_alpha=0.18,
        legend_label="Selected daily range",
    )
    temperature.line(
        "day",
        "smooth_max",
        source=weather_source,
        color=CORAL,
        line_width=3,
        legend_label="Selected smoothed high",
    )
    temperature.line(
        "day",
        "smooth_min",
        source=weather_source,
        color=TEAL,
        line_width=3,
        legend_label="Selected smoothed low",
    )
    temperature.add_tools(
        HoverTool(
            tooltips=[
                ("Date", "@date{%F}"),
                ("High", "@temp_max{0.0} °C"),
                ("Low", "@temp_min{0.0} °C"),
                ("Weather", "@weather"),
            ],
            formatters={"@date": "datetime"},
            mode="vline",
        )
    )
    temperature.yaxis.axis_label = "Temperature (°C)"
    temperature.legend.location = "top_left"
    temperature.legend.orientation = "horizontal"
    temperature.legend.click_policy = "hide"
    temperature.legend.label_text_font_size = "10px"
    style_figure(temperature)

    max_rolling_rain = max(
        frame.loc[frame["year"] == selected_year, "precipitation"]
        .rolling(30, min_periods=1)
        .sum()
        .max()
        for selected_year in YEARS
    )
    precipitation = figure(
        name="weather-rainfall-plot",
        height=285,
        sizing_mode="stretch_width",
        x_range=temperature.x_range,
        y_range=Range1d(start=0, end=max(30, float(frame["precipitation"].max()) * 1.12)),
        extra_y_ranges={"rolling": Range1d(start=0, end=float(max_rolling_rain) * 1.12)},
        toolbar_location=None,
    )
    rain_bars = precipitation.vbar(
        x="day", top="precipitation", source=weather_source, width=1, color="rain_color", alpha=0.78
    )
    precipitation.line(
        "day",
        "rolling_rain",
        source=weather_source,
        y_range_name="rolling",
        color=CORAL,
        line_width=2.5,
        legend_label="Selected 30-day total",
    )
    precipitation.line(
        "day",
        "rolling_rain",
        source=normal_source,
        y_range_name="rolling",
        color=VIOLET,
        line_dash="dashed",
        line_width=2.2,
        legend_label="Four-year mean 30-day total",
    )
    precipitation.add_layout(
        LinearAxis(y_range_name="rolling", axis_label="30-day total (mm)"), "right"
    )
    threshold_span = Span(
        name="weather-heavy-rain-threshold",
        location=heavy_rain.value,
        dimension="width",
        line_color=GOLD,
        line_dash="dashed",
        line_width=2,
    )
    threshold_label = Label(
        name="weather-heavy-rain-label",
        x=360,
        y=heavy_rain.value,
        y_offset=5,
        text=f"{heavy_rain.value:.0f} mm threshold",
        text_align="right",
        text_color=GOLD,
        text_font_size="10px",
        background_fill_color=PAPER,
        background_fill_alpha=0.88,
    )
    precipitation.add_layout(threshold_span)
    precipitation.add_layout(threshold_label)
    precipitation.add_tools(
        HoverTool(
            renderers=[rain_bars],
            tooltips=[("Date", "@date{%F}"), ("Precipitation", "@precipitation{0.0} mm")],
            formatters={"@date": "datetime"},
        )
    )
    precipitation.xaxis.axis_label = "Day of year"
    precipitation.yaxis[0].axis_label = "Daily precipitation (mm)"
    precipitation.legend.location = "top_left"
    precipitation.legend.orientation = "horizontal"
    precipitation.legend.label_text_font_size = "10px"
    style_figure(precipitation)

    mapper = LinearColorMapper(
        palette=RAIN_PALETTE, low=0, high=float(monthly["rain"].max()), nan_color=PAPER
    )
    monthly_plot = figure(
        name="weather-monthly-plot",
        height=285,
        width=500,
        x_range=FactorRange(factors=MONTHS),
        y_range=FactorRange(factors=[str(value) for value in reversed(YEARS)]),
        toolbar_location=None,
        title="Monthly rainfall across all four years",
    )
    month_cells = monthly_plot.rect(
        x="month",
        y="year",
        width=0.94,
        height=0.88,
        source=monthly_source,
        fill_color=transform("rain", mapper),
        line_color="outline",
        line_width="outline_width",
    )
    monthly_plot.add_tools(
        HoverTool(
            renderers=[month_cells],
            tooltips=[
                ("Month", "@month @year"),
                ("Precipitation", "@rain{0.0} mm"),
                ("Mean high", "@mean_high{0.0} °C"),
                ("Wet days", "@wet_days"),
            ],
        )
    )
    monthly_plot.add_layout(ColorBar(color_mapper=mapper, title="mm", width=9), "right")
    monthly_plot.xaxis.axis_label = "Month"
    monthly_plot.yaxis.axis_label = "Year"
    monthly_plot.grid.visible = False
    style_figure(monthly_plot)

    year_summary = Div(name="weather-year-summary")

    def moving_average(values: np.ndarray, width: int) -> np.ndarray:
        padded = np.pad(values, (width - 1, 0), mode="edge")
        return np.convolve(padded, np.ones(width) / width, mode="valid")

    def longest_dry_spell(precipitation_values: np.ndarray) -> int:
        longest = 0
        current = 0
        for value in precipitation_values:
            if value == 0:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        return longest

    def calculate() -> None:
        selected_year = int(year.value)
        selected = frame.loc[frame["year"] == selected_year].copy()
        width = int(smoothing.value)
        threshold = float(heavy_rain.value)
        threshold_span.location = threshold
        threshold_label.y = threshold
        threshold_label.text = f"{threshold:.0f} mm threshold"
        precipitation_values = selected["precipitation"].to_numpy()
        selected["rolling_rain"] = selected["precipitation"].rolling(30, min_periods=1).sum()
        selected["rain_color"] = np.where(selected["precipitation"] >= threshold, CORAL, TEAL)
        weather_source.data = {
            "date": selected["date"].to_numpy(),
            "day": selected["day"].to_numpy(),
            "temp_max": selected["temp_max"].to_numpy(),
            "temp_min": selected["temp_min"].to_numpy(),
            "smooth_max": moving_average(selected["temp_max"].to_numpy(), width),
            "smooth_min": moving_average(selected["temp_min"].to_numpy(), width),
            "precipitation": precipitation_values,
            "rolling_rain": selected["rolling_rain"].to_numpy(),
            "rain_color": selected["rain_color"].to_numpy(),
            "weather": selected["weather"].to_numpy(),
        }

        outlines = [CORAL if value == year.value else PAPER for value in monthly["year_name"]]
        monthly_source.data = {
            **monthly_source.data,
            "outline": outlines,
            "outline_width": [
                1.5 if value == year.value else 0.75 for value in monthly["year_name"]
            ],
        }

        total_rain = float(selected["precipitation"].sum())
        rain_delta = total_rain / float(annual_rain.mean()) - 1
        heavy_days = int(np.sum(precipitation_values >= threshold))
        average_heavy_days = (
            frame.groupby("year")["precipitation"]
            .apply(lambda values: np.sum(values >= threshold))
            .mean()
        )
        dry_spell = longest_dry_spell(precipitation_values)
        wettest_month_number = int(selected.groupby("month")["precipitation"].sum().idxmax())

        set_metric(high_card, f"{selected['temp_max'].max():.1f} °C")
        set_metric(rain_card, f"{total_rain:.0f} mm · {rain_delta:+.0%}")
        set_metric(
            heavy_card,
            f"{heavy_days} · avg {average_heavy_days:.1f}",
            label=f"Days at or above {threshold:.0f} mm",
        )
        set_metric(dry_card, f"{dry_spell} days")
        direction = "above" if rain_delta >= 0 else "below"
        year_summary.text = (
            f"<p><strong>{selected_year}:</strong> total precipitation was {abs(rain_delta):.0%} {direction} "
            f"the four-year annual average. {MONTHS[wettest_month_number - 1]} was the wettest month, and the "
            f"longest run without recorded precipitation lasted {dry_spell} days. {heavy_days} days met or "
            f"exceeded the {threshold:.0f} mm threshold; the yearly average was {average_heavy_days:.1f}.</p>"
        )

    def update(_attr: str, _old: object, _new: object) -> None:
        calculate()

    year.on_change("value", update)
    smoothing.on_change("value", update)
    heavy_rain.on_change("value", update)
    calculate()

    attribution = Div(
        text=(
            "<p><strong>Data:</strong> public-domain NOAA observations for Seattle from 2012 to 2015, "
            "distributed by Vega Datasets. Four years is enough for comparison here, but not a climate normal.</p>"
        )
    )
    controls = column(
        Div(
            text=(
                "<h2>Compare four years of Seattle weather</h2>"
                "<p>Set one year against the available 2012 to 2015 observations. Adjust the temperature smoothing or choose what "
                "counts as heavy rain; Python recomputes the event counts, rolling rainfall, and year summary.</p>"
            )
        ),
        year,
        smoothing,
        heavy_rain,
        year_summary,
        width=330,
        sizing_mode="stretch_height",
        styles={"background": WARM, "padding": "20px", "border": f"1px solid {GRID}"},
    )
    match_background(controls, WARM)
    document.add_root(
        column(
            metric_row(high_card, rain_card, heavy_card, dry_card, sizing_mode="stretch_width"),
            responsive_row(controls, temperature, sizing_mode="stretch_width"),
            responsive_row(precipitation, monthly_plot, sizing_mode="stretch_width"),
            attribution,
            sizing_mode="stretch_width",
            spacing=16,
        )
    )
    prepare_document(document, "/climate")
