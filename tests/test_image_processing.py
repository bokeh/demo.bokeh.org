"""Test the numerical image-processing operations."""

from __future__ import annotations

import numpy as np
import pytest

from apps.image_lab.processing import (
    FILTERS,
    color_saturation,
    contrast,
    gamma_correction,
    gaussian_blur,
    luminance,
    natural_color,
    sobel_edges,
    unsharp_mask,
)


def test_natural_color_returns_an_independent_copy() -> None:
    image = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    result = natural_color(image, 99)

    assert np.array_equal(result, image)
    assert not np.shares_memory(result, image)


def test_luminance_uses_perceptual_rgb_weights() -> None:
    image = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255]]], dtype=np.uint8)
    result = luminance(image, 1)

    assert result[0, :, 0].tolist() == [54, 182, 18]
    assert np.array_equal(result[..., 0], result[..., 1])
    assert np.array_equal(result[..., 1], result[..., 2])


def test_sobel_edges_finds_a_vertical_boundary() -> None:
    image = np.zeros((7, 7, 3), dtype=np.uint8)
    image[:, 4:] = 255
    result = sobel_edges(image, 2)

    assert result[3, 3, 0] == 255
    assert np.array_equal(result[1:-1, 1:-1, 0], result[1:-1, 1:-1, 1])
    assert np.array_equal(result[1:-1, 1:-1, 1], result[1:-1, 1:-1, 2])
    assert np.array_equal(result[0], image[0])


def test_unsharp_mask_enhances_and_clips_local_contrast() -> None:
    image = np.full((3, 3, 3), 100, dtype=np.uint8)
    image[1, 1] = 200

    result = unsharp_mask(image, 1)

    assert np.all(result[1, 1] == 255)
    assert np.array_equal(result[0], image[0])


def test_contrast_one_is_identity_and_extremes_are_clipped() -> None:
    image = np.array([[[0, 64, 128], [192, 224, 255]]], dtype=np.uint8)

    assert np.array_equal(contrast(image, 1), image)
    assert contrast(image, 3).min() == 0
    assert contrast(image, 3).max() == 255


def test_gamma_correction_lifts_midtones_above_one() -> None:
    image = np.array([[[0, 64, 255]]], dtype=np.uint8)
    result = gamma_correction(image, 2)

    assert result[0, 0, 0] == 0
    assert result[0, 0, 1] > image[0, 0, 1]
    assert result[0, 0, 2] == 255


def test_gaussian_blur_spreads_an_impulse_symmetrically() -> None:
    image = np.zeros((7, 7, 3), dtype=np.uint8)
    image[3, 3] = 255
    result = gaussian_blur(image, 1)

    assert 0 < result[3, 3, 0] < 255
    assert result[3, 2, 0] == result[3, 4, 0]
    assert result[2, 3, 0] == result[4, 3, 0]
    assert result[3, 3, 0] > result[3, 2, 0]


def test_zero_saturation_produces_grayscale() -> None:
    image = np.array([[[200, 40, 10], [15, 90, 240]]], dtype=np.uint8)
    result = color_saturation(image, 0)

    assert np.array_equal(result[..., 0], result[..., 1])
    assert np.array_equal(result[..., 1], result[..., 2])


@pytest.mark.parametrize("name", list(FILTERS))
def test_every_filter_preserves_shape_dtype_and_input(name: str) -> None:
    image = np.random.default_rng(4).integers(0, 256, (6, 7, 3), dtype=np.uint8)
    original = image.copy()
    image_filter = FILTERS[name]
    amount = image_filter.slider.value if image_filter.slider is not None else 1.0

    result = image_filter.processor(image, amount)

    assert result.shape == image.shape
    assert result.dtype == image.dtype
    assert np.array_equal(image, original)


def test_filter_metadata_matches_control_requirements() -> None:
    assert set(FILTERS) == {
        "Natural color",
        "Luminance",
        "Contrast",
        "Gamma correction",
        "Gaussian blur",
        "Sobel edges",
        "Unsharp mask",
        "Color saturation",
    }
    assert FILTERS["Natural color"].slider is None
    assert FILTERS["Luminance"].slider is None
    for image_filter in FILTERS.values():
        assert image_filter.description.endswith(".")
        if slider := image_filter.slider:
            assert slider.start <= slider.value <= slider.end
            assert slider.step > 0
