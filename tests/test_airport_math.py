"""Test airport projection and distance calculations."""

from __future__ import annotations

import numpy as np
import pytest

from apps.airport_map import EARTH_RADIUS_M, EARTH_RADIUS_MI, distance_miles, web_mercator


def test_web_mercator_maps_origin_to_origin_and_longitude_linearly() -> None:
    longitude = np.array([0.0, 90.0, -90.0])
    latitude = np.zeros(3)
    x, y = web_mercator(longitude, latitude)

    assert x == pytest.approx([0, EARTH_RADIUS_M * np.pi / 2, -EARTH_RADIUS_M * np.pi / 2])
    assert y == pytest.approx(0, abs=1e-8)


def test_web_mercator_is_symmetric_and_clips_polar_latitudes() -> None:
    _x, y = web_mercator(np.zeros(4), np.array([-90.0, -85.0, 85.0, 90.0]))

    assert y[0] == pytest.approx(y[1])
    assert y[2] == pytest.approx(y[3])
    assert y[0] == pytest.approx(-y[3])


def test_distance_miles_returns_vectorized_great_circle_distance() -> None:
    distances = distance_miles(0, 0, np.array([0.0, 0.0, 90.0]), np.array([0.0, 90.0, 0.0]))

    quarter_circumference = EARTH_RADIUS_MI * np.pi / 2
    assert distances == pytest.approx([0, quarter_circumference, quarter_circumference])


def test_distance_miles_crosses_the_antimeridian_by_the_short_path() -> None:
    distance = distance_miles(0, 179, np.array([0.0]), np.array([-179.0]))
    expected = EARTH_RADIUS_MI * np.radians(2)
    assert distance[0] == pytest.approx(expected)
