"""Test the public monitor's adapters, coalescing, and browser boundary."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from urllib.request import Request

import pytest
from bokeh.document import Document

from apps._common.performance import PublicPerformance
from apps.monitor import build_document
from apps.monitor.global_metrics import InMemoryHeartbeatStore, ServiceMonitor
from apps.monitor.metrics import (
    CoalescedSampler,
    DeterministicAdapter,
    EcsTaskStatsAdapter,
    SystemSample,
    create_adapter,
)

ACCOUNT_ID = "123456789012"
TASK_ARN = f"arn:aws:ecs:us-east-1:{ACCOUNT_ID}:task/private-cluster/secret"
METADATA_URI = "http://169.254.170.2/v4/private-token"


class Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.body


class Opener:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[Request] = []

    def __call__(self, request: Request, *, timeout: float) -> Response:
        assert timeout == 0.25
        self.requests.append(request)
        return Response(self.payload)


def task_stats() -> dict[str, Any]:
    return {
        TASK_ARN: {
            "name": "private-container-name",
            "id": "private-container-id",
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2_000_000_000},
                "system_cpu_usage": 100_000_000_000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "system_cpu_usage": 96_000_000_000,
            },
            "memory_stats": {"usage": 512 * 1024 * 1024},
            "network_rate_stats": {"rx_bytes_per_sec": 2048, "tx_bytes_per_sec": 1024},
            "networks": {"eth0": {"rx_bytes": 9000, "tx_bytes": 5000}},
        }
    }


def ecs_adapter(payload: dict[str, Any] | None = None) -> tuple[EcsTaskStatsAdapter, Opener]:
    opener = Opener(task_stats() if payload is None else payload)
    adapter = EcsTaskStatsAdapter(METADATA_URI, cpu_limit=1, memory_limit_mib=2048, opener=opener)
    return adapter, opener


def test_ecs_adapter_extracts_only_sanitized_numeric_task_measurements() -> None:
    adapter, opener = ecs_adapter()

    sample = adapter.sample(now=10)

    assert sample.scope == "task"
    assert sample.cpu_percent == pytest.approx(100)
    assert sample.memory_bytes == 512 * 1024 * 1024
    assert sample.memory_percent == pytest.approx(25)
    assert sample.rx_bytes_per_second == 2048
    assert sample.tx_bytes_per_second == 1024
    assert opener.requests[0].full_url == f"{METADATA_URI}/task/stats"
    serialized = json.dumps(asdict(sample))
    assert ACCOUNT_ID not in serialized
    assert TASK_ARN not in serialized
    assert "private-container" not in serialized
    assert METADATA_URI not in serialized


def test_ecs_adapter_rejects_non_link_local_sources() -> None:
    with pytest.raises(ValueError, match="link-local"):
        EcsTaskStatsAdapter("https://example.com/task-token", cpu_limit=1, memory_limit_mib=2048)


def test_sampler_coalesces_viewers_into_one_source_read() -> None:
    class CountingAdapter:
        calls = 0

        def sample(self, *, now: float) -> SystemSample:
            self.calls += 1
            return SystemSample(
                source_label="Live test measurements",
                scope="process",
                deterministic=False,
                cpu_percent=now,
                memory_bytes=1,
                memory_percent=None,
                cpu_capacity_vcpus=None,
                memory_capacity_bytes=None,
                rx_bytes_per_second=None,
                tx_bytes_per_second=None,
            )

    adapter = CountingAdapter()
    sampler = CoalescedSampler(
        adapter,
        performance=PublicPerformance(),
        interval_seconds=2,
        fallback=DeterministicAdapter(),
    )

    first = sampler.sample(now=10, wall_time=100)
    same_generation = sampler.sample(now=11.9, wall_time=101.9)
    second = sampler.sample(now=12, wall_time=102)

    assert adapter.calls == 2
    assert first.deterministic is False
    assert same_generation is first
    assert second.generation == first.generation + 1


def test_explicit_deterministic_source_is_clearly_labeled() -> None:
    adapter = create_adapter({"DEMO_MONITOR_SOURCE": "deterministic"})
    sample = adapter.sample(now=0)

    assert sample.deterministic is True
    assert "Deterministic" in sample.source_label
    assert sample.scope == "simulated"


def test_document_serialization_never_contains_aws_or_container_identifiers() -> None:
    adapter, _opener = ecs_adapter()
    performance = PublicPerformance(window_seconds=1e10)
    performance.record_callback(4.2, route="/market-monitor", callback="advance", now=1.0)
    performance.record_callback(99.0, route=TASK_ARN, callback="private-container-name", now=1.0)
    performance.record_event_loop(2.1, route="/market-monitor", now=1.0)
    sampler = CoalescedSampler(adapter, performance=performance)
    service_monitor = ServiceMonitor(sampler, InMemoryHeartbeatStore())
    service_monitor.tick(now=100, sampled_at=2.0)
    document = Document()

    build_document(document, service_monitor)

    history = document.select_one({"name": "monitor-history"})
    assert history is not None
    assert len(history.data["time"]) == 1
    assert len(document.session_callbacks) == 1
    assert document.session_callbacks[0].period == 2_000
    serialized = json.dumps(document.to_json(), default=str)
    assert ACCOUNT_ID not in serialized
    assert TASK_ARN not in serialized
    assert "private-container" not in serialized
    assert METADATA_URI not in serialized
    assert "ECS_CONTAINER_METADATA_URI_V4" not in serialized
    assert "monitor-task-source" not in serialized
    assert "Current" not in serialized
    assert "this task or local container" not in serialized
    assert "Callbacks across fresh tasks" not in serialized
    assert "/market-monitor" in serialized
    assert "advance" in serialized
