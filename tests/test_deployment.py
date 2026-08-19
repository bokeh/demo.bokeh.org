"""Test alignment between the container build and ECS task definition."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_runtime_dependencies_preserve_free_threading_after_application_import() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert '"pandas>=3,<4"' in project
    assert "import asgi, sys, sysconfig;" in workflow


def test_ecs_task_uses_arm64_fargate() -> None:
    task = json.loads((ROOT / "deploy" / "ecs-task-definition.json").read_text())

    assert task["requiresCompatibilities"] == ["FARGATE"]
    assert task["runtimePlatform"] == {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"}


def test_monitor_receives_only_numeric_task_limits_and_needs_no_task_role() -> None:
    task = json.loads((ROOT / "deploy" / "ecs-task-definition.json").read_text())
    environment = {
        item["name"]: item["value"] for item in task["containerDefinitions"][0]["environment"]
    }

    assert environment["DEMO_MONITOR_TASK_CPU_LIMIT"] == "1"
    assert environment["DEMO_MONITOR_TASK_MEMORY_LIMIT_MIB"] == "2048"
    assert "taskRoleArn" not in task


def test_deployment_builds_the_matching_arm64_image() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()

    assert "docker/setup-qemu-action@v3" in workflow
    assert "docker/setup-buildx-action@v3" in workflow
    assert "docker buildx build --platform linux/arm64" in workflow


def test_deployment_smoke_checks_the_catalog_and_websocket() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    smoke = (ROOT / "scripts" / "smoke_production.py").read_text()

    assert "python scripts/smoke_production.py" in workflow
    assert 'route = "/airport-access"' in smoke
    assert "Sec-WebSocket-Protocol: bokeh" in smoke
    assert 'urljoin(base_url, "/sitemap.xml")' in smoke
