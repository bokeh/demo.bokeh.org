"""Test anonymous process-local activity measurements."""

from __future__ import annotations

from bokeh.document import Document

from apps._common.activity import PublicActivity


def test_activity_counts_only_live_sessions_and_recent_request_times() -> None:
    activity = PublicActivity(window_seconds=60)
    first = Document()
    second = Document()
    activity.track_session(first)
    activity.track_session(second)
    activity.record_request(now=40)
    activity.record_request(now=70)

    snapshot = activity.snapshot(now=110)

    assert snapshot.active_sessions == 2
    assert snapshot.requests_per_minute == 1
    next(iter(first.session_destroyed_callbacks))(None)
    assert activity.snapshot(now=110).active_sessions == 1
