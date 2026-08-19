"""Count anonymous process-local activity for the public monitor."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any
from weakref import WeakSet, ref


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    """Anonymous activity totals from the current Python process."""

    active_sessions: int
    requests_per_minute: float


class PublicActivity:
    """Keep bounded numeric activity without retaining request details."""

    def __init__(self, *, window_seconds: float = 60.0) -> None:
        self._window_seconds = window_seconds
        self._requests: deque[float] = deque()
        self._sessions: WeakSet[Any] = WeakSet()
        self._lock = Lock()

    def record_request(self, *, now: float | None = None) -> None:
        """Record only when a request happened, never what it contained."""
        timestamp = monotonic() if now is None else now
        with self._lock:
            self._requests.append(timestamp)
            self._prune_requests(timestamp)

    def track_session(self, document: Any) -> None:
        """Count a live Bokeh document until its session is destroyed."""
        document_ref = ref(document)
        with self._lock:
            self._sessions.add(document)

        def session_destroyed(_session_context: Any) -> None:
            if tracked := document_ref():
                with self._lock:
                    self._sessions.discard(tracked)

        document.on_session_destroyed(session_destroyed)

    def snapshot(self, *, now: float | None = None) -> ActivitySnapshot:
        """Return active sessions and a rolling one-minute request rate."""
        timestamp = monotonic() if now is None else now
        with self._lock:
            self._prune_requests(timestamp)
            return ActivitySnapshot(
                active_sessions=len(self._sessions),
                requests_per_minute=len(self._requests) * 60 / self._window_seconds,
            )

    def _prune_requests(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()


PUBLIC_ACTIVITY = PublicActivity()
