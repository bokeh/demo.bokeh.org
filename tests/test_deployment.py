"""Test alignment between the container build and ECS task definition."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_ecs_task_uses_arm64_fargate() -> None:
    task = json.loads((ROOT / "deploy" / "ecs-task-definition.json").read_text())

    assert task["requiresCompatibilities"] == ["FARGATE"]
    assert task["runtimePlatform"] == {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"}


def test_deployment_builds_the_matching_arm64_image() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()

    assert "docker/setup-qemu-action@v3" in workflow
    assert "docker/setup-buildx-action@v3" in workflow
    assert "docker buildx build --platform linux/arm64" in workflow
