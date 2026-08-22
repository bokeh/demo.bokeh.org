"""Build the tile-aligned biomass overview pyramid in an Arraylake repository."""

from __future__ import annotations

import argparse
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any

import numpy as np
import zarr
from arraylake import Client
from numcodecs import Blosc
from zarr.codecs import BloscCodec

from apps.biomass import cog, shading
from apps.biomass.icechunk_source import DEFAULT_REPO, OVERVIEW_TILE_SIZE, VALID_MAX, VALID_MIN

LOGGER = logging.getLogger("biomass-overviews")
SOURCE_REPO = "bokeh/aboveground_biomass_100m_global_open-subscription"
TILE_SIZE = OVERVIEW_TILE_SIZE
MIN_ZOOM = 0
MAX_ZOOM = 4
YEAR_COUNT = cog.LATEST_YEAR - cog.BASELINE_YEAR + 1
FILL_VALUE = cog.NO_DATA
CODEC = Blosc(cname="zstd", clevel=7, shuffle=Blosc.BITSHUFFLE)
ZARR_CODEC = BloscCodec(cname="zstd", clevel=7, shuffle="bitshuffle")
RASTERIZE_LOCK = Lock()


@dataclass(frozen=True)
class BuiltTile:
    year: int
    zoom: int
    column: int
    row: int
    values: np.ndarray
    source_bytes: int
    compressed_bytes: int


def _client() -> Client:
    token = os.environ.get("ARRAYLAKE_API_TOKEN")
    return (
        Client(token=token, cache_credentials=False) if token else Client(cache_credentials=False)
    )


def _parse_years(value: str) -> list[int]:
    if value == "all":
        return list(range(cog.BASELINE_YEAR, cog.LATEST_YEAR + 1))
    years: list[int] = []
    for part in value.split(","):
        if ":" in part:
            start, end = (int(item) for item in part.split(":", maxsplit=1))
            years.extend(range(start, end + 1))
        else:
            years.append(int(part))
    result = sorted(set(years))
    invalid = [year for year in result if not cog.BASELINE_YEAR <= year <= cog.LATEST_YEAR]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"years must be between {cog.BASELINE_YEAR} and {cog.LATEST_YEAR}: {invalid}"
        )
    return result


def _initialize(repo: Any) -> None:
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    if "agb" in root:
        return
    root.attrs.update(
        {
            "title": "CTrees aboveground biomass Web Mercator overviews",
            "source_repository": SOURCE_REPO,
            "source_dataset": "CTrees Global Aboveground Biomass 100m",
            "projection": "EPSG:3857",
            "tile_matrix_set": "WebMercatorQuad",
            "tile_size": TILE_SIZE,
            "min_zoom": MIN_ZOOM,
            "max_zoom": MAX_ZOOM,
            "storage_budget_bytes": 10_000_000_000,
            "completed_years": [],
            "estimated_compressed_bytes_by_year": {},
        }
    )
    root.create_array(
        "year",
        data=np.arange(cog.BASELINE_YEAR, cog.LATEST_YEAR + 1, dtype=np.int16),
        chunks=(YEAR_COUNT,),
        compressors=[ZARR_CODEC],
        dimension_names=("year",),
    )
    group = root.create_group("agb")
    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
        side = TILE_SIZE * (1 << zoom)
        group.create_array(
            f"z{zoom}",
            shape=(YEAR_COUNT, side, side),
            chunks=(1, TILE_SIZE, TILE_SIZE),
            dtype=np.int16,
            fill_value=FILL_VALUE,
            compressors=[ZARR_CODEC],
            dimension_names=("year", "y", "x"),
            attributes={
                "long_name": "Above Ground Biomass",
                "units": "Mg ha-1",
                "scale_factor": 0.1,
                "valid_min": VALID_MIN,
                "valid_max": VALID_MAX,
                "_FillValue": FILL_VALUE,
                "projection": "EPSG:3857",
                "zoom": zoom,
                "tile_size": TILE_SIZE,
            },
        )
    snapshot = session.commit("Initialize tile-aligned z0-z4 biomass overview pyramid")
    LOGGER.info("Initialized %s at snapshot %s", DEFAULT_REPO, snapshot)


def _build_tile(year: int, zoom: int, column: int, row: int) -> BuiltTile:
    bounds = shading.tile_bounds(zoom, column, row)
    source_level = 8 - zoom
    source = cog.read_year_window(year, bounds, source_level)
    values = source.values.astype(np.float32)
    values[(values < VALID_MIN) | (values > VALID_MAX)] = np.nan
    # Numba's default workqueue backend cannot enter Datashader concurrently.
    # Keep the remote COG reads parallel and serialize only the projection kernel.
    with RASTERIZE_LOCK:
        raster, valid = shading.rasterize_values(
            values, bounds, shading._tile_mercator_bounds(zoom, column, row), tile_size=TILE_SIZE
        )
    encoded = np.full(raster.shape, FILL_VALUE, dtype=np.int16)
    encoded[valid] = np.clip(np.rint(raster[valid]), VALID_MIN, VALID_MAX).astype(np.int16)
    encoded.setflags(write=False)
    return BuiltTile(
        year=year,
        zoom=zoom,
        column=column,
        row=row,
        values=encoded,
        source_bytes=source.source_bytes,
        compressed_bytes=len(CODEC.encode(encoded)),
    )


def _tasks(year: int) -> list[tuple[int, int, int, int]]:
    return [
        (year, zoom, column, row)
        for zoom in range(MIN_ZOOM, MAX_ZOOM + 1)
        for row in range(1 << zoom)
        for column in range(1 << zoom)
    ]


def _finest_tasks(year: int) -> list[tuple[int, int, int, int]]:
    return [
        (year, MAX_ZOOM, column, row)
        for row in range(1 << MAX_ZOOM)
        for column in range(1 << MAX_ZOOM)
    ]


def _downsample_2x(values: np.ndarray, tile_size: int = TILE_SIZE) -> np.ndarray:
    """Average a 2x2 Web Mercator pixel block without spreading fill values."""
    expected = tile_size * 2
    if values.shape != (expected, expected):
        raise ValueError(f"source tile must have shape {(expected, expected)}")
    blocks = values.reshape(tile_size, 2, tile_size, 2)
    valid = (blocks >= VALID_MIN) & (blocks <= VALID_MAX)
    counts = valid.sum(axis=(1, 3))
    totals = np.where(valid, blocks, 0).sum(axis=(1, 3), dtype=np.int64)
    reduced = np.full((tile_size, tile_size), FILL_VALUE, dtype=np.int16)
    comparable = counts > 0
    reduced[comparable] = np.rint(totals[comparable] / counts[comparable]).astype(np.int16)
    reduced.setflags(write=False)
    return reduced


def _derive_tile(root: Any, year: int, zoom: int, column: int, row: int) -> BuiltTile:
    """Derive one coarse tile from four pixels of the next-finer Mercator level."""
    year_index = year - cog.BASELINE_YEAR
    source_size = TILE_SIZE * 2
    y0 = row * source_size
    x0 = column * source_size
    values = np.asarray(
        root["agb"][f"z{zoom + 1}"][year_index, y0 : y0 + source_size, x0 : x0 + source_size],
        dtype=np.int16,
    )
    reduced = _downsample_2x(values)
    return BuiltTile(
        year=year,
        zoom=zoom,
        column=column,
        row=row,
        values=reduced,
        source_bytes=values.nbytes,
        compressed_bytes=len(CODEC.encode(reduced)),
    )


def _write_coarse_levels(root: Any, year: int, workers: int) -> tuple[int, int]:
    """Build z3 through z0 progressively from the accurately projected z4 array."""
    year_index = year - cog.BASELINE_YEAR
    source_bytes = 0
    compressed_bytes = 0
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="biomass-overview-coarsen"
    ) as pool:
        for zoom in range(MAX_ZOOM - 1, MIN_ZOOM - 1, -1):
            tasks = [
                (root, year, zoom, column, row)
                for row in range(1 << zoom)
                for column in range(1 << zoom)
            ]
            futures = [pool.submit(_derive_tile, *task) for task in tasks]
            for done, future in enumerate(as_completed(futures), start=1):
                tile = future.result()
                y0 = tile.row * TILE_SIZE
                x0 = tile.column * TILE_SIZE
                root["agb"][f"z{zoom}"][year_index, y0 : y0 + TILE_SIZE, x0 : x0 + TILE_SIZE] = (
                    tile.values
                )
                source_bytes += tile.source_bytes
                compressed_bytes += tile.compressed_bytes
                if done % 16 == 0 or done == len(tasks):
                    LOGGER.info(
                        "Year %d z%d: derived %d/%d tiles from z%d",
                        year,
                        zoom,
                        done,
                        len(tasks),
                        zoom + 1,
                    )
    return source_bytes, compressed_bytes


def _write_year(repo: Any, year: int, workers: int) -> None:
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="r+")
    completed = {int(value) for value in root.attrs.get("completed_years", [])}
    if year in completed:
        LOGGER.info("Skipping already completed year %d", year)
        return

    tasks = _finest_tasks(year)
    started = perf_counter()
    source_bytes = 0
    compressed_bytes = 0
    year_index = year - cog.BASELINE_YEAR
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="biomass-overview-build"
    ) as pool:
        futures = [pool.submit(_build_tile, *task) for task in tasks]
        for done, future in enumerate(as_completed(futures), start=1):
            tile = future.result()
            y0 = tile.row * TILE_SIZE
            x0 = tile.column * TILE_SIZE
            root["agb"][f"z{tile.zoom}"][year_index, y0 : y0 + TILE_SIZE, x0 : x0 + TILE_SIZE] = (
                tile.values
            )
            source_bytes += tile.source_bytes
            compressed_bytes += tile.compressed_bytes
            if done % 16 == 0 or done == len(tasks):
                LOGGER.info(
                    "Year %d: wrote %d/%d tiles (%.1f MiB estimated compressed)",
                    year,
                    done,
                    len(tasks),
                    compressed_bytes / 1024**2,
                )

    coarse_source_bytes, coarse_compressed_bytes = _write_coarse_levels(root, year, workers)
    source_bytes += coarse_source_bytes
    compressed_bytes += coarse_compressed_bytes
    completed.add(year)
    estimates = dict(root.attrs.get("estimated_compressed_bytes_by_year", {}))
    estimates[str(year)] = compressed_bytes
    root.attrs["completed_years"] = sorted(completed)
    root.attrs["estimated_compressed_bytes_by_year"] = estimates
    snapshot = session.commit(
        f"Add {year} biomass Web Mercator overviews ({compressed_bytes / 1024**2:.1f} MiB)"
    )
    LOGGER.info(
        "Committed %d at %s in %.1f s; source %.1f MiB, estimated compressed %.1f MiB",
        year,
        snapshot,
        perf_counter() - started,
        source_bytes / 1024**2,
        compressed_bytes / 1024**2,
    )
    cog.read_year_window.cache_clear()


def _repair_coarse_year(repo: Any, year: int, workers: int) -> None:
    """Replace distorted coarse levels with levels derived from the aligned z4 data."""
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="r+")
    repaired = {int(value) for value in root.attrs.get("coarse_pyramid_repaired_years", [])}
    if year in repaired:
        LOGGER.info("Skipping already repaired year %d", year)
        return

    started = perf_counter()
    source_bytes, compressed_bytes = _write_coarse_levels(root, year, workers)
    repaired.add(year)
    estimates = dict(root.attrs.get("coarse_compressed_bytes_by_year", {}))
    estimates[str(year)] = compressed_bytes
    root.attrs["coarse_pyramid_source_zoom"] = MAX_ZOOM
    root.attrs["coarse_pyramid_repaired_years"] = sorted(repaired)
    root.attrs["coarse_compressed_bytes_by_year"] = estimates
    snapshot = session.commit(f"Realign {year} z0-z3 overviews from Web Mercator z{MAX_ZOOM}")
    LOGGER.info(
        "Repaired %d at %s in %.1f s; read %.1f MiB and wrote %.1f MiB estimated compressed",
        year,
        snapshot,
        perf_counter() - started,
        source_bytes / 1024**2,
        compressed_bytes / 1024**2,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--years", type=_parse_years, default=_parse_years("all"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--repair-coarse",
        action="store_true",
        help="rebuild z0-z3 from the aligned z4 overview without rereading the source COGs",
    )
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 16:
        parser.error("--workers must be between 1 and 16")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo = _client().get_repo(args.repo)
    _initialize(repo)
    for year in args.years:
        if args.repair_coarse:
            _repair_coarse_year(repo, year, args.workers)
        else:
            _write_year(repo, year, args.workers)


if __name__ == "__main__":
    main()
