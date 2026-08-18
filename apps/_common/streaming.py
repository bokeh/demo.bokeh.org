"""Helpers for bounded real-time simulation updates."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter


@dataclass(slots=True)
class PeriodicCoalescer:
    """Convert delayed periodic callbacks into one bounded batch of simulation ticks."""

    interval_seconds: float
    max_ticks: int = 4
    last_call: float | None = None

    def due_ticks(self, *, now: float | None = None) -> int:
        """Return elapsed ticks while dropping excess backlog after a long stall."""
        current = perf_counter() if now is None else now
        if self.last_call is None:
            self.last_call = current
            return 1
        elapsed = max(0.0, current - self.last_call)
        self.last_call = current
        ticks = max(1, int(elapsed / self.interval_seconds + 0.5))
        return min(ticks, self.max_ticks)

    def reset(self, *, now: float | None = None) -> None:
        """Reset elapsed-time accounting after a simulation restart or pause."""
        self.last_call = perf_counter() if now is None else now
