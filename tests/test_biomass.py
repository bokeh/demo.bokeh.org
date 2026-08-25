"""Test the live CTrees biomass-change demo."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from types import SimpleNamespace

import numpy as np
import pytest
from bokeh.document import Document
from bokeh.models import (
    BoxAnnotation,
    ColumnDataSource,
    CustomJS,
    RangeSlider,
    TileRenderer,
    WheelZoomTool,
    WMTSTileSource,
)

from apps._common.performance import PerformanceMonitor
from apps.biomass import (
    BiomassExplorer,
    cog,
    country_boundaries,
    histogram_data,
    icechunk_source,
    rgba_image,
    shading,
)
from apps.biomass.cog import (
    ChangeQuery,
    Window,
    bounds_around,
    fit_bounds_to_aspect,
    overview_level_for,
)
from catalog import DEMOS, LISTED_DEMOS, load_applications
from scripts import build_biomass_overviews


def test_biomass_application_constructs_without_network_access() -> None:
    document = Document()
    load_applications()["/biomass-change"](document)

    local_image = document.select_one({"type": ColumnDataSource, "name": "biomass-local-image"})
    boundaries = document.select_one(
        {"type": ColumnDataSource, "name": "biomass-country-boundaries"}
    )
    selection = document.select_one({"type": BoxAnnotation, "name": "biomass-selection"})
    selection_halo = document.select_one({"type": BoxAnnotation, "name": "biomass-selection-halo"})
    years = document.select_one({"type": RangeSlider, "name": "biomass-years"})
    global_plot = document.select_one({"name": "biomass-global-plot"})
    local_plot = document.select_one({"name": "biomass-local-plot"})
    tiles = document.select_one({"type": TileRenderer, "name": "biomass-global-tiles"})

    assert isinstance(local_image, ColumnDataSource)
    assert isinstance(boundaries, ColumnDataSource)
    assert isinstance(selection, BoxAnnotation)
    assert isinstance(selection_halo, BoxAnnotation)
    assert isinstance(years, RangeSlider)
    assert isinstance(global_plot.toolbar.active_scroll, WheelZoomTool)
    assert isinstance(local_plot.toolbar.active_scroll, WheelZoomTool)
    assert isinstance(tiles, TileRenderer)
    assert isinstance(tiles.tile_source, WMTSTileSource)
    assert tiles.render_parents
    fallback = tiles.js_property_callbacks["change:tile_source"]
    assert len(fallback) == 1
    assert isinstance(fallback[0], CustomJS)
    assert fallback[0].args["renderer"] is tiles
    assert "for (const [key, tile] of this.tiles)" in fallback[0].code
    assert tiles.tile_source.url == (
        "/biomass-tiles/2000/2025/{Z}/{X}/{Y}.webp?v=icechunk-z4-pixel-aligned-v7"
    )
    assert tiles.tile_source.tile_size == shading.TILE_SIZE == 256
    assert tiles.tile_source.max_zoom == icechunk_source.DISPLAY_MAX_ZOOM == 12
    assert tiles.tile_source.initial_resolution == pytest.approx(
        2 * shading.WEB_MERCATOR_LIMIT / shading.TILE_SIZE
    )
    assert global_plot.width == global_plot.height == 760
    assert global_plot.toolbar.active_scroll.speed == pytest.approx(0.0025)
    assert local_plot.toolbar.active_scroll.speed == pytest.approx(0.0025)
    assert selection.line_color == "#fffdf9"
    assert selection.line_alpha == pytest.approx(0.98)
    assert selection.line_width == 3
    assert selection_halo.line_color == "#2a1723"
    assert selection_halo.line_alpha == pytest.approx(0.9)
    assert selection_halo.line_width == 7
    assert years.value == (2000, 2025)
    assert document.template_variables["preload_images"] == [
        f"/biomass-tiles/2000/2025/{zoom}/{column}/{row}.webp?v=icechunk-z4-pixel-aligned-v7"
        for zoom, column, row in shading.INITIAL_VISIBLE_TILES
    ]
    assert local_image.data["image"][0].shape == (2, 2)
    assert boundaries.data == {"xs": [], "ys": []}
    assert any(callback.callback.__name__ == "start" for callback in document.session_callbacks)


def test_biomass_application_is_not_listed() -> None:
    assert "/biomass-change" not in {demo.route for demo in LISTED_DEMOS}


def test_biomass_application_uses_wide_page_layout() -> None:
    biomass = next(demo for demo in DEMOS if demo.route == "/biomass-change")
    assert biomass.wide


def test_country_boundaries_extract_polygon_and_multipolygon_rings() -> None:
    collection = {
        "features": [
            {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]}},
            {"geometry": {"type": "MultiPolygon", "coordinates": [[[[2, 2], [3, 2], [2, 2]]]]}},
        ]
    }

    boundaries = country_boundaries._extract_boundaries(collection)

    assert boundaries == {
        "xs": [[0.0, 1.0, 0.0], [2.0, 3.0, 2.0]],
        "ys": [[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]],
    }


def test_country_boundaries_project_and_split_antimeridian_crossings() -> None:
    projected = country_boundaries.project_boundaries(
        {"xs": [[0.0, 1.0], [179.0, -179.0, -178.0]], "ys": [[0.0, 1.0], [5.0, 5.0, 6.0]]}
    )

    assert len(projected["xs"]) == 2
    assert projected["xs"][0][0] == pytest.approx(0)
    assert projected["ys"][0][0] == pytest.approx(0, abs=1e-6)
    assert len(projected["xs"][1]) == 2


def test_rgba_image_maps_loss_gain_and_missing_pixels() -> None:
    delta = np.array([[-25.0, -12.0, -3.0, 0.0, 3.0, 12.0, 25.0, np.nan]], dtype=np.float32)
    valid = np.array([[True, True, True, True, True, True, True, False]])
    packed = rgba_image(delta, valid, limit=25)
    rgba = np.flipud(packed).view(np.uint8).reshape(1, 8, 4)

    assert rgba[0, 0, 0] > rgba[0, 0, 1]
    assert rgba[0, 6, 2] > rgba[0, 6, 0]
    assert np.ptp(rgba[0, 3, :3]) < 10
    loss_distance = [
        np.linalg.norm(rgba[0, index, :3].astype(float) - rgba[0, 3, :3]) for index in (2, 1, 0)
    ]
    gain_distance = [
        np.linalg.norm(rgba[0, index, :3].astype(float) - rgba[0, 3, :3]) for index in (4, 5, 6)
    ]
    assert loss_distance[0] > 45
    assert gain_distance[0] > 45
    assert loss_distance == sorted(loss_distance)
    assert gain_distance == sorted(gain_distance)
    assert rgba[0, 3, 3] == 72
    assert rgba[0, 7, 3] == 0


def test_histogram_counts_only_comparable_pixels() -> None:
    delta = np.array([[-120, -12, -3, 2, 18, 140, np.nan]], dtype=np.float32)
    valid = np.isfinite(delta)
    data = histogram_data(delta, valid, limit=20)

    assert len(data["top"]) == 40
    assert int(data["top"].sum()) == 6
    assert data["left"][0] == -20
    assert data["right"][-1] == 20


def test_bounds_keep_fixed_footprint_inside_global_extent() -> None:
    assert bounds_around(-53.5, -6.5, 0.5) == (-53.75, -6.75, -53.25, -6.25)
    assert bounds_around(179.9, 89.9, 1) == (179.0, 89.0, 180.0, 90.0)


def test_viewport_bounds_expand_to_canvas_aspect_without_stretching() -> None:
    assert fit_bounds_to_aspect((-10, -10, 10, 10), 2) == (-20, -10, 20, 10)
    assert fit_bounds_to_aspect((170, 80, 180, 90), 2) == (160, 80, 180, 90)
    assert fit_bounds_to_aspect((-180, -90, 180, 90), 2) == (-180, -90, 180, 90)


def test_overview_level_tracks_visible_resolution() -> None:
    assert overview_level_for((-180, -90, 180, 90), 900, 450) == 8
    assert overview_level_for((-0.25, -0.25, 0.25, 0.25), 900, 450) == 0


def test_overview_builder_covers_every_tile_from_z0_through_z4() -> None:
    tasks = build_biomass_overviews._tasks(2025)
    finest = build_biomass_overviews._finest_tasks(2025)

    assert build_biomass_overviews.TILE_SIZE == 1024
    assert shading.TILE_SIZE == 256
    assert len(tasks) == sum(4**zoom for zoom in range(5)) == 341
    assert tasks[0] == (2025, 0, 0, 0)
    assert tasks[-1] == (2025, 4, 15, 15)
    assert len(finest) == 4**4
    assert finest[0] == (2025, 4, 0, 0)
    assert finest[-1] == (2025, 4, 15, 15)


def test_overview_builder_derives_coarse_pixels_without_spreading_fill() -> None:
    fill = build_biomass_overviews.FILL_VALUE
    values = np.array(
        [[0, 2, fill, fill], [2, 4, fill, 8], [10, 14, 20, 24], [fill, 18, 28, 32]], dtype=np.int16
    )

    reduced = build_biomass_overviews._downsample_2x(values, tile_size=2)

    np.testing.assert_array_equal(reduced, [[2, 8], [14, 26]])
    assert not reduced.flags.writeable


def test_overview_builder_accepts_resumable_year_ranges() -> None:
    assert build_biomass_overviews._parse_years("2000,2003:2005,2003") == [2000, 2003, 2004, 2005]
    with pytest.raises(argparse.ArgumentTypeError, match="years must be between"):
        build_biomass_overviews._parse_years("1999")


def test_cog_window_bounds_report_the_pixel_aligned_source_extent() -> None:
    page = SimpleNamespace(imagewidth=25_312, imagelength=12_656)
    requested = shading.tile_bounds(4, 5, 8)
    row_start, row_end, column_start, column_end = cog._pixel_window(page, requested)

    snapped = cog._window_bounds(page, row_start, row_end, column_start, column_end)

    assert snapped[0] == pytest.approx(requested[0])
    assert snapped[2] == pytest.approx(requested[2])
    assert snapped[1] <= requested[1]
    assert snapped[3] >= requested[3]
    assert requested[1] - snapped[1] < 180 / page.imagelength
    assert snapped[3] - requested[3] < 180 / page.imagelength


def test_overview_builder_projects_from_snapped_cog_bounds(monkeypatch) -> None:
    requested = shading.tile_bounds(4, 5, 8)
    snapped = (requested[0], requested[1] - 0.01, requested[2], requested[3] + 0.01)
    source = Window(values=np.ones((2, 2), dtype=np.int16), source_bytes=8, bounds=snapped)
    projected_from = []

    monkeypatch.setattr(build_biomass_overviews.cog, "read_year_window", lambda *_args: source)

    def rasterize(values, bounds, mercator_bounds, tile_size):
        projected_from.append((bounds, mercator_bounds, tile_size))
        return values.astype(np.float32), np.ones_like(values, dtype=bool)

    monkeypatch.setattr(build_biomass_overviews.shading, "rasterize_values", rasterize)

    tile = build_biomass_overviews._build_tile(2000, 4, 5, 8)

    assert projected_from == [(snapped, shading._tile_mercator_bounds(4, 5, 8), 1024)]
    np.testing.assert_array_equal(tile.values, source.values)


def test_rasterize_values_samples_exact_web_mercator_pixel_centres() -> None:
    page = SimpleNamespace(imagewidth=25_312, imagelength=12_656)
    requested = shading.tile_bounds(4, 4, 7)
    row_start, row_end, column_start, column_end = cog._pixel_window(page, requested)
    source_bounds = cog._window_bounds(page, row_start, row_end, column_start, column_end)
    rows = row_end - row_start
    north = source_bounds[3]
    south = source_bounds[1]
    source_latitude = np.linspace(
        north - (north - south) / (2 * rows), south + (north - south) / (2 * rows), rows
    )
    source = np.repeat((source_latitude >= 10).astype(np.float32)[:, None], 8, axis=1)

    raster, valid = shading.rasterize_values(
        source, source_bounds, shading._tile_mercator_bounds(4, 4, 7), tile_size=1024
    )

    mercator_north = shading._tile_mercator_bounds(4, 4, 7)[3]
    mercator_south = shading._tile_mercator_bounds(4, 4, 7)[1]
    target_y = np.linspace(
        mercator_north - (mercator_north - mercator_south) / 2048,
        mercator_south + (mercator_north - mercator_south) / 2048,
        1024,
    )
    target_latitude = np.degrees(
        2 * np.arctan(np.exp(target_y / shading.EARTH_RADIUS_M)) - np.pi / 2
    )
    expected = target_latitude >= 10
    np.testing.assert_array_equal(raster[:, 0], expected.astype(np.float32))
    assert valid.all()


def test_query_change_compares_scaled_source_values(monkeypatch) -> None:
    bounds = bounds_around(0, 0, 0.5)
    snapped_bounds = (-0.251, -0.252, 0.251, 0.252)
    baseline = np.array([[100, 200], [cog.NO_DATA, 400]], dtype=np.int16)
    current = np.array([[150, 170], [300, 400]], dtype=np.int16)

    def fake_window(year: int, _bounds, _overview_level: int) -> Window:
        values = baseline if year == 2000 else current
        return Window(values=values, source_bytes=123, bounds=snapped_bounds)

    monkeypatch.setattr(cog, "read_year_window", fake_window)
    result = cog.query_change(2000, 2025, bounds)

    assert result.valid_pixels == 3
    np.testing.assert_allclose(result.delta[result.valid], [5, -3, 0])
    assert np.isnan(result.delta[1, 0])
    assert result.source_bytes == 246
    assert result.bounds == snapped_bounds


def test_result_updates_detail_metrics_and_histogram() -> None:
    document = Document()
    explorer = BiomassExplorer(document, PerformanceMonitor("/biomass-change", enabled=False))
    baseline = np.array([[100, 200], [300, 400]], dtype=np.int16)
    current = np.array([[50, 300], [300, 500]], dtype=np.int16)
    valid = np.ones((2, 2), dtype=bool)
    delta = (current - baseline).astype(np.float32) / 10
    result = ChangeQuery(
        baseline=baseline,
        current=current,
        delta=delta,
        valid=valid,
        bounds=explorer.bounds,
        start_year=2000,
        end_year=2025,
        overview_level=0,
        source_bytes=4_200_000,
        elapsed_seconds=1.25,
    )

    explorer._apply_detail_result(result)

    assert "25.0 Mg/ha" in explorer.before_card.text
    assert "28.8 Mg/ha" in explorer.after_card.text
    assert "+3.8 Mg/ha" in explorer.change_card.text
    assert int(np.sum(explorer.histogram_source.data["top"])) == 4
    assert "4.2 MB" in explorer.status.text


def test_fallback_tile_returns_a_projected_png(monkeypatch) -> None:
    delta = np.arange(32, dtype=np.float32).reshape(4, 8)
    valid = np.ones_like(delta, dtype=bool)

    def fake_change(
        start_year: int, end_year: int, query_bounds, overview_level: int
    ) -> ChangeQuery:
        values = np.zeros_like(delta, dtype=np.int16)
        return ChangeQuery(
            baseline=values,
            current=values,
            delta=delta,
            valid=valid,
            bounds=query_bounds,
            start_year=start_year,
            end_year=end_year,
            overview_level=overview_level,
            source_bytes=512,
            elapsed_seconds=0.01,
        )

    monkeypatch.setattr(shading.icechunk_source, "configured", lambda: False)
    monkeypatch.setattr(shading.cog, "query_change", fake_change)
    shading.query_tile.cache_clear()
    result = shading.query_tile(2000, 2025, 1, 0, 0)

    assert result.image.startswith(b"RIFF")
    assert result.image[8:12] == b"WEBP"
    assert result.media_type == "image/webp"
    assert result.bounds[0] == -180
    assert result.bounds[1] == pytest.approx(0)
    assert result.bounds[2] == 0
    assert result.bounds[3] == pytest.approx(shading.WEB_MERCATOR_MAX_LATITUDE)
    assert result.source_pixels == 32
    assert result.source_bytes == 512
    assert result.zoom == 1
    assert result.column == 0
    assert result.row == 0
    shading.query_tile.cache_clear()


def test_configured_tile_uses_precomputed_icechunk_pixels(monkeypatch) -> None:
    delta = np.array([[-4.0, 0.0], [3.0, np.nan]], dtype=np.float32)
    valid = np.isfinite(delta)

    def fake_tile_change(
        start_year: int, end_year: int, zoom: int, column: int, row: int
    ) -> icechunk_source.TileChange:
        assert (start_year, end_year, zoom, column, row) == (2000, 2025, 1, 0, 0)
        return icechunk_source.TileChange(
            delta=delta,
            valid=valid,
            source_bytes=16,
            source_pixels=3,
            source_zoom=1,
            backend="Arraylake Icechunk · precomputed Web Mercator z1",
        )

    monkeypatch.setattr(shading.icechunk_source, "configured", lambda: True)
    monkeypatch.setattr(shading.icechunk_source, "query_tile_change", fake_tile_change)
    shading.query_tile.cache_clear()
    result = shading.query_tile(2000, 2025, 1, 0, 0)

    assert result.image.startswith(b"RIFF")
    assert result.image[8:12] == b"WEBP"
    assert result.media_type == "image/webp"
    assert result.source_bytes == 16
    assert result.source_pixels == 3
    assert result.backend.endswith("precomputed Web Mercator z1")
    shading.query_tile.cache_clear()


def test_initial_tile_warmup_covers_first_view_and_world_reset(monkeypatch) -> None:
    requested: list[tuple[int, int, int, int, int]] = []
    monkeypatch.setattr(shading.icechunk_source, "configured", lambda: True)
    monkeypatch.setattr(
        shading,
        "query_tile",
        lambda start, end, zoom, column, row: requested.append((start, end, zoom, column, row)),
    )

    elapsed = shading.warm_initial_tiles()

    assert elapsed is not None
    assert set(requested) == {
        (2000, 2025, zoom, column, row)
        for zoom, column, row in (*shading.INITIAL_WARM_TILES, *shading.WORLD_WARM_TILES)
    }


def test_web_mercator_tile_bounds_and_projection_round_trip() -> None:
    assert shading.tile_bounds(0, 0, 0) == pytest.approx(
        (-180, -shading.WEB_MERCATOR_MAX_LATITUDE, 180, shading.WEB_MERCATOR_MAX_LATITUDE)
    )
    x, y = shading.web_mercator(np.array([-53.5]), np.array([-6.5]))
    longitude, latitude = shading.inverse_web_mercator(float(x[0]), float(y[0]))
    assert longitude == pytest.approx(-53.5)
    assert latitude == pytest.approx(-6.5)


def test_client_tile_activation_focuses_the_selected_initial_preset() -> None:
    document = Document()
    explorer = BiomassExplorer(document, PerformanceMonitor("/biomass-change", enabled=False))
    construction_source = explorer.global_tile_renderer.tile_source

    explorer._activate_client_tiles()

    assert explorer.global_tile_renderer.tile_source is not construction_source
    expected = explorer._web_mercator_bounds((-65.5, -12.5, -41.5, -0.5))
    assert explorer.global_plot.x_range.start == pytest.approx(expected[0])
    assert explorer.global_plot.x_range.end == pytest.approx(expected[2])
    assert explorer.global_plot.y_range.start == pytest.approx(expected[1])
    assert explorer.global_plot.y_range.end == pytest.approx(expected[3])
    assert any(
        callback.callback.__name__ == "_enable_viewport_sync"
        for callback in document.session_callbacks
    )


def test_viewport_center_updates_detail_selection(monkeypatch) -> None:
    document = Document()
    explorer = BiomassExplorer(document, PerformanceMonitor("/biomass-change", enabled=False))
    requested_bounds = []
    monkeypatch.setattr(
        explorer, "_submit_detail_query", lambda: requested_bounds.append(explorer.bounds)
    )
    x, y = shading.web_mercator(np.array([-122.25]), np.array([44.25]))
    explorer.global_plot.x_range.update(start=float(x[0] - 1_000), end=float(x[0] + 1_000))
    explorer.global_plot.y_range.update(start=float(y[0] - 1_000), end=float(y[0] + 1_000))

    explorer._sync_detail_to_viewport()

    assert explorer.preset.value == "custom"
    assert explorer.center_longitude == pytest.approx(-122.25, abs=0.01)
    assert explorer.center_latitude == pytest.approx(44.25, abs=0.01)
    assert requested_bounds == [explorer.bounds]
    assert "Viewport center" in explorer.location.text
    selection_bounds = explorer._web_mercator_bounds(explorer.bounds)
    assert explorer.selection.left == pytest.approx(selection_bounds[0])
    assert explorer.selection.bottom == pytest.approx(selection_bounds[1])
    assert explorer.selection.right == pytest.approx(selection_bounds[2])
    assert explorer.selection.top == pytest.approx(selection_bounds[3])
    assert explorer.selection_halo.left == pytest.approx(selection_bounds[0])
    assert explorer.selection_halo.bottom == pytest.approx(selection_bounds[1])
    assert explorer.selection_halo.right == pytest.approx(selection_bounds[2])
    assert explorer.selection_halo.top == pytest.approx(selection_bounds[3])


def test_viewport_center_does_not_repeat_unchanged_detail_query(monkeypatch) -> None:
    document = Document()
    explorer = BiomassExplorer(document, PerformanceMonitor("/biomass-change", enabled=False))
    requested_bounds = []
    monkeypatch.setattr(
        explorer, "_submit_detail_query", lambda: requested_bounds.append(explorer.bounds)
    )
    x, y = shading.web_mercator(
        np.array([explorer.center_longitude]), np.array([explorer.center_latitude])
    )
    explorer.global_plot.x_range.update(start=float(x[0] - 1_000), end=float(x[0] + 1_000))
    explorer.global_plot.y_range.update(start=float(y[0] - 1_000), end=float(y[0] + 1_000))

    explorer._sync_detail_to_viewport()

    assert explorer.preset.value == "para"
    assert requested_bounds == []


def test_icechunk_tile_slices_map_display_z6_into_storage_z4() -> None:
    source_zoom, source_column, source_row, rows, columns, scale = icechunk_source._tile_slices(
        6, 20, 33
    )

    assert (source_zoom, source_column, source_row, scale) == (4, 5, 8, 4)
    assert rows == slice(256, 512)
    assert columns == slice(0, 256)


def test_icechunk_tile_slices_map_high_display_zooms_into_storage_z4() -> None:
    assert icechunk_source._tile_slices(12, 0, 0) == (4, 0, 0, slice(0, 4), slice(0, 4), 256)


def test_icechunk_tile_slices_map_low_display_zooms_into_storage_z0() -> None:
    assert icechunk_source._tile_slices(0, 0, 0) == (0, 0, 0, slice(0, 1024), slice(0, 1024), 1)
    assert icechunk_source._tile_slices(1, 1, 0) == (0, 0, 0, slice(0, 512), slice(512, 1024), 2)
    assert icechunk_source._tile_slices(2, 3, 2) == (0, 0, 0, slice(512, 768), slice(768, 1024), 4)


def test_icechunk_storage_window_reduces_to_standard_display_tile() -> None:
    values = np.full((512, 512), 10, dtype=np.int16)
    values[0:2, 0:2] = np.array([[10, 20], [icechunk_source.FILL_VALUE] * 2])

    resized = icechunk_source._resize_display_tile(values)

    assert resized.shape == (256, 256)
    assert resized.dtype == np.int16
    assert resized[0, 0] == 15
    assert np.all(resized[1:, 1:] == 10)


def test_icechunk_detail_bounds_map_into_web_mercator_overview() -> None:
    rows, columns = icechunk_source._mercator_pixel_window((-0.5, -0.5, 0.5, 0.5))

    assert 0 <= rows.start < rows.stop <= 16_384
    assert 0 <= columns.start < columns.stop <= 16_384
    assert rows.stop - rows.start == pytest.approx(columns.stop - columns.start, abs=2)


def test_icechunk_repository_initialization_is_single_flight(monkeypatch) -> None:
    icechunk_source._reset_caches_for_testing()
    opened: list[object] = []
    expected = object()

    def fake_open() -> object:
        opened.append(expected)
        sleep(0.05)
        return expected

    monkeypatch.setattr(icechunk_source, "_open_root", fake_open)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(icechunk_source._root) for _ in range(2)]

    assert [future.result() for future in futures] == [expected, expected]
    assert opened == [expected]
    icechunk_source._reset_caches_for_testing()


def test_icechunk_startup_warms_only_the_initial_detail_pair(monkeypatch) -> None:
    requested_years: list[int] = []

    class Array:
        def __getitem__(self, key) -> np.ndarray:
            requested_years.append(int(key[0]) + icechunk_source.BASELINE_YEAR)
            return np.ones((2, 2), dtype=np.int16)

    monkeypatch.setattr(icechunk_source, "configured", lambda: True)
    monkeypatch.setattr(icechunk_source, "_root", lambda: {"agb": {"z4": Array()}})
    monkeypatch.setattr(
        icechunk_source, "_mercator_pixel_window", lambda _bounds: (slice(0, 2), slice(0, 2))
    )
    icechunk_source.read_year_window.cache_clear()

    elapsed = icechunk_source.warm_default_windows()

    assert elapsed is not None
    assert sorted(requested_years) == [icechunk_source.BASELINE_YEAR, icechunk_source.LATEST_YEAR]
    assert icechunk_source.read_year_window.cache_info().currsize == 2

    icechunk_source.query_change(2007, 2019, icechunk_source.DEFAULT_DETAIL_BOUNDS)
    assert len(requested_years) == 4
    icechunk_source.read_year_window.cache_clear()


def test_icechunk_query_compares_precomputed_overview_values(monkeypatch) -> None:
    bounds = bounds_around(0, 0, 0.5)
    baseline = np.array([[100, 200], [icechunk_source.NO_DATA, 400]], dtype=np.int16)
    current = np.array([[150, 170], [300, 400]], dtype=np.int16)

    def fake_window(year: int, _bounds) -> Window:
        values = baseline if year == 2000 else current
        return Window(values=values, source_bytes=values.nbytes)

    monkeypatch.setattr(icechunk_source, "read_year_window", fake_window)
    result = icechunk_source.query_change(2000, 2025, bounds)

    assert result.backend == "Arraylake Icechunk · precomputed Web Mercator (~2.4 km at equator)"
    assert result.valid_pixels == 3
    np.testing.assert_allclose(result.delta[result.valid], [5, -3, 0])
    assert np.isnan(result.delta[1, 0])
    assert result.source_bytes == 16
