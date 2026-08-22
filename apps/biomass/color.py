"""Color mapping shared by Bokeh image glyphs and Web Mercator tiles."""

from __future__ import annotations

import numpy as np

GLOBAL_COLOR_LIMIT = 25.0
LOCAL_COLOR_LIMIT = 60.0
COLOR_DEADBAND = 2.0
MIN_COLOR_STRENGTH = 0.32
LOSS_HEX = "#ff5a36"
GAIN_HEX = "#00c2e0"
NEUTRAL_HEX = "#6c6871"
LOSS_SOFT_HEX = "#9b635e"
GAIN_SOFT_HEX = "#498595"
LOSS = np.array([255, 90, 54], dtype=np.float32)
GAIN = np.array([0, 194, 224], dtype=np.float32)
NEUTRAL = np.array([108, 104, 113], dtype=np.float32)


def rgba_pixels(delta: np.ndarray, valid: np.ndarray, *, limit: float) -> np.ndarray:
    """Return north-up RGBA pixels for a biomass-change raster."""
    absolute = np.abs(np.nan_to_num(delta))
    scaled = np.clip((absolute - COLOR_DEADBAND) / (limit - COLOR_DEADBAND), 0, 1)
    magnitude = np.where(
        absolute <= COLOR_DEADBAND,
        0,
        MIN_COLOR_STRENGTH + (1 - MIN_COLOR_STRENGTH) * np.power(scaled, 0.75),
    )[..., None]
    target = np.where((delta < 0)[..., None], LOSS, GAIN)
    rgb = NEUTRAL + (target - NEUTRAL) * magnitude
    rgba = np.empty((*delta.shape, 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, np.where(absolute <= COLOR_DEADBAND, 72, 245), 0).astype(
        np.uint8
    )
    return rgba


def rgba_image(delta: np.ndarray, valid: np.ndarray, *, limit: float) -> np.ndarray:
    """Pack a north-up raster for Bokeh's bottom-up ``image_rgba`` glyph."""
    rgba = rgba_pixels(delta, valid, limit=limit)
    return np.ascontiguousarray(np.flipud(rgba)).view(np.uint32).reshape(delta.shape)


def color_limits(start_year: int, end_year: int) -> tuple[float, float, float]:
    """Scale global, detail, and histogram ranges to the comparison interval."""
    years = max(abs(end_year - start_year), 1)
    return (
        max(5.0, GLOBAL_COLOR_LIMIT * years / 25),
        max(12.0, LOCAL_COLOR_LIMIT * years / 25),
        max(20.0, 100 * years / 25),
    )
