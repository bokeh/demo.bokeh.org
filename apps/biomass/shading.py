"""Datashader-backed viewport rendering for CTrees biomass change."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import datashader as ds
import numpy as np
import xarray as xr

from . import cog, icechunk_source
from .cog import Bounds, fit_bounds_to_aspect, overview_level_for


@dataclass(frozen=True)
class ViewportQuery:
    """One screen-resolution Datashader result and its source metadata."""

    delta: np.ndarray
    valid: np.ndarray
    bounds: Bounds
    start_year: int
    end_year: int
    overview_level: int
    source_bytes: int
    source_pixels: int
    elapsed_seconds: float
    backend: str


def query_viewport(
    start_year: int, end_year: int, bounds: Bounds, *, plot_width: int, plot_height: int
) -> ViewportQuery:
    """Range-read a suitable COG overview and rasterize it to screen resolution."""
    started = perf_counter()
    bounds = fit_bounds_to_aspect(bounds, plot_width / plot_height)
    overview_level = overview_level_for(bounds, plot_width, plot_height)
    if overview_level == 0 and icechunk_source.configured():
        change = icechunk_source.query_change(start_year, end_year, bounds)
    else:
        change = cog.query_change(start_year, end_year, bounds, overview_level)
    west, south, east, north = bounds
    rows, columns = change.delta.shape
    x_step = (east - west) / columns
    y_step = (north - south) / rows
    longitude = np.linspace(west + x_step / 2, east - x_step / 2, columns)
    latitude = np.linspace(north - y_step / 2, south + y_step / 2, rows)
    source = xr.DataArray(
        change.delta,
        coords={"latitude": latitude, "longitude": longitude},
        dims=("latitude", "longitude"),
        name="biomass_change",
    )
    canvas = ds.Canvas(
        plot_width=plot_width, plot_height=plot_height, x_range=(west, east), y_range=(south, north)
    )
    raster = canvas.raster(source, agg="mean", interpolate="nearest")
    delta = np.asarray(raster.values, dtype=np.float32)
    raster_latitude = np.asarray(raster.coords["latitude"].values)
    if raster_latitude[0] < raster_latitude[-1]:
        delta = np.flipud(delta)
    delta = np.ascontiguousarray(delta)
    valid = np.isfinite(delta)
    delta.setflags(write=False)
    valid.setflags(write=False)
    return ViewportQuery(
        delta=delta,
        valid=valid,
        bounds=bounds,
        start_year=start_year,
        end_year=end_year,
        overview_level=overview_level,
        source_bytes=change.source_bytes,
        source_pixels=change.valid_pixels,
        elapsed_seconds=perf_counter() - started,
        backend=change.backend,
    )
