"""Read small geographic windows from the public CTrees biomass COGs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from math import ceil, floor, log2
from time import perf_counter
from typing import BinaryIO, cast

import fsspec
import numpy as np
import tifffile

BASE_URL = "https://ctrees-agb-100m-global.s3.us-west-2.amazonaws.com/cogs"
COG_NAME = "global_agb_100m_landsat0024_all_{year}_densenet_l1_agb_mosaic_100m_base_cd_ts.tif"
BASELINE_YEAR = 2000
LATEST_YEAR = 2025
NO_DATA = -9999
HTTP_BLOCK_SIZE = 2 * 1024 * 1024
NATIVE_WIDTH = 405_000
NATIVE_HEIGHT = 202_500
NATIVE_RESOLUTION = 360 / NATIVE_WIDTH
OVERVIEW_LEVELS = 11

Bounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class Window:
    """One decoded geographic window and its source-read metadata."""

    values: np.ndarray
    source_bytes: int


@dataclass(frozen=True)
class ChangeQuery:
    """Biomass change and summary values for one live query."""

    baseline: np.ndarray
    current: np.ndarray
    delta: np.ndarray
    valid: np.ndarray
    bounds: Bounds
    start_year: int
    end_year: int
    overview_level: int
    source_bytes: int
    elapsed_seconds: float
    backend: str = "public COG overview"

    @property
    def valid_pixels(self) -> int:
        return int(np.count_nonzero(self.valid))


def url_for(year: int) -> str:
    """Return the public COG URL for an available CTrees year."""
    if year < BASELINE_YEAR or year > LATEST_YEAR:
        raise ValueError(f"year must be between {BASELINE_YEAR} and {LATEST_YEAR}")
    return f"{BASE_URL}/{COG_NAME.format(year=year)}"


def bounds_around(longitude: float, latitude: float, span: float) -> Bounds:
    """Return a fixed-size WGS84 box kept inside the raster extent."""
    if not 0.1 <= span <= 2:
        raise ValueError("span must be between 0.1 and 2 degrees")
    half = span / 2
    west = min(max(longitude - half, -180.0), 180.0 - span)
    south = min(max(latitude - half, -90.0), 90.0 - span)
    return (round(west, 6), round(south, 6), round(west + span, 6), round(south + span, 6))


def fit_bounds_to_aspect(bounds: Bounds, aspect: float) -> Bounds:
    """Expand and clamp bounds to ``aspect`` without stretching geographic pixels."""
    if aspect <= 0:
        raise ValueError("aspect must be positive")
    west, south, east, north = bounds
    width = east - west
    height = north - south
    if width <= 0 or height <= 0:
        raise ValueError("bounds must have positive width and height")
    center_x = (west + east) / 2
    center_y = (south + north) / 2
    if width / height < aspect:
        width = height * aspect
    else:
        height = width / aspect
    width = min(width, 360)
    height = min(height, 180)
    west = min(max(center_x - width / 2, -180), 180 - width)
    south = min(max(center_y - height / 2, -90), 90 - height)
    return (round(west, 6), round(south, 6), round(west + width, 6), round(south + height, 6))


def overview_level_for(bounds: Bounds, plot_width: int, plot_height: int) -> int:
    """Choose the finest COG overview that remains close to canvas resolution."""
    west, south, east, north = bounds
    if plot_width <= 0 or plot_height <= 0:
        raise ValueError("plot dimensions must be positive")
    target_resolution = max((east - west) / plot_width, (north - south) / plot_height)
    ratio = max(target_resolution / NATIVE_RESOLUTION, 1)
    return min(max(floor(log2(ratio)), 0), OVERVIEW_LEVELS - 1)


def _pixel_window(page: tifffile.TiffPage, bounds: Bounds) -> tuple[int, int, int, int]:
    west, south, east, north = bounds
    # Reduced-resolution IFDs omit GeoTIFF tags but retain the same global extent.
    scale_x = 360 / page.imagewidth
    scale_y = 180 / page.imagelength
    origin_x = -180.0
    origin_y = 90.0
    column_start = max(0, floor((west - origin_x) / scale_x))
    column_end = min(page.imagewidth, ceil((east - origin_x) / scale_x))
    row_start = max(0, floor((origin_y - north) / scale_y))
    row_end = min(page.imagelength, ceil((origin_y - south) / scale_y))
    if column_start >= column_end or row_start >= row_end:
        raise ValueError("query bounds do not intersect the raster")
    return row_start, row_end, column_start, column_end


def _read_tiles(page: tifffile.TiffPage, bounds: Bounds) -> Window:
    if not page.is_tiled or page.tilewidth is None or page.tilelength is None:
        raise ValueError("CTrees source is expected to be a tiled GeoTIFF")

    row_start, row_end, column_start, column_end = _pixel_window(page, bounds)
    tile_width = page.tilewidth
    tile_height = page.tilelength
    tiles_across = ceil(page.imagewidth / tile_width)
    tile_columns = range(column_start // tile_width, (column_end - 1) // tile_width + 1)
    tile_rows = range(row_start // tile_height, (row_end - 1) // tile_height + 1)
    tile_indices = [row * tiles_across + column for row in tile_rows for column in tile_columns]
    offsets = [page.dataoffsets[index] for index in tile_indices]
    bytecounts = [page.databytecounts[index] for index in tile_indices]
    result = np.full((row_end - row_start, column_end - column_start), NO_DATA, dtype=np.int16)
    segments = page.parent.filehandle.read_segments(
        offsets, bytecounts, indices=tile_indices, sort=True
    )
    for segment in segments:
        decoded, position, _shape = page.decode(*segment, _fullsize=True)
        if decoded is None:
            continue
        tile_y, tile_x = position[2], position[3]
        data = decoded[0, :, :, 0]
        source_y0 = max(row_start, tile_y) - tile_y
        source_y1 = min(row_end, tile_y + data.shape[0]) - tile_y
        source_x0 = max(column_start, tile_x) - tile_x
        source_x1 = min(column_end, tile_x + data.shape[1]) - tile_x
        target_y0 = max(row_start, tile_y) - row_start
        target_x0 = max(column_start, tile_x) - column_start
        target_y1 = target_y0 + source_y1 - source_y0
        target_x1 = target_x0 + source_x1 - source_x0
        result[target_y0:target_y1, target_x0:target_x1] = data[
            source_y0:source_y1, source_x0:source_x1
        ]

    result.setflags(write=False)
    return Window(values=result, source_bytes=sum(bytecounts))


@lru_cache(maxsize=48)
def read_year_window(year: int, bounds: Bounds, overview_level: int = 0) -> Window:
    """Range-read and decode only the source tiles intersecting ``bounds``."""
    if overview_level < 0 or overview_level >= OVERVIEW_LEVELS:
        raise ValueError(f"overview_level must be between 0 and {OVERVIEW_LEVELS - 1}")
    with (
        fsspec.open(url_for(year), "rb", block_size=HTTP_BLOCK_SIZE) as stream,
        tifffile.TiffFile(cast(BinaryIO, stream)) as tif,
    ):
        return _read_tiles(cast(tifffile.TiffPage, tif.pages[overview_level]), bounds)


def query_change(
    start_year: int, end_year: int, bounds: Bounds, overview_level: int = 0
) -> ChangeQuery:
    """Read two annual windows concurrently and compare them."""
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ctrees-cog") as executor:
        baseline_future = executor.submit(read_year_window, start_year, bounds, overview_level)
        current_future = executor.submit(read_year_window, end_year, bounds, overview_level)
        baseline_window = baseline_future.result()
        current_window = current_future.result()

    baseline = baseline_window.values
    current = current_window.values
    if baseline.shape != current.shape:
        raise ValueError("source windows do not have matching shapes")
    valid = (baseline != NO_DATA) & (current != NO_DATA)
    delta = np.full(baseline.shape, np.nan, dtype=np.float32)
    np.subtract(current, baseline, out=delta, where=valid, dtype=np.float32)
    delta /= 10
    delta.setflags(write=False)
    valid.setflags(write=False)
    return ChangeQuery(
        baseline=baseline,
        current=current,
        delta=delta,
        valid=valid,
        bounds=bounds,
        start_year=start_year,
        end_year=end_year,
        overview_level=overview_level,
        source_bytes=baseline_window.source_bytes + current_window.source_bytes,
        elapsed_seconds=perf_counter() - started,
    )
