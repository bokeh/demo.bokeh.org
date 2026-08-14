"""Test the synthetic wave-field calculations."""

from __future__ import annotations

import numpy as np
import pytest

from apps.heatmap import OPTIONS, evaluate_field


@pytest.mark.parametrize("model", OPTIONS)
def test_every_field_model_preserves_shape_and_returns_finite_values(model: str) -> None:
    axis = np.linspace(-2, 2, 17)
    x, y = np.meshgrid(axis, axis)
    values = evaluate_field(model, x, y, 1.8, 0.7)

    assert values.shape == x.shape
    assert np.isfinite(values).all()
    assert np.ptp(values) > 0


def test_field_models_are_numerically_distinct() -> None:
    axis = np.linspace(-2, 2, 13)
    x, y = np.meshgrid(axis, axis)
    signatures = {np.round(evaluate_field(model, x, y, 1.8, 0.7), 8).tobytes() for model in OPTIONS}
    assert len(signatures) == len(OPTIONS)


def test_interference_matches_its_analytic_expression() -> None:
    x = np.array([0.2, 0.8])
    y = np.array([-0.5, 1.1])
    frequency = 1.7
    coupling = 0.4

    values = evaluate_field("Interference", x, y, frequency, coupling)
    expected = np.sin(frequency * x) * np.cos(frequency * y) + coupling * np.sin(x * y)
    assert values == pytest.approx(expected)


def test_twin_sources_is_symmetric_across_the_vertical_axis() -> None:
    x = np.linspace(-3, 3, 101)
    y = np.full_like(x, 0.4)
    values = evaluate_field("Twin sources", x, y, 1.6, 0.8)
    assert values == pytest.approx(values[::-1])


def test_airy_diffraction_has_unit_intensity_at_the_origin() -> None:
    values = evaluate_field("Airy diffraction", np.array([0.0]), np.array([0.0]), 2, 0.7)
    assert values[0] == pytest.approx(1)


def test_evaluate_field_rejects_unknown_model() -> None:
    with pytest.raises(ValueError, match="Unknown field model"):
        evaluate_field("Missing", np.array([0.0]), np.array([0.0]), 1, 1)
