"""Pixel-aligned Web Mercator tiles for CTrees biomass change."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from math import atan, degrees, pi, sinh
from time import perf_counter

import imagecodecs
import numpy as np

from . import cog, icechunk_source
from .cog import BASELINE_YEAR, LATEST_YEAR, Bounds, overview_level_for
from .color import color_limits, rgba_pixels

EARTH_RADIUS_M = 6_378_137.0
WEB_MERCATOR_LIMIT = EARTH_RADIUS_M * pi
WEB_MERCATOR_MAX_LATITUDE = 85.0511287798066
TILE_SIZE = icechunk_source.DISPLAY_TILE_SIZE
TILE_VERSION = "icechunk-z4-pixel-aligned-v7"
MAX_TILE_ZOOM = icechunk_source.DISPLAY_MAX_ZOOM
TILE_CACHE_SIZE = 512
INITIAL_VISIBLE_TILES = tuple((6, column, row) for row in range(32, 35) for column in range(21, 24))
INITIAL_WARM_TILES = tuple((6, column, row) for row in range(29, 37) for column in range(19, 26))
WORLD_WARM_TILES = ((0, 0, 0), *((1, column, row) for row in range(2) for column in range(2)))
INITIAL_TILE_WARM_WORKERS = 6


@dataclass(frozen=True)
class TileQuery:
    """One Web Mercator tile and its source metadata."""

    image: bytes
    media_type: str
    bounds: Bounds
    start_year: int
    end_year: int
    zoom: int
    column: int
    row: int
    overview_level: int
    source_bytes: int
    source_pixels: int
    elapsed_seconds: float
    backend: str


def tile_bounds(zoom: int, column: int, row: int) -> Bounds:
    """Return a WebMercatorQuad tile's WGS84 bounds."""
    if zoom < 0 or zoom > MAX_TILE_ZOOM:
        raise ValueError(f"zoom must be between 0 and {MAX_TILE_ZOOM}")
    count = 1 << zoom
    if row < 0 or row >= count:
        raise ValueError("tile row is outside the selected zoom")
    column %= count
    west = column / count * 360 - 180
    east = (column + 1) / count * 360 - 180
    north = degrees(atan(sinh(pi * (1 - 2 * row / count))))
    south = degrees(atan(sinh(pi * (1 - 2 * (row + 1) / count))))
    return (west, south, east, north)


def web_mercator(longitude: np.ndarray, latitude: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project longitude and latitude arrays into EPSG:3857 metres."""
    clipped = np.clip(latitude, -WEB_MERCATOR_MAX_LATITUDE, WEB_MERCATOR_MAX_LATITUDE)
    x = EARTH_RADIUS_M * np.radians(longitude)
    y = EARTH_RADIUS_M * np.log(np.tan(pi / 4 + np.radians(clipped) / 2))
    return x, y


def inverse_web_mercator(x: float, y: float) -> tuple[float, float]:
    """Return longitude and latitude for one EPSG:3857 point."""
    longitude = float(np.degrees(x / EARTH_RADIUS_M))
    latitude = float(np.degrees(2 * np.arctan(np.exp(y / EARTH_RADIUS_M)) - pi / 2))
    return longitude, latitude


def _tile_mercator_bounds(zoom: int, column: int, row: int) -> Bounds:
    count = 1 << zoom
    column %= count
    span = 2 * WEB_MERCATOR_LIMIT / count
    west = -WEB_MERCATOR_LIMIT + column * span
    east = west + span
    north = WEB_MERCATOR_LIMIT - row * span
    south = north - span
    return (west, south, east, north)


def rasterize_values(
    values: np.ndarray, bounds: Bounds, mercator_bounds: Bounds, tile_size: int = TILE_SIZE
) -> tuple[np.ndarray, np.ndarray]:
    """Sample a WGS84 pixel grid at Web Mercator output-pixel centres."""
    west, south, east, north = bounds
    rows, columns = values.shape
    if rows == 0 or columns == 0 or east <= west or north <= south:
        raise ValueError("source raster must have nonempty values and positive bounds")
    mercator_west, mercator_south, mercator_east, mercator_north = mercator_bounds
    if mercator_east <= mercator_west or mercator_north <= mercator_south:
        raise ValueError("Web Mercator bounds must be positive")

    x_step = (mercator_east - mercator_west) / tile_size
    y_step = (mercator_north - mercator_south) / tile_size
    target_x = np.linspace(mercator_west + x_step / 2, mercator_east - x_step / 2, tile_size)
    target_y = np.linspace(mercator_north - y_step / 2, mercator_south + y_step / 2, tile_size)
    longitude = np.degrees(target_x / EARTH_RADIUS_M)
    latitude = np.degrees(2 * np.arctan(np.exp(target_y / EARTH_RADIUS_M)) - pi / 2)
    source_columns = np.floor((longitude - west) / (east - west) * columns).astype(np.int64)
    source_rows = np.floor((north - latitude) / (north - south) * rows).astype(np.int64)
    columns_inside = (source_columns >= 0) & (source_columns < columns)
    rows_inside = (source_rows >= 0) & (source_rows < rows)
    source_columns = np.clip(source_columns, 0, columns - 1)
    source_rows = np.clip(source_rows, 0, rows - 1)
    delta = np.asarray(values[np.ix_(source_rows, source_columns)], dtype=np.float32)
    delta[~rows_inside, :] = np.nan
    delta[:, ~columns_inside] = np.nan
    delta = np.ascontiguousarray(delta)
    return delta, np.isfinite(delta)


@lru_cache(maxsize=TILE_CACHE_SIZE)
def query_tile(
    start_year: int, end_year: int, zoom: int, column: int, row: int, image_format: str = "webp"
) -> TileQuery:
    """Read, project, color, encode, and cache one WebMercatorQuad tile."""
    if not BASELINE_YEAR <= start_year <= LATEST_YEAR:
        raise ValueError(f"start year must be between {BASELINE_YEAR} and {LATEST_YEAR}")
    if not BASELINE_YEAR <= end_year <= LATEST_YEAR:
        raise ValueError(f"end year must be between {BASELINE_YEAR} and {LATEST_YEAR}")
    if image_format not in {"png", "webp"}:
        raise ValueError("image format must be png or webp")
    started = perf_counter()
    count = 1 << zoom
    column %= count
    bounds = tile_bounds(zoom, column, row)
    if icechunk_source.configured():
        change = icechunk_source.query_tile_change(start_year, end_year, zoom, column, row)
        delta = change.delta
        valid = change.valid
        overview_level = change.source_zoom
        source_pixels = change.source_pixels
        source_bytes = change.source_bytes
        backend = change.backend
    else:
        overview_level = overview_level_for(bounds, TILE_SIZE, TILE_SIZE)
        change = cog.query_change(start_year, end_year, bounds, overview_level)
        delta, valid = rasterize_values(
            change.delta, change.bounds, _tile_mercator_bounds(zoom, column, row)
        )
        source_pixels = change.valid_pixels
        source_bytes = change.source_bytes
        backend = change.backend
    global_limit, _local_limit, _histogram_limit = color_limits(start_year, end_year)
    pixels = rgba_pixels(delta, valid, limit=global_limit)
    if image_format == "webp":
        image = bytes(imagecodecs.webp_encode(pixels, lossless=True, method=2))
        media_type = "image/webp"
    else:
        image = bytes(imagecodecs.png_encode(pixels))
        media_type = "image/png"
    return TileQuery(
        image=image,
        media_type=media_type,
        bounds=bounds,
        start_year=start_year,
        end_year=end_year,
        zoom=zoom,
        column=column,
        row=row,
        overview_level=overview_level,
        source_bytes=source_bytes,
        source_pixels=source_pixels,
        elapsed_seconds=perf_counter() - started,
        backend=backend,
    )


def warm_renderer() -> float:
    """Warm the tile reprojection and WebP encoding paths before readiness."""
    started = perf_counter()
    source = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)
    x, y = web_mercator(np.array([-1.0, 1.0]), np.array([-1.0, 1.0]))
    raster, valid = rasterize_values(
        source,
        (-1.0, -1.0, 1.0, 1.0),
        (float(x[0]), float(y[0]), float(x[1]), float(y[1])),
        tile_size=2,
    )
    if raster.shape != (2, 2):
        raise RuntimeError("Biomass raster warmup returned an unexpected shape")
    pixels = rgba_pixels(raster, valid, limit=5)
    webp = bytes(imagecodecs.webp_encode(pixels, lossless=True, method=2))
    if not (webp.startswith(b"RIFF") and webp[8:12] == b"WEBP"):
        raise RuntimeError("WebP warmup returned an unexpected payload")
    return perf_counter() - started


def warm_initial_tiles() -> float | None:
    """Cache the first Pará viewport plus low-zoom tiles used after reset."""
    if not icechunk_source.configured():
        return None
    started = perf_counter()
    coordinates = (*INITIAL_WARM_TILES, *WORLD_WARM_TILES)
    with ThreadPoolExecutor(
        max_workers=INITIAL_TILE_WARM_WORKERS, thread_name_prefix="biomass-initial-tile-warm"
    ) as executor:
        list(executor.map(lambda tile: query_tile(BASELINE_YEAR, LATEST_YEAR, *tile), coordinates))
    return perf_counter() - started
