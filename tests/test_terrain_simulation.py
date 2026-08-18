"""Test synthetic terrain generation and transect sampling."""

from __future__ import annotations

import numpy as np
import pytest

from apps.terrain.simulation import (
    LANDFORMS,
    LEVELS,
    XX,
    YY,
    X,
    Y,
    gaussian_surface,
    generate_terrain,
    sample_transect,
    volcanic_caldera,
)


def test_gaussian_surface_peaks_at_its_center_and_is_anisotropic() -> None:
    x = np.array([[0.0, 1.0, 0.0]])
    y = np.array([[0.0, 0.0, 1.0]])
    surface = gaussian_surface(x, y, 0, 0, 1, 2)

    assert surface[0, 0] == 1
    assert surface[0, 1] == pytest.approx(np.exp(-1))
    assert surface[0, 2] == pytest.approx(np.exp(-0.25))


@pytest.mark.parametrize("name", list(LANDFORMS))
def test_raw_landforms_are_finite_dramatic_fields(name: str) -> None:
    terrain = LANDFORMS[name]()

    assert terrain.shape == XX.shape == YY.shape == (len(Y), len(X))
    assert np.isfinite(terrain).all()
    assert np.ptp(terrain) > 1_000


def test_landform_generators_produce_distinct_surfaces() -> None:
    signatures = {np.round(generator(), 6).tobytes() for generator in LANDFORMS.values()}
    assert len(signatures) == len(LANDFORMS)


@pytest.mark.parametrize("name", list(LANDFORMS))
def test_generate_terrain_clips_to_displayed_elevation_range(name: str) -> None:
    first = generate_terrain(name)
    second = generate_terrain(name)

    assert first.min() >= LEVELS[0] + 1
    assert first.max() <= 2_800
    assert np.array_equal(first, second)
    assert first is not second


def test_volcanic_caldera_has_a_depressed_center_inside_the_rim() -> None:
    terrain = volcanic_caldera()
    center_y = int(np.argmin(np.abs(Y - 0.1)))
    center_x = int(np.argmin(np.abs(X + 0.25)))
    rim_x = int(np.argmin(np.abs(X - 0.75)))

    assert terrain[center_y, center_x] < terrain[center_y, rim_x]


def test_island_arc_crosses_sea_level() -> None:
    terrain = generate_terrain("Island arc")
    assert terrain.min() < 0 < terrain.max()


def test_generate_terrain_rejects_unknown_landform() -> None:
    with pytest.raises(ValueError, match="Unknown landform"):
        generate_terrain("Missing")  # pyright: ignore[reportArgumentType]


def test_sample_transect_interpolates_a_planar_surface() -> None:
    terrain = 2 * XX + 3 * YY
    distance, values = sample_transect(terrain, -4, -2, 5, 3)
    sample_x = np.linspace(-4, 5, len(values))
    sample_y = np.linspace(-2, 3, len(values))

    assert len(distance) == len(values) == 241
    assert distance[0] == 0
    assert distance[-1] == pytest.approx(np.hypot(9, 5))
    assert values == pytest.approx(2 * sample_x + 3 * sample_y)


def test_sample_transect_clips_samples_to_the_model_extent() -> None:
    terrain = XX.copy()
    _distance, values = sample_transect(terrain, X[0] - 5, 0, X[-1] + 5, 0)

    assert values[0] == pytest.approx(X[0])
    assert values[-1] == pytest.approx(X[-1])
    assert np.all(np.diff(values) >= 0)


def test_sample_transect_preserves_constant_elevation() -> None:
    terrain = np.full_like(XX, -125.0)
    _distance, values = sample_transect(terrain, -5, 4, 5, -4)
    assert values == pytest.approx(-125)
