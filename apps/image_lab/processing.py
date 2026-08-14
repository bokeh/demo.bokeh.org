"""Define the Numba-compiled image-processing operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numba import njit


@njit
def natural_color(image: np.ndarray, _amount: float) -> np.ndarray:
    return image.copy()


@njit
def luminance(image: np.ndarray, _amount: float) -> np.ndarray:
    height, width, _ = image.shape
    output = np.empty_like(image)
    for y in range(height):
        for x in range(width):
            red = float(image[y, x, 0])
            green = float(image[y, x, 1])
            blue = float(image[y, x, 2])
            value = np.uint8(min(255, 0.2126 * red + 0.7152 * green + 0.0722 * blue))
            output[y, x, 0] = value
            output[y, x, 1] = value
            output[y, x, 2] = value
    return output


@njit
def sobel_edges(image: np.ndarray, amount: float) -> np.ndarray:
    height, width, _ = image.shape
    output = image.copy()
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            top_left = np.mean(image[y - 1, x - 1])
            top = np.mean(image[y - 1, x])
            top_right = np.mean(image[y - 1, x + 1])
            left = np.mean(image[y, x - 1])
            right = np.mean(image[y, x + 1])
            bottom_left = np.mean(image[y + 1, x - 1])
            bottom = np.mean(image[y + 1, x])
            bottom_right = np.mean(image[y + 1, x + 1])
            gradient_x = top_right + 2 * right + bottom_right - top_left - 2 * left - bottom_left
            gradient_y = bottom_left + 2 * bottom + bottom_right - top_left - 2 * top - top_right
            value = np.uint8(min(255, amount * np.sqrt(gradient_x**2 + gradient_y**2) / 4))
            output[y, x, 0] = value
            output[y, x, 1] = value
            output[y, x, 2] = value
    return output


@njit
def unsharp_mask(image: np.ndarray, amount: float) -> np.ndarray:
    height, width, _ = image.shape
    output = image.copy()
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            for channel in range(3):
                neighbors = (
                    float(image[y - 1, x, channel])
                    + float(image[y + 1, x, channel])
                    + float(image[y, x - 1, channel])
                    + float(image[y, x + 1, channel])
                ) / 4
                value = image[y, x, channel] + amount * (image[y, x, channel] - neighbors)
                output[y, x, channel] = np.uint8(min(255, max(0, value)))
    return output


@njit
def contrast(image: np.ndarray, amount: float) -> np.ndarray:
    height, width, _ = image.shape
    output = np.empty_like(image)
    for y in range(height):
        for x in range(width):
            for channel in range(3):
                value = 127.5 + amount * (float(image[y, x, channel]) - 127.5)
                output[y, x, channel] = np.uint8(min(255, max(0, value)))
    return output


@njit
def gamma_correction(image: np.ndarray, amount: float) -> np.ndarray:
    height, width, _ = image.shape
    output = np.empty_like(image)
    for y in range(height):
        for x in range(width):
            for channel in range(3):
                normalized = float(image[y, x, channel]) / 255
                output[y, x, channel] = np.uint8(255 * normalized ** (1 / amount))
    return output


@njit
def gaussian_blur(image: np.ndarray, amount: float) -> np.ndarray:
    height, width, _ = image.shape
    output = np.empty_like(image)
    radius = int(min(4, max(1, round(2 * amount))))
    for y in range(height):
        for x in range(width):
            y_start = max(0, y - radius)
            y_end = min(height, y + radius + 1)
            x_start = max(0, x - radius)
            x_end = min(width, x + radius + 1)
            for channel in range(3):
                total = 0.0
                weight_sum = 0.0
                for sample_y in range(y_start, y_end):
                    for sample_x in range(x_start, x_end):
                        distance = (sample_y - y) ** 2 + (sample_x - x) ** 2
                        weight = np.exp(-distance / (2 * amount**2))
                        total += weight * image[sample_y, sample_x, channel]
                        weight_sum += weight
                output[y, x, channel] = np.uint8(total / weight_sum)
    return output


@njit
def color_saturation(image: np.ndarray, amount: float) -> np.ndarray:
    height, width, _ = image.shape
    output = np.empty_like(image)
    for y in range(height):
        for x in range(width):
            red = float(image[y, x, 0])
            green = float(image[y, x, 1])
            blue = float(image[y, x, 2])
            luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            for channel in range(3):
                value = luminance + amount * (float(image[y, x, channel]) - luminance)
                output[y, x, channel] = np.uint8(min(255, max(0, value)))
    return output


ImageProcessor = Callable[[np.ndarray, float], np.ndarray]


@dataclass(frozen=True)
class SliderConfig:
    title: str
    start: float
    end: float
    step: float
    value: float


@dataclass(frozen=True)
class ImageFilter:
    processor: ImageProcessor
    description: str
    slider: SliderConfig | None = None


FILTERS = {
    "Natural color": ImageFilter(natural_color, "The selected pixels are shown without a filter."),
    "Luminance": ImageFilter(luminance, "A perceptual RGB weighting produces a grayscale image."),
    "Contrast": ImageFilter(
        contrast,
        "Values are expanded or compressed around the midpoint.",
        SliderConfig("Contrast", 0.5, 3.0, 0.1, 1.5),
    ),
    "Gamma correction": ImageFilter(
        gamma_correction,
        "Gamma lifts shadow detail or darkens the midtones.",
        SliderConfig("Gamma", 0.4, 2.5, 0.1, 1.4),
    ),
    "Gaussian blur": ImageFilter(
        gaussian_blur,
        "A Gaussian-weighted neighborhood suppresses small, bright details.",
        SliderConfig("Blur sigma", 0.5, 2.0, 0.1, 1.2),
    ),
    "Sobel edges": ImageFilter(
        sobel_edges,
        "A gradient kernel isolates rapid changes in luminance.",
        SliderConfig("Edge gain", 0.5, 5.0, 0.1, 2.2),
    ),
    "Unsharp mask": ImageFilter(
        unsharp_mask,
        "Local contrast is increased around fine structure.",
        SliderConfig("Sharpening amount", 0.1, 3.0, 0.1, 1.2),
    ),
    "Color saturation": ImageFilter(
        color_saturation,
        "Color is pulled toward or pushed away from luminance.",
        SliderConfig("Saturation", 0, 2.0, 0.1, 1.4),
    ),
}
