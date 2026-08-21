"""Explore live CTrees aboveground-biomass change through Icechunk and COGs."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import Any, cast

import numpy as np
from bokeh.events import Event, Tap
from bokeh.layouts import column
from bokeh.models import (
    BoxAnnotation,
    ColumnDataSource,
    Div,
    HoverTool,
    Range1d,
    RangeSlider,
    Select,
    Title,
)
from bokeh.plotting import figure

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
from apps._common.colors import GOLD, GRID, INK, PAPER, PLUM, WARM

from . import cog, icechunk_source
from .cog import BASELINE_YEAR, LATEST_YEAR, Bounds, ChangeQuery, bounds_around
from .shading import ViewportQuery, query_viewport

ASSETS = Path(__file__).parent
GLOBAL_NO_DATA = -128
GLOBAL_COLOR_LIMIT = 25.0
LOCAL_COLOR_LIMIT = 60.0
VIEWPORT_WIDTH = 900
VIEWPORT_HEIGHT = 450
COLOR_DEADBAND = 2.0
MIN_COLOR_STRENGTH = 0.55
LOSS_HEX = "#ff5a36"
GAIN_HEX = "#00c2e0"
NEUTRAL_HEX = "#6c6871"
LOSS = np.array([255, 90, 54], dtype=np.float32)
GAIN = np.array([0, 194, 224], dtype=np.float32)
NEUTRAL = np.array([108, 104, 113], dtype=np.float32)
QUERY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="biomass-query")
PRESETS = {
    "para": ("Pará, Brazil", -53.50, -6.50),
    "sabah": ("Sabah, Malaysia", 116.00, 5.50),
    "congo": ("Congo Basin", 20.25, 0.25),
    "oregon": ("Oregon Cascades", -122.25, 44.25),
    "sumatra": ("Sumatra, Indonesia", 101.50, -0.50),
}


def rgba_image(delta: np.ndarray, valid: np.ndarray, *, limit: float) -> np.ndarray:
    """Encode a colorblind-safe, high-contrast raster for ``image_rgba``."""
    absolute = np.abs(np.nan_to_num(delta))
    scaled = np.clip((absolute - COLOR_DEADBAND) / (limit - COLOR_DEADBAND), 0, 1)
    magnitude = np.where(
        absolute <= COLOR_DEADBAND,
        0,
        MIN_COLOR_STRENGTH + (1 - MIN_COLOR_STRENGTH) * np.sqrt(scaled),
    )[..., None]
    target = np.where((delta < 0)[..., None], LOSS, GAIN)
    rgb = NEUTRAL + (target - NEUTRAL) * magnitude
    rgba = np.empty((*delta.shape, 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, np.where(absolute <= COLOR_DEADBAND, 72, 245), 0).astype(
        np.uint8
    )
    return np.ascontiguousarray(np.flipud(rgba)).view(np.uint32).reshape(delta.shape)


def histogram_data(
    delta: np.ndarray, valid: np.ndarray, *, limit: float = 100
) -> dict[str, np.ndarray]:
    """Bin valid pixel changes into a compact, clipped distribution."""
    edges = np.linspace(-limit, limit, 41, dtype=np.float32)
    values = np.clip(delta[valid], edges[0], edges[-1])
    counts, _ = np.histogram(values, bins=edges)
    return {
        "left": edges[:-1],
        "right": edges[1:],
        "top": counts,
        "color": np.where(edges[:-1] < 0, LOSS_HEX, GAIN_HEX),
    }


def _global_image() -> np.ndarray:
    with np.load(ASSETS / "global_delta_2025.npz") as archive:
        values = archive["delta"]
    valid = values != GLOBAL_NO_DATA
    delta = np.where(valid, values, np.nan).astype(np.float32)
    return rgba_image(delta, valid, limit=GLOBAL_COLOR_LIMIT)


GLOBAL_IMAGE = _global_image()


def color_limits(start_year: int, end_year: int) -> tuple[float, float, float]:
    """Scale global, detail, and histogram ranges to the comparison interval."""
    years = max(abs(end_year - start_year), 1)
    return (
        max(5.0, GLOBAL_COLOR_LIMIT * years / 25),
        max(12.0, LOCAL_COLOR_LIMIT * years / 25),
        max(20.0, 100 * years / 25),
    )


class BiomassExplorer:
    """Coordinate Bokeh models and nonblocking Icechunk/COG queries."""

    def __init__(self, document, performance) -> None:
        self.document = document
        self.performance = performance
        self.detail_generation = 0
        self.viewport_generation = 0
        self.last_detail_query: Future[ChangeQuery] | None = None
        self.last_viewport_query: Future[ViewportQuery] | None = None
        self.viewport_callback = None
        self.center_longitude = -53.5
        self.center_latitude = -6.5

        preset_options = [(key, values[0]) for key, values in PRESETS.items()]
        self.preset = Select(
            title="Start somewhere interesting",
            value="para",
            options=[*preset_options, ("custom", "Custom map point")],
            name="biomass-preset",
        )
        self.years = RangeSlider(
            title="Comparison years",
            start=BASELINE_YEAR,
            end=LATEST_YEAR,
            step=1,
            value=(BASELINE_YEAR, LATEST_YEAR),
            name="biomass-years",
        )
        self.span = Select(
            title="Detail footprint around the selected point",
            value="0.5",
            options=[("0.25", "0.25° square"), ("0.5", "0.5° square"), ("1.0", "1° square")],
        )
        self.location = Div(
            text=self._location_text("Pará, Brazil"),
            name="biomass-location",
            styles={
                "padding": "12px 14px",
                "background": PAPER,
                "border-left": f"4px solid {GOLD}",
            },
        )
        self.status = Div(
            text=(
                "<p><strong>Preparing native 100 m detail…</strong><br>"
                "The selected footprint updates without a query button.</p>"
            ),
            name="biomass-query-status",
            styles={"padding": "14px", "background": PAPER, "border-left": f"4px solid {GOLD}"},
        )
        self.viewport_status = Div(
            text=(
                "<p><strong>Preparing live Datashader view…</strong><br>"
                "Pan or zoom to query the best cloud source for this scale.</p>"
            ),
            name="biomass-viewport-status",
            styles={"padding": "12px 14px", "background": PAPER},
        )

        self.before_card = metric(f"Mean biomass · {BASELINE_YEAR}", "…", accent=GOLD)
        self.after_card = metric(f"Mean biomass · {LATEST_YEAR}", "…", accent=GAIN_HEX)
        self.change_card = metric("Mean change", "…", accent=LOSS_HEX)
        self.pixel_card = metric("Live source pixels", "…", accent=PLUM)

        default_bounds = self.bounds
        self.selection = BoxAnnotation(
            left=default_bounds[0],
            bottom=default_bounds[1],
            right=default_bounds[2],
            top=default_bounds[3],
            fill_color=GOLD,
            fill_alpha=0.12,
            line_color=GOLD,
            line_width=2.5,
            name="biomass-selection",
        )
        self.global_source = ColumnDataSource(
            data={
                "image": [GLOBAL_IMAGE],
                "x": [-180.0],
                "y": [-90.0],
                "dw": [360.0],
                "dh": [180.0],
            },
            name="biomass-global-image",
        )
        self.global_plot = self._build_global_plot()

        empty = np.zeros((2, 2), dtype=np.uint32)
        self.local_source = ColumnDataSource(
            data={
                "image": [empty],
                "x": [default_bounds[0]],
                "y": [default_bounds[1]],
                "dw": [default_bounds[2] - default_bounds[0]],
                "dh": [default_bounds[3] - default_bounds[1]],
            },
            name="biomass-local-image",
        )
        self.local_title = Title(text="Waiting for live 100 m source pixels")
        self.local_plot = self._build_local_plot(default_bounds)
        self.histogram_source = ColumnDataSource(
            data={
                "left": np.linspace(-100, 95, 40),
                "right": np.linspace(-95, 100, 40),
                "top": np.zeros(40),
                "color": np.where(np.arange(40) < 20, LOSS_HEX, GAIN_HEX),
            },
            name="biomass-change-histogram",
        )
        self.histogram = self._build_histogram()
        self.reading = Div(
            text="<p>Pixel-level losses and gains will appear after the live source query.</p>",
            name="biomass-reading",
            styles={"padding": "14px", "background": WARM, "border-left": f"4px solid {LOSS_HEX}"},
        )

        self.preset.on_change("value", self._choose_preset)
        self.years.on_change("value_throttled", self._years_changed)
        self.span.on_change("value", self._footprint_changed)
        self.global_plot.on_event(Tap, self._select_map_point)
        for axis_range in (self.global_plot.x_range, self.global_plot.y_range):
            axis_range.on_change("start", self._viewport_changed)
            axis_range.on_change("end", self._viewport_changed)

    @property
    def bounds(self) -> Bounds:
        return bounds_around(self.center_longitude, self.center_latitude, float(self.span.value))

    @property
    def year_pair(self) -> tuple[int, int]:
        start_year, end_year = self.years.value
        return int(start_year), int(end_year)

    def _build_global_plot(self):
        self.global_title = Title(text="Live Datashader view · pan, zoom, or tap anywhere")
        plot = figure(
            title=self.global_title,
            height=520,
            sizing_mode="stretch_width",
            x_range=Range1d(start=-180, end=180, bounds=(-180, 180)),
            y_range=Range1d(start=-90, end=90, bounds=(-90, 90)),
            tools="tap,pan,wheel_zoom,reset",
            active_drag="pan",
            match_aspect=True,
            name="biomass-global-plot",
        )
        plot.image_rgba(image="image", x="x", y="y", dw="dw", dh="dh", source=self.global_source)
        plot.add_layout(self.selection)
        style_figure(plot)
        plot.background_fill_color = PLUM
        plot.grid.grid_line_color = "#6b5862"
        plot.grid.grid_line_alpha = 0.42
        plot.axis.axis_label_text_color = INK
        plot.xaxis.axis_label = "Longitude"
        plot.yaxis.axis_label = "Latitude"
        return plot

    def _build_local_plot(self, bounds: Bounds):
        plot = figure(
            title=self.local_title,
            height=500,
            sizing_mode="stretch_width",
            x_range=Range1d(start=bounds[0], end=bounds[2]),
            y_range=Range1d(start=bounds[1], end=bounds[3]),
            tools="pan,wheel_zoom,reset",
            active_drag="pan",
            match_aspect=True,
            name="biomass-local-plot",
        )
        plot.image_rgba(image="image", x="x", y="y", dw="dw", dh="dh", source=self.local_source)
        style_figure(plot)
        plot.background_fill_color = PLUM
        plot.grid.grid_line_color = "#6b5862"
        plot.grid.grid_line_alpha = 0.34
        plot.xaxis.axis_label = "Longitude"
        plot.yaxis.axis_label = "Latitude"
        return plot

    def _build_histogram(self):
        plot = figure(
            title=Title(text="Distribution of pixel change"),
            height=310,
            width=390,
            sizing_mode="stretch_width",
            x_range=Range1d(start=-100, end=100),
            tools="",
            toolbar_location=None,
            name="biomass-histogram-plot",
        )
        bars = plot.quad(
            left="left",
            right="right",
            bottom=0,
            top="top",
            fill_color="color",
            fill_alpha=0.86,
            line_color=PAPER,
            line_alpha=0.45,
            source=self.histogram_source,
        )
        plot.add_tools(
            HoverTool(
                renderers=[bars],
                tooltips=[("Change", "@left{0} to @right{0} Mg/ha"), ("Pixels", "@top{0,0}")],
            )
        )
        plot.xaxis.axis_label = "Change in aboveground biomass (Mg/ha)"
        plot.yaxis.axis_label = "Pixels"
        style_figure(plot)
        return plot

    def _location_text(self, label: str) -> str:
        return (
            f"<p style='margin:0'><strong>{label}</strong><br>"
            f"{self.center_latitude:+.2f}° latitude · {self.center_longitude:+.2f}° longitude<br>"
            "Tap the map to move the detail footprint.</p>"
        )

    def _update_selection(self, label: str) -> None:
        bounds = self.bounds
        self.selection.update(left=bounds[0], bottom=bounds[1], right=bounds[2], top=bounds[3])
        self.location.text = self._location_text(label)

    def _choose_preset(self, _attr: str, _old: object, new: str) -> None:
        if new == "custom":
            return
        label, longitude, latitude = PRESETS[new]
        self.center_longitude = longitude
        self.center_latitude = latitude
        self._update_selection(label)
        west = min(max(longitude - 12, -180), 156)
        south = min(max(latitude - 6, -90), 78)
        self.global_plot.x_range.update(start=west, end=west + 24)
        self.global_plot.y_range.update(start=south, end=south + 12)
        self._submit_detail_query()

    def _select_map_point(self, event: Event) -> None:
        if not isinstance(event, Tap) or event.x is None or event.y is None:
            return
        self.preset.value = "custom"
        self.center_longitude = round(float(np.clip(event.x, -179.5, 179.5)), 2)
        self.center_latitude = round(float(np.clip(event.y, -89.5, 89.5)), 2)
        self._update_selection("Custom map point")
        self._submit_detail_query()

    def _years_changed(self, _attr: str, _old: object, _new: object) -> None:
        start_year, end_year = self.year_pair
        self.status.text = (
            f"<p><strong>Updating detail · {start_year} → {end_year}</strong><br>"
            "The released year handles launch the query automatically.</p>"
        )
        self._submit_detail_query()
        self._schedule_viewport_query()

    def _footprint_changed(self, _attr: str, _old: object, _new: object) -> None:
        self._update_selection(
            "Custom footprint" if self.preset.value == "custom" else PRESETS[self.preset.value][0]
        )
        self._submit_detail_query()

    def _viewport_changed(self, _attr: str, _old: object, _new: object) -> None:
        self._schedule_viewport_query()

    def _schedule_viewport_query(self) -> None:
        if self.viewport_callback is not None:
            with suppress(ValueError, RuntimeError):
                self.document.remove_timeout_callback(self.viewport_callback)
        self.viewport_generation += 1
        generation = self.viewport_generation
        self.viewport_callback = self.document.add_timeout_callback(
            partial(self._submit_viewport_query, generation), 240
        )

    def _viewport_bounds(self) -> Bounds:
        x_range = cast(Range1d, self.global_plot.x_range)
        y_range = cast(Range1d, self.global_plot.y_range)
        west = max(float(cast(float, x_range.start)), -180)
        east = min(float(cast(float, x_range.end)), 180)
        south = max(float(cast(float, y_range.start)), -90)
        north = min(float(cast(float, y_range.end)), 90)
        if west >= east or south >= north:
            return (-180, -90, 180, 90)
        return (west, south, east, north)

    def start(self) -> None:
        """Launch the initial detail and viewport queries after session startup."""
        self._submit_detail_query()
        self.viewport_generation += 1
        self._submit_viewport_query(self.viewport_generation)

    def _submit_detail_query(self) -> None:
        self.detail_generation += 1
        generation = self.detail_generation
        bounds = self.bounds
        start_year, end_year = self.year_pair
        if icechunk_source.configured():
            self.status.text = (
                f"<p><strong>Icechunk detail running · {start_year} → {end_year}</strong><br>"
                "Slicing native 100 m chunks from the subscribed Arraylake repository.</p>"
            )
            query = icechunk_source.query_change
        else:
            self.status.text = (
                f"<p><strong>Public COG detail running · {start_year} → {end_year}</strong><br>"
                "Range-reading the native tiles that intersect the selected footprint.</p>"
            )
            query = cog.query_change
        future = QUERY_EXECUTOR.submit(query, start_year, end_year, bounds)
        self.last_detail_query = future
        future.add_done_callback(
            lambda completed: self._detail_query_finished(generation, completed)
        )

    def _detail_query_finished(self, generation: int, future: Future[ChangeQuery]) -> None:
        try:
            result = future.result()
        except Exception:  # noqa: BLE001
            callback = partial(self._show_detail_error, generation)
        else:
            callback = partial(self._show_detail_result, generation, result)
        with suppress(RuntimeError):
            self.document.add_next_tick_callback(callback)

    def _show_detail_error(self, generation: int) -> None:
        if generation != self.detail_generation:
            return
        self.status.text = (
            "<p><strong>The cloud dataset did not answer this query.</strong><br>"
            "Move the selection or year handles to retry automatically.</p>"
        )

    def _submit_viewport_query(self, generation: int) -> None:
        self.viewport_callback = None
        start_year, end_year = self.year_pair
        bounds = self._viewport_bounds()
        self.viewport_status.text = (
            f"<p><strong>Datashader rendering · {start_year} → {end_year}</strong><br>"
            "Selecting native Icechunk chunks or a matching COG overview for this scale.</p>"
        )
        future = QUERY_EXECUTOR.submit(
            query_viewport,
            start_year,
            end_year,
            bounds,
            plot_width=VIEWPORT_WIDTH,
            plot_height=VIEWPORT_HEIGHT,
        )
        self.last_viewport_query = future
        future.add_done_callback(
            lambda completed: self._viewport_query_finished(generation, completed)
        )

    def _viewport_query_finished(self, generation: int, future: Future[ViewportQuery]) -> None:
        try:
            result = future.result()
        except Exception:  # noqa: BLE001
            callback = partial(self._show_viewport_error, generation)
        else:
            callback = partial(self._show_viewport_result, generation, result)
        with suppress(RuntimeError):
            self.document.add_next_tick_callback(callback)

    def _show_viewport_error(self, generation: int) -> None:
        if generation != self.viewport_generation:
            return
        self.viewport_status.text = (
            "<p><strong>The live viewport did not render.</strong><br>"
            "Pan, zoom, or change years to retry; the previous view remains visible.</p>"
        )

    def _show_viewport_result(self, generation: int, result: ViewportQuery) -> None:
        if generation != self.viewport_generation:
            return
        self.performance.measure(self._apply_viewport_result, name="biomass-viewport-result")(
            result
        )

    def _apply_viewport_result(self, result: ViewportQuery) -> None:
        global_limit, _local_limit, _histogram_limit = color_limits(
            result.start_year, result.end_year
        )
        image = rgba_image(result.delta, result.valid, limit=global_limit)
        west, south, east, north = result.bounds
        self.global_source.data = {
            "image": [image],
            "x": [west],
            "y": [south],
            "dw": [east - west],
            "dh": [north - south],
        }
        self.global_title.text = (
            f"Live Datashader · {result.start_year} → {result.end_year} · {result.backend}"
        )
        source_megabytes = result.source_bytes / 1_000_000
        source_note = (
            f"materializing a {source_megabytes:.1f} MB native slice"
            if result.backend.startswith("Arraylake")
            else f"decoding {source_megabytes:.1f} MB from overview {result.overview_level}"
        )
        self.viewport_status.text = (
            f"<p><strong>Viewport rendered in {result.elapsed_seconds:.1f} s.</strong><br>"
            f"Datashader aggregated {result.source_pixels:,} source pixels after "
            f"{source_note} via {result.backend}.</p>"
        )

    @staticmethod
    def _mean(values: np.ndarray, valid: np.ndarray) -> float:
        return float(np.mean(values[valid], dtype=np.float64) / 10)

    def _show_detail_result(self, generation: int, result: ChangeQuery) -> None:
        if generation != self.detail_generation:
            return
        self.performance.measure(self._apply_detail_result, name="biomass-detail-result")(result)

    def _apply_detail_result(self, result: ChangeQuery) -> None:
        bounds = result.bounds
        _global_limit, local_limit, histogram_limit = color_limits(
            result.start_year, result.end_year
        )
        image = rgba_image(result.delta, result.valid, limit=local_limit)
        self.local_source.data = {
            "image": [image],
            "x": [bounds[0]],
            "y": [bounds[1]],
            "dw": [bounds[2] - bounds[0]],
            "dh": [bounds[3] - bounds[1]],
        }
        self.local_plot.x_range.update(
            start=bounds[0], end=bounds[2], reset_start=bounds[0], reset_end=bounds[2]
        )
        self.local_plot.y_range.update(
            start=bounds[1], end=bounds[3], reset_start=bounds[1], reset_end=bounds[3]
        )
        self.local_title.text = (
            f"Live 100 m change · {result.start_year} → {result.end_year} · "
            f"{self.center_latitude:+.2f}°, {self.center_longitude:+.2f}°"
        )
        self.histogram_source.data = cast(
            Any, histogram_data(result.delta, result.valid, limit=histogram_limit)
        )
        self.histogram.x_range.update(
            start=-histogram_limit,
            end=histogram_limit,
            reset_start=-histogram_limit,
            reset_end=histogram_limit,
        )

        if result.valid_pixels == 0:
            for card in (self.before_card, self.after_card, self.change_card, self.pixel_card):
                set_metric(card, "No modeled data")
            self.reading.text = (
                "<p><strong>No comparable land pixels were found.</strong><br>"
                "Move the selection onto a vegetated land area and query again.</p>"
            )
            self.status.text = (
                f"<p><strong>Live detail complete in {result.elapsed_seconds:.1f} s.</strong><br>"
                "The selected source tiles contained no comparable modeled pixels.</p>"
            )
            return

        before = self._mean(result.baseline, result.valid)
        after = self._mean(result.current, result.valid)
        change = float(np.mean(result.delta[result.valid], dtype=np.float64))
        threshold = max(2.0, abs(result.end_year - result.start_year) * 10 / 25)
        losing = float(np.mean(result.delta[result.valid] <= -threshold) * 100)
        gaining = float(np.mean(result.delta[result.valid] >= threshold) * 100)
        set_metric(
            self.before_card, f"{before:,.1f} Mg/ha", label=f"Mean biomass · {result.start_year}"
        )
        set_metric(
            self.after_card, f"{after:,.1f} Mg/ha", label=f"Mean biomass · {result.end_year}"
        )
        set_metric(
            self.change_card,
            f"{change:+,.1f} Mg/ha",
            label=f"Mean change · {result.start_year} → {result.end_year}",
        )
        set_metric(self.pixel_card, f"{result.valid_pixels:,}")
        direction = "gained" if change >= 0 else "lost"
        self.reading.text = (
            f"<p><strong>This footprint {direction} {abs(change):.1f} Mg/ha on average.</strong><br>"
            f"{losing:.1f}% of comparable pixels lost at least {threshold:.1f} Mg/ha; "
            f"{gaining:.1f}% gained at least {threshold:.1f} Mg/ha.</p>"
        )
        source_megabytes = result.source_bytes / 1_000_000
        source_note = (
            f"Materialized {source_megabytes:.1f} MB of native array data"
            if result.backend.startswith("Arraylake")
            else f"Decoded {source_megabytes:.1f} MB of compressed overview tiles"
        )
        self.status.text = (
            f"<p><strong>Live detail complete in {result.elapsed_seconds:.1f} s.</strong><br>"
            f"{source_note} via {result.backend}.</p>"
        )

    def layout(self):
        introduction = Div(
            text=(
                "<h2>Zoom from planet to pixels</h2>"
                "<p><strong>Pan or zoom</strong> to rerender from live cloud chunks. "
                "<strong>Release either year handle</strong> to compare a new pair immediately. "
                "<strong>Tap the map</strong> for native 100 m Icechunk detail.</p>"
            ),
            styles={"background": WARM},
        )
        controls = column(
            introduction,
            self.preset,
            self.location,
            self.years,
            self.span,
            self.viewport_status,
            self.status,
            width=320,
            sizing_mode="stretch_height",
            styles={"background": WARM, "padding": "20px", "border": f"1px solid {GRID}"},
        )
        match_background(controls, WARM)
        legend = Div(
            text=(
                "<div style='display:flex;align-items:center;gap:10px;justify-content:center'>"
                f"<strong style='color:{LOSS_HEX}'>orange · biomass loss</strong>"
                f"<span style='width:min(340px,45vw);height:12px;background:linear-gradient(90deg,{LOSS_HEX} 0%,{LOSS_HEX} 44%,{NEUTRAL_HEX} 44%,{NEUTRAL_HEX} 56%,{GAIN_HEX} 56%,{GAIN_HEX} 100%)'></span>"
                f"<strong style='color:{GAIN_HEX}'>cyan · biomass gain</strong></div>"
                "<p style='text-align:center;color:#6f686c;margin:6px 0 0'>Gray marks change within ±2 Mg/ha. Color ranges adapt to the selected interval; geographic pixels retain a 2:1 world aspect.</p>"
            )
        )
        note = Div(
            text=(
                "<p><strong>Data and method:</strong> CTrees Global Aboveground Biomass, annual "
                "100 m estimates for 2000-2025, scaled to Mg/ha. Native detail and close zooms slice "
                "the subscribed Arraylake Icechunk/Zarr cube; broad views use the same dataset's "
                "public COG overviews so a world pan never scans the 26 TB native array. Datashader "
                "aggregates to exactly 900 × 450 pixels without stretching the geographic extent. "
                "<a href='https://app.earthmover.io/marketplace/69e00e1c21faca8bf36879d2' target='_blank' rel='noreferrer'>"
                "Earthmover listing</a> · "
                "<a href='https://registry.opendata.aws/ctrees-agb-100m-global/' target='_blank' rel='noreferrer'>"
                "AWS Open Data registry</a> · "
                "<a href='https://doi.org/10.31223/X5KJ4Q' target='_blank' rel='noreferrer'>methodology</a></p>"
            )
        )
        return column(
            metric_row(
                self.before_card,
                self.after_card,
                self.change_card,
                self.pixel_card,
                sizing_mode="stretch_width",
            ),
            responsive_row(controls, self.global_plot, sizing_mode="stretch_width"),
            legend,
            responsive_row(
                self.local_plot,
                column(self.reading, self.histogram, sizing_mode="stretch_width"),
                sizing_mode="stretch_width",
            ),
            note,
            sizing_mode="stretch_width",
            spacing=16,
        )


def modify_document(document) -> None:
    performance = monitor_document(document, "/biomass-change")
    explorer = BiomassExplorer(document, performance)
    document.add_root(explorer.layout())
    prepare_document(document, "/biomass-change")
    document.add_next_tick_callback(explorer.start)
