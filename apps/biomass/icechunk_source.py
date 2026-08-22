"""Read tile-aligned CTrees biomass overviews from the derived Arraylake repo."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from math import ceil, floor, log, pi, tan
from threading import Lock
from time import perf_counter
from typing import Any

import numpy as np

from .cog import BASELINE_YEAR, LATEST_YEAR, NO_DATA, Bounds, ChangeQuery, Window, bounds_around

TOKEN_ENV = "ARRAYLAKE_API_TOKEN"
CLI_AUTH_ENV = "BIOMASS_ARRAYLAKE_USE_CLI_AUTH"
REPO_ENV = "BIOMASS_ARRAYLAKE_REPO"
DEFAULT_REPO = "bokeh/aboveground-biomass-webmercator-overviews"
DEFAULT_DETAIL_BOUNDS = bounds_around(-53.5, -6.5, 0.5)
DEFAULT_WARM_WORKERS = 8
CHUNK_CACHE_BYTES = 256 * 1024 * 1024
OVERVIEW_TILE_SIZE = 1024
OVERVIEW_MAX_ZOOM = 4
DISPLAY_TILE_SIZE = 256
DISPLAY_ZOOM_OFFSET = 2
MAX_REQUEST_ZOOM = 12
DISPLAY_MAX_ZOOM = MAX_REQUEST_ZOOM
VALID_MIN = 0
VALID_MAX = 6000
FILL_VALUE = NO_DATA
WEB_MERCATOR_MAX_LATITUDE = 85.0511287798066


@dataclass(frozen=True)
class TileChange:
    """One already-projected tile difference read from the overview repository."""

    delta: np.ndarray
    valid: np.ndarray
    source_bytes: int
    source_pixels: int
    source_zoom: int
    backend: str


class _RepositoryState:
    def __init__(self) -> None:
        self.lock = Lock()
        self.root: Any | None = None


_REPOSITORY_STATE = _RepositoryState()


def configured() -> bool:
    """Return whether API-token or explicitly enabled local CLI auth is configured."""
    return bool(os.environ.get(TOKEN_ENV) or os.environ.get(CLI_AUTH_ENV))


def _open_root() -> Any:
    """Open the derived Web Mercator overview repository."""
    token = os.environ.get(TOKEN_ENV)
    if not token and not os.environ.get(CLI_AUTH_ENV):
        raise RuntimeError(
            f"{TOKEN_ENV} or {CLI_AUTH_ENV}=1 is required for the overview repository"
        )

    zarr = import_module("zarr")
    icechunk = import_module("icechunk")
    client_type = import_module("arraylake").Client

    config = icechunk.config.RepositoryConfig.default()
    config.caching = icechunk.config.CachingConfig(
        num_chunk_refs=32_000, num_bytes_chunks=CHUNK_CACHE_BYTES
    )
    client_kwargs: dict[str, Any] = {"cache_credentials": False}
    if token:
        client_kwargs["token"] = token
    repository = client_type(**client_kwargs).get_repo(
        os.environ.get(REPO_ENV, DEFAULT_REPO), config=config
    )
    session = repository.readonly_session("main")
    return zarr.open_group(session.store, mode="r")


def _root() -> Any:
    """Return the process-wide overview group, opening it once."""
    if _REPOSITORY_STATE.root is not None:
        return _REPOSITORY_STATE.root
    with _REPOSITORY_STATE.lock:
        if _REPOSITORY_STATE.root is None:
            _REPOSITORY_STATE.root = _open_root()
        return _REPOSITORY_STATE.root


def warm_repository() -> float | None:
    """Resolve and cache repository metadata before serving user requests."""
    if not configured():
        return None
    started = perf_counter()
    _root()
    return perf_counter() - started


def warm_default_windows() -> float | None:
    """Cache the initial year pair for the demo's default detail footprint."""
    if not configured():
        return None
    started = perf_counter()
    years = (BASELINE_YEAR, LATEST_YEAR)
    with ThreadPoolExecutor(
        max_workers=DEFAULT_WARM_WORKERS, thread_name_prefix="biomass-overview-warm"
    ) as executor:
        list(executor.map(lambda year: read_year_window(year, DEFAULT_DETAIL_BOUNDS), years))
    return perf_counter() - started


def _reset_caches_for_testing() -> None:
    """Clear process caches for deterministic tests and live benchmarks."""
    with _REPOSITORY_STATE.lock:
        _REPOSITORY_STATE.root = None
    read_year_tile.cache_clear()
    read_year_window.cache_clear()


def _validate_year(year: int) -> int:
    if year < BASELINE_YEAR or year > LATEST_YEAR:
        raise ValueError(f"year must be between {BASELINE_YEAR} and {LATEST_YEAR}")
    return year - BASELINE_YEAR


def _tile_slices(zoom: int, column: int, row: int) -> tuple[int, int, int, slice, slice, int]:
    if zoom < 0 or zoom > MAX_REQUEST_ZOOM:
        raise ValueError(f"zoom must be between 0 and {MAX_REQUEST_ZOOM}")
    count = 1 << zoom
    if row < 0 or row >= count:
        raise ValueError("tile row is outside the selected zoom")
    column %= count
    source_zoom = min(max(zoom - DISPLAY_ZOOM_OFFSET, 0), OVERVIEW_MAX_ZOOM)
    scale = 1 << (zoom - source_zoom)
    source_column = column // scale
    source_row = row // scale
    local_column = column % scale
    local_row = row % scale
    span = OVERVIEW_TILE_SIZE // scale
    columns = slice(local_column * span, (local_column + 1) * span)
    rows = slice(local_row * span, (local_row + 1) * span)
    return source_zoom, source_column, source_row, rows, columns, scale


def _resize_display_tile(values: np.ndarray) -> np.ndarray:
    """Return one standard display tile from a storage-aligned pixel window."""
    span = values.shape[0]
    if values.shape != (span, span):
        raise ValueError("tile window must be square")
    if span == DISPLAY_TILE_SIZE:
        return values
    if span < DISPLAY_TILE_SIZE:
        factor = DISPLAY_TILE_SIZE // span
        if span * factor != DISPLAY_TILE_SIZE:
            raise ValueError("tile window cannot be enlarged to the display tile size")
        return np.repeat(np.repeat(values, factor, axis=0), factor, axis=1)

    factor = span // DISPLAY_TILE_SIZE
    if DISPLAY_TILE_SIZE * factor != span:
        raise ValueError("tile window cannot be reduced to the display tile size")
    blocks = values.reshape(DISPLAY_TILE_SIZE, factor, DISPLAY_TILE_SIZE, factor)
    valid = (blocks >= VALID_MIN) & (blocks <= VALID_MAX)
    counts = valid.sum(axis=(1, 3))
    totals = np.where(valid, blocks, 0).sum(axis=(1, 3), dtype=np.int64)
    reduced = np.full((DISPLAY_TILE_SIZE, DISPLAY_TILE_SIZE), FILL_VALUE, dtype=np.int16)
    comparable = counts > 0
    reduced[comparable] = np.rint(totals[comparable] / counts[comparable]).astype(np.int16)
    return reduced


@lru_cache(maxsize=128)
def read_year_tile(year: int, zoom: int, column: int, row: int) -> Window:
    """Read one 256 px display tile from the 1024 px storage pyramid."""
    year_index = _validate_year(year)
    source_zoom, source_column, source_row, rows, columns, _scale = _tile_slices(zoom, column, row)
    y0 = source_row * OVERVIEW_TILE_SIZE + rows.start
    y1 = source_row * OVERVIEW_TILE_SIZE + rows.stop
    x0 = source_column * OVERVIEW_TILE_SIZE + columns.start
    x1 = source_column * OVERVIEW_TILE_SIZE + columns.stop
    values = np.asarray(_root()["agb"][f"z{source_zoom}"][year_index, y0:y1, x0:x1], dtype=np.int16)
    source_bytes = values.nbytes
    values = _resize_display_tile(values)
    values.setflags(write=False)
    return Window(values=values, source_bytes=source_bytes)


def query_tile_change(
    start_year: int, end_year: int, zoom: int, column: int, row: int
) -> TileChange:
    """Compare two tile-aligned annual overview chunks without reprojection."""
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="biomass-overview-tile") as executor:
        baseline_future = executor.submit(read_year_tile, start_year, zoom, column, row)
        current_future = executor.submit(read_year_tile, end_year, zoom, column, row)
        baseline_window = baseline_future.result()
        current_window = current_future.result()
    baseline = baseline_window.values
    current = current_window.values
    valid = (
        (baseline >= VALID_MIN)
        & (baseline <= VALID_MAX)
        & (current >= VALID_MIN)
        & (current <= VALID_MAX)
    )
    delta = np.full(baseline.shape, np.nan, dtype=np.float32)
    np.subtract(current, baseline, out=delta, where=valid, dtype=np.float32)
    delta /= 10
    delta.setflags(write=False)
    valid.setflags(write=False)
    source_zoom = _tile_slices(zoom, column, row)[0]
    return TileChange(
        delta=delta,
        valid=valid,
        source_bytes=baseline_window.source_bytes + current_window.source_bytes,
        source_pixels=int(np.count_nonzero(valid)),
        source_zoom=source_zoom,
        backend=f"Arraylake Icechunk · precomputed Web Mercator z{source_zoom}",
    )


def _mercator_pixel_window(bounds: Bounds) -> tuple[slice, slice]:
    west, south, east, north = bounds
    world = OVERVIEW_TILE_SIZE * (1 << OVERVIEW_MAX_ZOOM)

    def column(longitude: float) -> float:
        return (longitude + 180) / 360 * world

    def row(latitude: float) -> float:
        clipped = min(max(latitude, -WEB_MERCATOR_MAX_LATITUDE), WEB_MERCATOR_MAX_LATITUDE)
        radians = clipped * pi / 180
        return (1 - log(tan(pi / 4 + radians / 2)) / pi) / 2 * world

    column_start = max(0, floor(column(west)))
    column_end = min(world, ceil(column(east)))
    row_start = max(0, floor(row(north)))
    row_end = min(world, ceil(row(south)))
    if column_start >= column_end or row_start >= row_end:
        raise ValueError("query bounds do not intersect the overview array")
    return slice(row_start, row_end), slice(column_start, column_end)


@lru_cache(maxsize=48)
def read_year_window(year: int, bounds: Bounds) -> Window:
    """Read a small WGS84 footprint from the finest precomputed overview."""
    year_index = _validate_year(year)
    rows, columns = _mercator_pixel_window(bounds)
    values = np.asarray(
        _root()["agb"][f"z{OVERVIEW_MAX_ZOOM}"][year_index, rows, columns], dtype=np.int16
    )
    values.setflags(write=False)
    return Window(values=values, source_bytes=values.nbytes)


def query_change(start_year: int, end_year: int, bounds: Bounds) -> ChangeQuery:
    """Compare two annual windows from the finest stored overview."""
    started = perf_counter()
    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="biomass-overview-detail"
    ) as executor:
        baseline_future = executor.submit(read_year_window, start_year, bounds)
        current_future = executor.submit(read_year_window, end_year, bounds)
        baseline_window = baseline_future.result()
        current_window = current_future.result()
    baseline = baseline_window.values
    current = current_window.values
    valid = (
        (baseline >= VALID_MIN)
        & (baseline <= VALID_MAX)
        & (current >= VALID_MIN)
        & (current <= VALID_MAX)
    )
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
        overview_level=OVERVIEW_MAX_ZOOM,
        source_bytes=baseline_window.source_bytes + current_window.source_bytes,
        elapsed_seconds=perf_counter() - started,
        backend="Arraylake Icechunk · precomputed Web Mercator (~2.4 km at equator)",
    )
