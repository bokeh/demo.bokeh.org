"""Test the sanitized service-wide monitor exchange."""

from __future__ import annotations

from dataclasses import replace

import pytest

from apps._common.performance import (
    PUBLIC_APP_ROUTES,
    PUBLIC_CALLBACKS_BY_ROUTE,
    AppTiming,
    CallbackTiming,
    latency_histogram,
)
from apps.monitor.global_metrics import (
    DynamoHeartbeatStore,
    Heartbeat,
    ServiceMonitor,
    aggregate_heartbeats,
    decode_heartbeat,
    encode_heartbeat,
)
from apps.monitor.metrics import CoalescedSampler, SystemSample


def heartbeat(*, published_at: float = 100, cpu_percent: float = 50) -> Heartbeat:
    callback_histogram = latency_histogram([1.0, 2.0, 4.0, 8.0])
    loop_histogram = latency_histogram([0.5, 1.0, 2.0])
    return Heartbeat(
        published_at=published_at,
        expires_at=280,
        cpu_percent=cpu_percent,
        cpu_capacity_vcpus=1.0,
        memory_bytes=512 * 1024 * 1024,
        memory_capacity_bytes=2 * 1024 * 1024 * 1024,
        rx_bytes_per_second=2048,
        tx_bytes_per_second=1024,
        active_sessions=3,
        page_entries_per_minute=12,
        callback_count=4,
        callback_window_seconds=60,
        callback_max_ms=8.0,
        callback_histogram=callback_histogram,
        event_loop_max_ms=2.0,
        event_loop_histogram=loop_histogram,
        callbacks_by_app=(
            AppTiming("/market-monitor", 4, 8.0, 8.0, callback_histogram),
        ),
        event_loop_by_app=(
            AppTiming("/market-monitor", 3, 2.0, 2.0, loop_histogram),
        ),
        slowest_callbacks=(
            CallbackTiming("/market-monitor", "advance", 4, 8.0, 8.0, callback_histogram),
        ),
    )


def test_heartbeat_round_trip_preserves_only_public_aggregates() -> None:
    original = heartbeat()

    encoded = encode_heartbeat(original)
    decoded = decode_heartbeat(encoded)

    assert len(encoded) < 1024
    assert decoded == original


def test_maximum_public_tables_keep_the_compressed_payload_below_one_kibibyte() -> None:
    histogram = latency_histogram([0.5, 1, 2, 4, 8, 16, 32, 64])
    apps = tuple(
        AppTiming(route, 8, 64, 64, histogram) for route in sorted(PUBLIC_APP_ROUTES)[:8]
    )
    callback_labels = (
        (route, callback)
        for route, callbacks in sorted(PUBLIC_CALLBACKS_BY_ROUTE.items())
        for callback in sorted(callbacks)
    )
    callbacks = tuple(
        CallbackTiming(route, callback, 8, 64, 64, histogram)
        for route, callback in list(callback_labels)[:12]
    )
    maximum = replace(
        heartbeat(),
        callbacks_by_app=apps,
        event_loop_by_app=apps,
        slowest_callbacks=callbacks,
    )

    assert len(encode_heartbeat(maximum)) < 900


def test_decoder_rejects_non_public_labels() -> None:
    private = replace(
        heartbeat(),
        callbacks_by_app=(AppTiming("arn:aws:ecs:private", 1, 1, 1, latency_histogram([1])),),
    )

    with pytest.raises(ValueError, match="non-public route"):
        decode_heartbeat(encode_heartbeat(private))


def test_service_aggregate_sums_capacity_and_merges_histograms() -> None:
    first = heartbeat(cpu_percent=50)
    second = replace(
        heartbeat(cpu_percent=100),
        active_sessions=5,
        page_entries_per_minute=8,
        memory_bytes=1024 * 1024 * 1024,
    )

    sample = aggregate_heartbeats(
        (first, second),
        generation=4,
        now=110,
        source_label="Live aggregate from reporting ECS tasks",
        deterministic=False,
    )

    assert sample.status == "ok"
    assert sample.reporting_tasks == 2
    assert sample.active_sessions == 8
    assert sample.page_entries_per_minute == 20
    assert sample.cpu_vcpus == pytest.approx(1.5)
    assert sample.cpu_percent == pytest.approx(75)
    assert sample.memory_bytes == 1536 * 1024 * 1024
    assert sample.memory_percent == pytest.approx(37.5)
    assert sample.rx_bytes_per_second == 4096
    assert sample.callback_rate == pytest.approx(8 / 60)
    assert sample.callback_p95_ms == 8
    assert sample.callbacks_by_app[0].count == 8
    assert sample.slowest_callbacks[0].callback == "advance"


def test_service_monitor_ignores_stale_rows_before_ttl_deletes_them() -> None:
    class Adapter:
        def sample(self, *, now: float) -> SystemSample:
            del now
            return SystemSample(
                "Live test process", "process", False, 25, 10, None, 1, 100, 2, 1
            )

    class Store:
        source_label = "Test service"
        deterministic = False

        def put(self, _publisher: str, _row: Heartbeat) -> None:
            return None

        def read(self) -> tuple[Heartbeat, ...]:
            return (heartbeat(published_at=1),)

    sample = ServiceMonitor(CoalescedSampler(Adapter()), Store()).tick(now=100, sampled_at=10)

    assert sample.status == "degraded"
    assert sample.reason == "no_fresh_heartbeats"
    assert sample.reporting_tasks == 0


class DynamoClient:
    def __init__(self) -> None:
        self.put: dict | None = None
        self.scan_arguments: dict | None = None

    def put_item(self, **arguments) -> None:
        self.put = arguments

    def scan(self, **arguments):
        self.scan_arguments = arguments
        assert self.put is not None
        return {"Items": [{"payload": self.put["Item"]["payload"]}]}


def test_dynamo_store_never_reads_or_returns_publisher_keys() -> None:
    client = DynamoClient()
    store = DynamoHeartbeatStore("monitor-table", client=client)

    store.put("opaque-private-publisher", heartbeat())
    rows = store.read()

    assert rows == (heartbeat(),)
    assert client.scan_arguments == {
        "TableName": "monitor-table",
        "ProjectionExpression": "payload",
        "ConsistentRead": False,
        "Limit": 32,
    }
    assert client.put is not None
    assert "opaque-private-publisher" not in repr(rows)


def test_service_monitor_reads_store_only_during_coalesced_tick() -> None:
    class Adapter:
        def sample(self, *, now: float) -> SystemSample:
            del now
            return SystemSample(
                source_label="Live test process",
                scope="process",
                deterministic=False,
                cpu_percent=25,
                memory_bytes=10,
                memory_percent=None,
                cpu_capacity_vcpus=1,
                memory_capacity_bytes=100,
                rx_bytes_per_second=2,
                tx_bytes_per_second=1,
            )

    class Store:
        source_label = "Test service"
        deterministic = False
        reads = 0
        row: Heartbeat | None = None

        def put(self, _publisher: str, row: Heartbeat) -> None:
            self.row = row

        def read(self) -> tuple[Heartbeat, ...]:
            self.reads += 1
            return () if self.row is None else (self.row,)

    store = Store()
    monitor = ServiceMonitor(CoalescedSampler(Adapter()), store)

    updated = monitor.tick(now=100, sampled_at=10)
    first_viewer = monitor.sample()
    second_viewer = monitor.sample()

    assert updated.reporting_tasks == 1
    assert first_viewer is second_viewer
    assert store.reads == 1
