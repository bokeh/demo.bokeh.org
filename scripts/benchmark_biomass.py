"""Benchmark user-visible native biomass query latency before and after startup warmup."""

from __future__ import annotations

import argparse
import json
import sys
from time import perf_counter

from apps.biomass import icechunk_source


def _timed_query() -> float:
    started = perf_counter()
    icechunk_source.query_change(
        icechunk_source.BASELINE_YEAR,
        icechunk_source.LATEST_YEAR,
        icechunk_source.DEFAULT_DETAIL_BOUNDS,
    )
    return perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimum-speedup", type=float, default=5.0)
    args = parser.parse_args()
    if not icechunk_source.configured():
        parser.error(f"{icechunk_source.TOKEN_ENV} or {icechunk_source.CLI_AUTH_ENV}=1 is required")

    icechunk_source._reset_caches_for_testing()
    cold_seconds = _timed_query()

    icechunk_source._reset_caches_for_testing()
    warmup_seconds = icechunk_source.warm_default_windows()
    warm_seconds = _timed_query()
    speedup = cold_seconds / warm_seconds
    result = {
        "cold_user_query_seconds": round(cold_seconds, 3),
        "startup_warmup_seconds": round(warmup_seconds or 0, 3),
        "startup_cached_years": icechunk_source.read_year_window.cache_info().currsize,
        "warmed_user_query_seconds": round(warm_seconds, 3),
        "user_query_speedup": round(speedup, 2),
        "minimum_speedup": args.minimum_speedup,
        "passed": speedup >= args.minimum_speedup,
    }
    sys.stdout.write(f"{json.dumps(result, sort_keys=True)}\n")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
