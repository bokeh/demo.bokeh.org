"""Test the live CTrees biomass-change demo."""

from __future__ import annotations

import numpy as np
from bokeh.document import Document
from bokeh.models import ColumnDataSource, RangeSlider

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


def test_biomass_application_constructs_without_network_access() -> None:
    document = Document()
    load_applications()["/biomass-change"](document)

    global_image = document.select_one({"type": ColumnDataSource, "name": "biomass-global-image"})
    local_image = document.select_one({"type": ColumnDataSource, "name": "biomass-local-image"})
    boundaries = document.select_one(
        {"type": ColumnDataSource, "name": "biomass-country-boundaries"}
    )
    years = document.select_one({"type": RangeSlider, "name": "biomass-years"})

    assert isinstance(global_image, ColumnDataSource)
    assert isinstance(local_image, ColumnDataSource)
    assert isinstance(boundaries, ColumnDataSource)
    assert isinstance(years, RangeSlider)
    assert years.value == (2000, 2025)
    assert global_image.data["image"][0].shape == (791, 1582)
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


def test_query_change_compares_scaled_source_values(monkeypatch) -> None:
    bounds = bounds_around(0, 0, 0.5)
    baseline = np.array([[100, 200], [cog.NO_DATA, 400]], dtype=np.int16)
    current = np.array([[150, 170], [300, 400]], dtype=np.int16)

    def fake_window(year: int, _bounds, _overview_level: int) -> Window:
        values = baseline if year == 2000 else current
        return Window(values=values, source_bytes=123)

    monkeypatch.setattr(cog, "read_year_window", fake_window)
    result = cog.query_change(2000, 2025, bounds)

    assert result.valid_pixels == 3
    np.testing.assert_allclose(result.delta[result.valid], [5, -3, 0])
    assert np.isnan(result.delta[1, 0])
    assert result.source_bytes == 246


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


def test_datashader_viewport_returns_exact_canvas_shape(monkeypatch) -> None:
    bounds = (-10.0, -5.0, 10.0, 5.0)
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
    result = shading.query_viewport(2000, 2025, bounds, plot_width=8, plot_height=4)

    assert result.delta.shape == (4, 8)
    assert result.bounds == bounds
    assert result.source_pixels == 32
    assert result.source_bytes == 512


def test_icechunk_window_slices_follow_native_grid() -> None:
    rows, columns = icechunk_source._window_slices((-0.5, -0.5, 0.5, 0.5))

    assert rows.start == 100_687
    assert rows.stop == 101_813
    assert columns.start == 201_937
    assert columns.stop == 203_063


def test_icechunk_query_compares_native_array_values(monkeypatch) -> None:
    bounds = bounds_around(0, 0, 0.5)
    baseline = np.array([[100, 200], [icechunk_source.NO_DATA, 400]], dtype=np.int16)
    current = np.array([[150, 170], [300, 400]], dtype=np.int16)

    def fake_window(year: int, _bounds) -> Window:
        values = baseline if year == 2000 else current
        return Window(values=values, source_bytes=values.nbytes)

    monkeypatch.setattr(icechunk_source, "read_year_window", fake_window)
    result = icechunk_source.query_change(2000, 2025, bounds)

    assert result.backend == "Arraylake Icechunk · native 100 m"
    assert result.valid_pixels == 3
    np.testing.assert_allclose(result.delta[result.valid], [5, -3, 0])
    assert np.isnan(result.delta[1, 0])
    assert result.source_bytes == 16
