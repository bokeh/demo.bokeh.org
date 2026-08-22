"""Explore CTrees biomass change through tile-aligned Icechunk overviews."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from functools import partial
from typing import Any, cast

import numpy as np
from bokeh.events import DocumentReady, Event, RangesUpdate, Tap
from bokeh.layouts import column
from bokeh.models import (
    BoxAnnotation,
    ColumnDataSource,
    CustomJS,
    Div,
    HoverTool,
    Range1d,
    RangeSlider,
    Select,
    Title,
    WheelZoomTool,
    WMTSTileSource,
)
from bokeh.plotting import figure
from bokeh.server.callbacks import TimeoutCallback

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

from . import cog, country_boundaries, icechunk_source
from .cog import BASELINE_YEAR, LATEST_YEAR, Bounds, ChangeQuery, bounds_around
from .color import (
    GAIN_HEX,
    GAIN_SOFT_HEX,
    LOSS_HEX,
    LOSS_SOFT_HEX,
    NEUTRAL_HEX,
    color_limits,
    rgba_image,
)
from .shading import (
    INITIAL_VISIBLE_TILES,
    MAX_TILE_ZOOM,
    TILE_SIZE,
    TILE_VERSION,
    WEB_MERCATOR_LIMIT,
    inverse_web_mercator,
    web_mercator,
)

QUERY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="biomass-query")
PRESETS = {
    "para": ("Pará, Brazil", -53.50, -6.50),
    "sabah": ("Sabah, Malaysia", 116.00, 5.50),
    "congo": ("Congo Basin", 20.25, 0.25),
    "oregon": ("Oregon Cascades", -122.25, 44.25),
    "sumatra": ("Sumatra, Indonesia", 101.50, -0.50),
}

KEEP_VISIBLE_TILES_JS = """
const source = renderer.tile_source
if (source.__biomass_descendant_fallback__ === true)
  return

const direct_children = source.children_by_tile_xyz.bind(source)
source.children_by_tile_xyz = function(x, y, z) {
  const children = direct_children(x, y, z)
  const direct_keys = new Set(
    children.map(([cx, cy, cz]) => this.tile_xyz_to_key(cx, cy, cz)),
  )
  const [nx, ny, nz] = this.normalize_xyz(x, y, z)
  const prefix = this.tile_xyz_to_quadkey(nx, ny, nz)
  const descendants = []

  for (const [key, tile] of this.tiles) {
    if (direct_keys.has(key) || tile.loaded !== true)
      continue
    const [cx, cy, cz] = this.key_to_tile_xyz(key)
    if (cz <= z + 1)
      continue
    const [ncx, ncy, ncz] = this.normalize_xyz(cx, cy, cz)
    if (ncz > nz && this.tile_xyz_to_quadkey(ncx, ncy, ncz).startsWith(prefix))
      descendants.push([cx, cy, cz, this.get_tile_meter_bounds(cx, cy, cz)])
  }

  descendants.sort((left, right) => left[2] - right[2])
  children.push(...descendants)
  return children
}
source.__biomass_descendant_fallback__ = true
"""


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


class BiomassExplorer:
    """Coordinate Bokeh models and nonblocking Icechunk overview queries."""

    def __init__(self, document, performance) -> None:
        self.document = document
        self.performance = performance
        self.detail_generation = 0
        self.last_detail_query: Future[ChangeQuery] | None = None
        self.last_boundary_query: Future[dict[str, list[list[float]]]] | None = None
        self.viewport_callback: TimeoutCallback | None = None
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
                "<p><strong>Preparing tile-aligned Icechunk detail…</strong><br>"
                "The selected footprint updates without a query button.</p>"
            ),
            name="biomass-query-status",
            styles={"padding": "14px", "background": PAPER, "border-left": f"4px solid {GOLD}"},
        )
        self.viewport_status = Div(
            text=(
                "<p><strong>Live Web Mercator tiles are ready.</strong><br>"
                "Pan or zoom to fetch only the visible 256 px tiles; released year changes "
                "replace the tile URL immediately.</p>"
            ),
            name="biomass-viewport-status",
            styles={"padding": "12px 14px", "background": PAPER},
        )

        self.before_card = metric(f"Mean biomass · {BASELINE_YEAR}", "…", accent=GOLD)
        self.after_card = metric(f"Mean biomass · {LATEST_YEAR}", "…", accent=GAIN_HEX)
        self.change_card = metric("Mean change", "…", accent=LOSS_HEX)
        self.pixel_card = metric("Comparable overview pixels", "…", accent=PLUM)

        default_bounds = self.bounds
        selection_west, selection_south, selection_east, selection_north = (
            self._web_mercator_bounds(default_bounds)
        )
        self.selection_halo = BoxAnnotation(
            left=selection_west,
            bottom=selection_south,
            right=selection_east,
            top=selection_north,
            fill_alpha=0,
            line_color=PLUM,
            line_alpha=0.9,
            line_width=7,
            name="biomass-selection-halo",
        )
        self.selection = BoxAnnotation(
            left=selection_west,
            bottom=selection_south,
            right=selection_east,
            top=selection_north,
            fill_color=GOLD,
            fill_alpha=0.08,
            line_color=PAPER,
            line_alpha=0.98,
            line_width=3,
            name="biomass-selection",
        )
        self.boundary_source = ColumnDataSource(
            data={"xs": [], "ys": []}, name="biomass-country-boundaries"
        )
        self.global_plot = self._build_global_plot()
        self._keep_visible_tiles_while_zooming()

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
        self.local_title = Title(text="Waiting for live overview pixels")
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
        self.histogram_note = Div(
            text=(
                "<p style='margin:0'><strong>How to read this:</strong> each bar counts comparable "
                "overview grid cells in a biomass-change interval. Orange is loss, cyan is gain, and "
                "the outer bins include more extreme values. Counts are not area-weighted.</p>"
            ),
            styles={"padding": "10px 14px", "background": PAPER, "color": "#6f686c"},
        )
        self.reading = Div(
            text="<p>Pixel-level losses and gains will appear after the live source query.</p>",
            name="biomass-reading",
            styles={"padding": "14px", "background": WARM, "border-left": f"4px solid {LOSS_HEX}"},
        )

        self.preset.on_change("value", self._choose_preset)
        self.years.on_change("value_throttled", self._years_changed)
        self.span.on_change("value", self._footprint_changed)
        self.global_plot.on_event(Tap, self._select_map_point)

    @property
    def bounds(self) -> Bounds:
        return bounds_around(self.center_longitude, self.center_latitude, float(self.span.value))

    @property
    def year_pair(self) -> tuple[int, int]:
        start_year, end_year = self.years.value
        return int(start_year), int(end_year)

    @staticmethod
    def _web_mercator_bounds(bounds: Bounds) -> Bounds:
        west, south, east, north = bounds
        x, y = web_mercator(np.array([west, east]), np.array([south, north]))
        return (float(x[0]), float(y[0]), float(x[1]), float(y[1]))

    def _tile_source(self) -> WMTSTileSource:
        start_year, end_year = self.year_pair
        return WMTSTileSource(
            url=(f"/biomass-tiles/{start_year}/{end_year}/{{Z}}/{{X}}/{{Y}}.webp?v={TILE_VERSION}"),
            tile_size=TILE_SIZE,
            initial_resolution=2 * WEB_MERCATOR_LIMIT / TILE_SIZE,
            min_zoom=0,
            max_zoom=MAX_TILE_ZOOM,
            wrap_around=True,
            attribution="CTrees Global Aboveground Biomass · Earthmover Arraylake",
        )

    def _keep_visible_tiles_while_zooming(self) -> None:
        """Retain any cached descendant level until zoomed-out tiles arrive."""
        fallback = CustomJS(
            args={"renderer": self.global_tile_renderer}, code=KEEP_VISIBLE_TILES_JS
        )
        self.global_tile_renderer.js_on_change("tile_source", fallback)
        self.document.js_on_event(DocumentReady, fallback)

    def _build_global_plot(self):
        start_year, end_year = self.year_pair
        self.global_title = Title(
            text=f"Live Web Mercator tiles · {start_year} → {end_year} · pan, zoom, or tap"
        )
        plot = figure(
            title=self.global_title,
            width=760,
            height=760,
            sizing_mode="scale_width",
            x_axis_type="mercator",
            y_axis_type="mercator",
            x_range=Range1d(
                start=-WEB_MERCATOR_LIMIT,
                end=WEB_MERCATOR_LIMIT,
                bounds=(-WEB_MERCATOR_LIMIT, WEB_MERCATOR_LIMIT),
            ),
            y_range=Range1d(
                start=-WEB_MERCATOR_LIMIT,
                end=WEB_MERCATOR_LIMIT,
                bounds=(-WEB_MERCATOR_LIMIT, WEB_MERCATOR_LIMIT),
            ),
            tools="tap,pan,wheel_zoom,reset",
            active_drag="pan",
            active_scroll="wheel_zoom",
            match_aspect=True,
            name="biomass-global-plot",
        )
        self.global_tile_renderer = plot.add_tile(
            self._tile_source(), render_parents=True, name="biomass-global-tiles"
        )
        plot.multi_line(
            xs="xs",
            ys="ys",
            source=self.boundary_source,
            line_color="#f6e8df",
            line_alpha=0.44,
            line_width=0.8,
        )
        plot.add_layout(self.selection_halo)
        plot.add_layout(self.selection)
        style_figure(plot)
        wheel_zoom = next(tool for tool in plot.tools if isinstance(tool, WheelZoomTool))
        wheel_zoom.speed = 0.0025
        plot.toolbar.active_scroll = wheel_zoom
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
            active_scroll="wheel_zoom",
            match_aspect=True,
            name="biomass-local-plot",
        )
        plot.image_rgba(image="image", x="x", y="y", dw="dw", dh="dh", source=self.local_source)
        style_figure(plot)
        wheel_zoom = next(tool for tool in plot.tools if isinstance(tool, WheelZoomTool))
        wheel_zoom.speed = 0.0025
        plot.toolbar.active_scroll = wheel_zoom
        plot.background_fill_color = PLUM
        plot.grid.grid_line_color = "#6b5862"
        plot.grid.grid_line_alpha = 0.34
        plot.xaxis.axis_label = "Longitude"
        plot.yaxis.axis_label = "Latitude"
        return plot

    def _build_histogram(self):
        plot = figure(
            title=Title(text="Distribution of overview-pixel change"),
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
        plot.yaxis.axis_label = "Comparable overview pixels"
        style_figure(plot)
        return plot

    def _location_text(self, label: str) -> str:
        return (
            f"<p style='margin:0'><strong>{label}</strong><br>"
            f"{self.center_latitude:+.2f}° latitude · {self.center_longitude:+.2f}° longitude<br>"
            "Pan or zoom to follow the viewport; tap for an exact point.</p>"
        )

    def _update_selection(self, label: str) -> None:
        west, south, east, north = self._web_mercator_bounds(self.bounds)
        self.selection_halo.update(left=west, bottom=south, right=east, top=north)
        self.selection.update(left=west, bottom=south, right=east, top=north)
        self.location.text = self._location_text(label)

    def _choose_preset(self, _attr: str, _old: object, new: str) -> None:
        if new == "custom":
            return
        label, longitude, latitude = PRESETS[new]
        self.center_longitude = longitude
        self.center_latitude = latitude
        self._update_selection(label)
        self._focus_global_plot(longitude, latitude)
        self._submit_detail_query()

    def _focus_global_plot(self, longitude: float, latitude: float) -> None:
        """Move the global plot to a preset-sized Web Mercator footprint."""
        west = min(max(longitude - 12, -180), 156)
        south = min(max(latitude - 6, -84), 72)
        x0, y0, x1, y1 = self._web_mercator_bounds((west, south, west + 24, south + 12))
        self.global_plot.x_range.update(start=x0, end=x1)
        self.global_plot.y_range.update(start=y0, end=y1)

    def _select_map_point(self, event: Event) -> None:
        if not isinstance(event, Tap) or event.x is None or event.y is None:
            return
        longitude, latitude = inverse_web_mercator(float(event.x), float(event.y))
        self.preset.value = "custom"
        self.center_longitude = round(float(np.clip(longitude, -179.5, 179.5)), 2)
        self.center_latitude = round(float(np.clip(latitude, -84.5, 84.5)), 2)
        self._update_selection("Custom map point")
        self._submit_detail_query()

    def _viewport_changed(self, event: Event) -> None:
        if not isinstance(event, RangesUpdate):
            return
        if self.viewport_callback is not None:
            with suppress(ValueError, RuntimeError):
                self.document.remove_timeout_callback(self.viewport_callback)
        self.viewport_callback = self.document.add_timeout_callback(
            self._sync_detail_to_viewport, 220
        )

    def _sync_detail_to_viewport(self) -> None:
        self.viewport_callback = None
        x_range = cast(Range1d, self.global_plot.x_range)
        y_range = cast(Range1d, self.global_plot.y_range)
        values = np.asarray(
            [x_range.start, x_range.end, y_range.start, y_range.end], dtype=np.float64
        )
        if not np.all(np.isfinite(values)) or values[0] >= values[1] or values[2] >= values[3]:
            return

        longitude, latitude = inverse_web_mercator(
            float((values[0] + values[1]) / 2), float((values[2] + values[3]) / 2)
        )
        longitude = float(np.clip(longitude, -179.5, 179.5))
        latitude = float(np.clip(latitude, -84.5, 84.5))
        if (
            abs(longitude - self.center_longitude) < 0.02
            and abs(latitude - self.center_latitude) < 0.02
        ):
            return

        self.preset.value = "custom"
        self.center_longitude = round(longitude, 2)
        self.center_latitude = round(latitude, 2)
        self._update_selection("Viewport center")
        self.viewport_status.text = (
            "<p><strong>Detail footprint followed the settled viewport.</strong><br>"
            "Its Icechunk overview query is updating at the new map center.</p>"
        )
        self._submit_detail_query()

    def _years_changed(self, _attr: str, _old: object, _new: object) -> None:
        start_year, end_year = self.year_pair
        self.status.text = (
            f"<p><strong>Updating detail · {start_year} → {end_year}</strong><br>"
            "The released year handles launch the query automatically.</p>"
        )
        self.global_tile_renderer.tile_source = self._tile_source()
        self.global_title.text = (
            f"Live Web Mercator tiles · {start_year} → {end_year} · pan, zoom, or tap"
        )
        self.viewport_status.text = (
            f"<p><strong>Visible tiles switched to {start_year} → {end_year}.</strong><br>"
            "The browser is fetching the new year-pair URL in parallel and reusing cached "
            "tiles where possible.</p>"
        )
        self._submit_detail_query()

    def _footprint_changed(self, _attr: str, _old: object, _new: object) -> None:
        self._update_selection(
            "Custom footprint" if self.preset.value == "custom" else PRESETS[self.preset.value][0]
        )
        self._submit_detail_query()

    def start(self) -> None:
        """Launch the initial detail and boundary queries after session startup."""
        boundary_query = QUERY_EXECUTOR.submit(country_boundaries.load_country_boundaries)
        self.last_boundary_query = boundary_query
        boundary_query.add_done_callback(self._boundary_query_finished)
        self._submit_detail_query()
        self.document.add_timeout_callback(self._activate_client_tiles, 750)

    def _activate_client_tiles(self) -> None:
        """Replace the construction-time source after the browser session is connected."""
        self.global_tile_renderer.tile_source = self._tile_source()
        self._focus_global_plot(self.center_longitude, self.center_latitude)
        self.document.add_timeout_callback(self._enable_viewport_sync, 250)

    def _enable_viewport_sync(self) -> None:
        """Subscribe only after the client has completed its initial range layout."""
        self.global_plot.on_event(RangesUpdate, self._viewport_changed)

    def _boundary_query_finished(self, future: Future[dict[str, list[list[float]]]]) -> None:
        try:
            data = future.result()
        except Exception:  # noqa: BLE001
            return
        with suppress(RuntimeError):
            self.document.add_next_tick_callback(partial(self._show_boundaries, data))

    def _show_boundaries(self, data: dict[str, list[list[float]]]) -> None:
        self.boundary_source.data = cast(Any, country_boundaries.project_boundaries(data))

    def _submit_detail_query(self) -> None:
        self.detail_generation += 1
        generation = self.detail_generation
        bounds = self.bounds
        start_year, end_year = self.year_pair
        if icechunk_source.configured():
            self.status.text = (
                f"<p><strong>Icechunk detail running · {start_year} → {end_year}</strong><br>"
                "Slicing the finest tile-aligned overview from the derived Arraylake repository.</p>"
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
        resolution = "z4 overview" if result.backend.startswith("Arraylake") else "100 m"
        self.local_title.text = (
            f"Live {resolution} change · {result.start_year} → {result.end_year} · "
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
            f"Read {source_megabytes:.1f} MB of tile-aligned overview values"
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
                "<p><strong>Pan or zoom</strong> to stream cached Web Mercator tiles and move "
                "the detail footprint to the settled viewport center. "
                "<strong>Release either year handle</strong> to compare a new pair immediately. "
                "<strong>Tap the map</strong> to choose an exact detail point.</p>"
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
                f"<span style='width:min(340px,45vw);height:12px;background:linear-gradient(90deg,{LOSS_HEX} 0%,{LOSS_SOFT_HEX} 43%,{NEUTRAL_HEX} 49%,{NEUTRAL_HEX} 51%,{GAIN_SOFT_HEX} 57%,{GAIN_HEX} 100%)'></span>"
                f"<strong style='color:{GAIN_HEX}'>cyan · biomass gain</strong></div>"
                "<p style='text-align:center;color:#6f686c;margin:6px 0 0'>Gray marks change within ±2 Mg/ha. Color ranges adapt to the selected interval; Web Mercator tiles retain equal x/y scale and are never stretched.</p>"
            )
        )
        note = Div(
            text=(
                "<p><strong>Data and method:</strong> CTrees Global Aboveground Biomass, annual "
                "100 m estimates for 2000-2025, scaled to Mg/ha (metric tonnes per hectare). "
                "A one-time build distills the source COG overviews into z0-z4, 1024 px "
                "WebMercatorQuad chunks in a dedicated Arraylake Icechunk repository. The live "
                "service exposes standard 256 px z0-z6 tiles by slicing those storage chunks, then "
                "subtracts, colors, and caches them by year pair and coordinate. Country "
                "outlines use Natural Earth 1:110m administrative boundaries projected to the same "
                "coordinate system. "
                "<a href='https://app.earthmover.io/marketplace/69e00e1c21faca8bf36879d2' target='_blank' rel='noreferrer'>"
                "Earthmover listing</a> · "
                "<a href='https://registry.opendata.aws/ctrees-agb-100m-global/' target='_blank' rel='noreferrer'>"
                "AWS Open Data registry</a> · "
                "<a href='https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/' target='_blank' rel='noreferrer'>"
                "Natural Earth boundaries</a> · "
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
                column(
                    self.reading, self.histogram, self.histogram_note, sizing_mode="stretch_width"
                ),
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
    document.template_variables["preload_images"] = [
        f"/biomass-tiles/{BASELINE_YEAR}/{LATEST_YEAR}/{zoom}/{column}/{row}.webp?v={TILE_VERSION}"
        for zoom, column, row in INITIAL_VISIBLE_TILES
    ]
    document.add_next_tick_callback(explorer.start)
