"""Read native CTrees biomass pixels from the subscribed Arraylake Icechunk repo."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from importlib import import_module
from math import ceil, floor
from threading import Lock
from time import perf_counter
from typing import Any

import numpy as np

from .cog import (
    BASELINE_YEAR,
    LATEST_YEAR,
    NATIVE_HEIGHT,
    NATIVE_RESOLUTION,
    NATIVE_WIDTH,
    NO_DATA,
    Bounds,
    ChangeQuery,
    Window,
    bounds_around,
)

TOKEN_ENV = "ARRAYLAKE_API_TOKEN"
REPO_ENV = "BIOMASS_ARRAYLAKE_REPO"
DEFAULT_REPO = "bokeh/aboveground_biomass_100m_global_open-subscription"
DEFAULT_DETAIL_BOUNDS = bounds_around(-53.5, -6.5, 0.5)
DEFAULT_WARM_WORKERS = 8


class _ArrayState:
    def __init__(self) -> None:
        self.lock = Lock()
        self.array: Any | None = None


_ARRAY_STATE = _ArrayState()


def configured() -> bool:
    """Return whether credentials for the subscribed Icechunk repo are configured."""
    return bool(os.environ.get(TOKEN_ENV))


def _open_agb_array() -> Any:
    """Open the native-resolution Zarr array backed by Icechunk."""
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"{TOKEN_ENV} is required for the subscribed Icechunk repository")

    # Keep these imports lazy so gallery construction and offline tests do not authenticate.
    zarr = import_module("zarr")
    icechunk = import_module("icechunk")
    client_type = import_module("arraylake").Client

    client = client_type(token=token, cache_credentials=False)
    config = icechunk.config.RepositoryConfig.default()
    # The AGB manifest contains about 538k virtual references. Caching it once prevents
    # every small map query from rescanning the same manifest.
    config.caching = icechunk.config.CachingConfig(num_chunk_refs=1_200_000)
    repository = client.get_repo(os.environ.get(REPO_ENV, DEFAULT_REPO), config=config)
    session = repository.readonly_session("main")
    root = zarr.open_group(session.store, mode="r")
    return root["aboveground_biomass"]["agb"]


def _agb_array() -> Any:
    """Return the process-wide array, opening it exactly once across concurrent queries."""
    if _ARRAY_STATE.array is not None:
        return _ARRAY_STATE.array
    with _ARRAY_STATE.lock:
        if _ARRAY_STATE.array is None:
            _ARRAY_STATE.array = _open_agb_array()
        return _ARRAY_STATE.array


def warm_repository() -> float | None:
    """Resolve and cache repository metadata before user sessions can issue queries."""
    if not configured():
        return None
    started = perf_counter()
    _agb_array()
    return perf_counter() - started


def warm_default_windows() -> float | None:
    """Cache every annual window for the demo's initial detail footprint."""
    if not configured():
        return None
    started = perf_counter()
    years = range(BASELINE_YEAR, LATEST_YEAR + 1)
    with ThreadPoolExecutor(
        max_workers=DEFAULT_WARM_WORKERS, thread_name_prefix="ctrees-icechunk-warm"
    ) as executor:
        list(executor.map(lambda year: read_year_window(year, DEFAULT_DETAIL_BOUNDS), years))
    return perf_counter() - started


def _reset_caches_for_testing() -> None:
    """Clear process caches for deterministic tests and live benchmarks."""
    with _ARRAY_STATE.lock:
        _ARRAY_STATE.array = None
    read_year_window.cache_clear()


def _window_slices(bounds: Bounds) -> tuple[slice, slice]:
    west, south, east, north = bounds
    column_start = max(0, floor((west + 180) / NATIVE_RESOLUTION))
    column_end = min(NATIVE_WIDTH, ceil((east + 180) / NATIVE_RESOLUTION))
    row_start = max(0, floor((90 - north) / NATIVE_RESOLUTION))
    row_end = min(NATIVE_HEIGHT, ceil((90 - south) / NATIVE_RESOLUTION))
    if column_start >= column_end or row_start >= row_end:
        raise ValueError("query bounds do not intersect the Icechunk array")
    return slice(row_start, row_end), slice(column_start, column_end)


@lru_cache(maxsize=48)
def read_year_window(year: int, bounds: Bounds) -> Window:
    """Read one native 100 m window through Arraylake's Icechunk repository."""
    if year < BASELINE_YEAR or year > LATEST_YEAR:
        raise ValueError(f"year must be between {BASELINE_YEAR} and {LATEST_YEAR}")
    rows, columns = _window_slices(bounds)
    values = np.asarray(_agb_array()[year - BASELINE_YEAR, rows, columns], dtype=np.int16)
    values.setflags(write=False)
    return Window(values=values, source_bytes=values.nbytes)


def query_change(start_year: int, end_year: int, bounds: Bounds) -> ChangeQuery:
    """Read and compare two native annual windows through Icechunk."""
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ctrees-icechunk") as executor:
        baseline_future = executor.submit(read_year_window, start_year, bounds)
        current_future = executor.submit(read_year_window, end_year, bounds)
        baseline_window = baseline_future.result()
        current_window = current_future.result()

    baseline = baseline_window.values
    current = current_window.values
    if baseline.shape != current.shape:
        raise ValueError("Icechunk source windows do not have matching shapes")
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
        overview_level=0,
        source_bytes=baseline_window.source_bytes + current_window.source_bytes,
        elapsed_seconds=perf_counter() - started,
        backend="Arraylake Icechunk · native 100 m",
    )
