"""Test shared streaming update helpers."""

from __future__ import annotations

from apps._common.streaming import PeriodicCoalescer


def test_periodic_coalescer_batches_delay_and_bounds_backlog() -> None:
    coalescer = PeriodicCoalescer(0.1, max_ticks=4)
    assert coalescer.due_ticks(now=1.0) == 1
    assert coalescer.due_ticks(now=1.1) == 1
    assert coalescer.due_ticks(now=1.4) == 3
    assert coalescer.due_ticks(now=2.4) == 4


def test_periodic_coalescer_reset_discards_elapsed_time() -> None:
    coalescer = PeriodicCoalescer(0.2)
    coalescer.due_ticks(now=1.0)
    coalescer.reset(now=3.0)
    assert coalescer.due_ticks(now=3.2) == 1
