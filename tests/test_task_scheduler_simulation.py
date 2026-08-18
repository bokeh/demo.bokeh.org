"""Test synthetic task graph construction and critical-path analysis."""

from __future__ import annotations

import pytest

from apps.task_scheduler import WORKLOAD_NOTE_TEMPLATE
from apps.task_scheduler.simulation import WORKLOADS, Task, Workload, find_critical_path, make_tasks


def sample_workload() -> Workload:
    return Workload(
        stages=(("Read", 2, 2.0), ("Process", 3, 4.0), ("Publish", 1, 1.0)),
        note="Synthetic test workload.",
    )


def test_make_tasks_assigns_contiguous_ids_and_unique_names() -> None:
    tasks, _edges = make_tasks(sample_workload())

    assert [task["id"] for task in tasks] == list(range(6))
    assert len({task["name"] for task in tasks}) == len(tasks)
    assert [task["stage_index"] for task in tasks] == [0, 0, 1, 1, 1, 2]


def test_make_tasks_initializes_mutable_scheduler_fields() -> None:
    tasks, _edges = make_tasks(sample_workload())

    for task in tasks:
        assert task["remaining"] == task["duration"]
        assert task["status"] == "Waiting"
        assert task["worker"] is None
        assert task["attempt"] == 0
        assert not task["straggler"]
        assert task["injected_delay"] == 0
        assert task["bar"] is None


def test_make_tasks_connects_only_to_the_previous_stage() -> None:
    tasks, edges = make_tasks(sample_workload())

    assert tasks[0]["dependencies"] == tasks[1]["dependencies"] == ()
    assert tasks[2]["dependencies"] == (0, 1)
    assert tasks[3]["dependencies"] == (1,)
    assert tasks[4]["dependencies"] == (0,)
    assert tasks[5]["dependencies"] == (2, 3, 4)
    assert set(edges) == {
        (dependency, task["id"]) for task in tasks for dependency in task["dependencies"]
    }


def test_make_tasks_is_reproducible_and_returns_independent_state() -> None:
    first, first_edges = make_tasks(sample_workload())
    second, second_edges = make_tasks(sample_workload())

    assert first == second
    assert first_edges == second_edges
    first[0]["status"] = "Complete"
    assert second[0]["status"] == "Waiting"


def test_generated_durations_stay_near_each_stage_baseline() -> None:
    workload = sample_workload()
    tasks, _edges = make_tasks(workload)

    baselines = {index: stage[2] for index, stage in enumerate(workload.stages)}
    for task in tasks:
        baseline = baselines[task["stage_index"]]
        assert baseline * 0.72 <= task["duration"] <= baseline * 1.34


@pytest.mark.parametrize("name", list(WORKLOADS))
def test_every_workload_builds_a_valid_acyclic_graph(name: str) -> None:
    workload = WORKLOADS[name]
    tasks, edges = make_tasks(workload)

    assert len(tasks) == sum(count for _stage, count, _duration in workload.stages)
    assert len(edges) == sum(len(task["dependencies"]) for task in tasks)
    assert all(dependency < task["id"] for task in tasks for dependency in task["dependencies"])
    assert all(task["dependencies"] for task in tasks if task["stage_index"] > 0)
    assert find_critical_path(tasks) <= {task["id"] for task in tasks}
    assert tasks[-1]["id"] in find_critical_path(tasks)


def test_find_critical_path_uses_accumulated_duration() -> None:
    tasks: list[Task] = [
        task(0, 2, ()),
        task(1, 3, ()),
        task(2, 5, (0,)),
        task(3, 10, (1,)),
        task(4, 1, (2, 3)),
    ]

    assert find_critical_path(tasks) == {1, 3, 4}


def test_find_critical_path_handles_a_single_task() -> None:
    assert find_critical_path([task(0, 2, ())]) == {0}


def test_find_critical_path_rejects_an_empty_graph() -> None:
    with pytest.raises(ValueError, match="empty"):
        find_critical_path([])


def test_scheduler_templates_escape_workload_text() -> None:
    html = WORKLOAD_NOTE_TEMPLATE.render(name="<workload>", note="<script>bad</script>")

    assert "&lt;workload&gt;" in html
    assert "&lt;script&gt;bad&lt;/script&gt;" in html
    assert "<script>" not in html


def task(task_id: int, duration: float, dependencies: tuple[int, ...]) -> Task:
    return {
        "id": task_id,
        "name": f"task-{task_id}",
        "stage": "Test",
        "stage_index": 0,
        "dependencies": dependencies,
        "duration": duration,
        "remaining": duration,
        "status": "Waiting",
        "worker": None,
        "attempt": 0,
        "straggler": False,
        "injected_delay": 0,
        "bar": None,
    }
