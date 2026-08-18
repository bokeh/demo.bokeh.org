"""Define the synthetic workloads and Bokeh-independent scheduler state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

import numpy as np

SEED = 3102026
STEP_SECONDS = 0.55
STRAGGLER_DELAY = 18.0
WORKER_OUTAGE = 16.0

type TaskStatus = Literal["Waiting", "Ready", "Running", "Complete"]
type WorkloadName = Literal[
    "Satellite mosaic",
    "Demand forecast",
    "Genomics cohort",
    "Storm forecast ensemble",
    "Particle detector",
    "Portfolio stress test",
    "Film render",
    "Search index rebuild",
]


@dataclass(frozen=True)
class Workload:
    """Describe the stages and explanatory note for a synthetic workload."""

    stages: tuple[tuple[str, int, float], ...]
    note: str


class Task(TypedDict):
    """Store mutable state for one simulated task."""

    id: int
    name: str
    stage: str
    stage_index: int
    dependencies: tuple[int, ...]
    duration: float
    remaining: float
    status: TaskStatus
    worker: str | None
    attempt: int
    straggler: bool
    injected_delay: float
    bar: int | None


class WorkerState(TypedDict):
    """Store the current assignment and outage window for one worker."""

    name: str
    task: int | None
    offline_until: float


@dataclass
class SchedulerState:
    """Collect the mutable state for one scheduler session."""

    tasks: list[Task]
    edges: list[tuple[int, int]]
    critical_path: set[int]
    workers: list[WorkerState]
    clock: float
    cycles_completed: int
    rng: np.random.Generator


WORKLOADS: dict[WorkloadName, Workload] = {
    "Satellite mosaic": Workload(
        stages=(
            ("Load scenes", 8, 2.8),
            ("Calibrate", 12, 4.4),
            ("Reproject", 12, 5.8),
            ("Blend tiles", 8, 6.2),
            ("Build pyramid", 5, 4.8),
            ("Publish", 1, 3.2),
        ),
        note="Scenes fan out through calibration and reprojection, then converge into a multiresolution mosaic.",
    ),
    "Demand forecast": Workload(
        stages=(
            ("Read partitions", 10, 2.4),
            ("Clean features", 10, 3.6),
            ("Fit regions", 8, 7.2),
            ("Score horizon", 12, 3.8),
            ("Reconcile", 5, 5.4),
            ("Export", 1, 2.6),
        ),
        note="Regional models run in parallel before a reconciliation step enforces a consistent national forecast.",
    ),
    "Genomics cohort": Workload(
        stages=(
            ("Read samples", 12, 2.2),
            ("Align reads", 12, 6.8),
            ("Call variants", 10, 6.0),
            ("Joint genotype", 6, 8.0),
            ("Annotate", 5, 4.4),
            ("Summarize", 1, 3.0),
        ),
        note="Sample-level work stays parallel until joint genotyping combines the cohort into shared variant calls.",
    ),
    "Storm forecast ensemble": Workload(
        stages=(
            ("Ingest observations", 1, 4.0),
            ("Run members", 20, 8.2),
            ("Extract tracks", 20, 3.4),
            ("Cluster outcomes", 6, 5.8),
            ("Build probabilities", 3, 4.6),
            ("Issue forecast", 1, 2.4),
        ),
        note="One analysis fans out into twenty ensemble members, then contracts into track clusters and forecast probabilities.",
    ),
    "Particle detector": Workload(
        stages=(
            ("Decode events", 18, 2.0),
            ("Cluster hits", 24, 3.2),
            ("Fit tracks", 14, 5.6),
            ("Find vertices", 7, 6.6),
            ("Classify events", 7, 3.8),
            ("Write dataset", 1, 3.0),
        ),
        note="Detector events widen into many hit-clustering tasks before track fitting and vertex reconstruction reduce the result.",
    ),
    "Portfolio stress test": Workload(
        stages=(
            ("Load positions", 1, 2.8),
            ("Generate scenarios", 16, 2.2),
            ("Reprice portfolio", 16, 7.4),
            ("Aggregate desks", 8, 3.8),
            ("Compute risk", 4, 4.6),
            ("Publish report", 1, 2.4),
        ),
        note="A single portfolio snapshot fans out across market scenarios; desk-level losses then roll up into firm-wide risk.",
    ),
    "Film render": Workload(
        stages=(
            ("Load assets", 6, 3.4),
            ("Render frames", 24, 8.8),
            ("Denoise frames", 24, 4.2),
            ("Composite shots", 8, 6.0),
            ("Encode reels", 3, 4.8),
            ("Package delivery", 1, 2.6),
        ),
        note="Shared assets feed a wide render farm; completed frames are denoised independently before shots and reels converge.",
    ),
    "Search index rebuild": Workload(
        stages=(
            ("Read documents", 16, 2.4),
            ("Parse content", 16, 3.0),
            ("Build segments", 10, 5.4),
            ("Merge shards", 5, 7.6),
            ("Validate index", 2, 4.0),
            ("Swap index", 1, 1.8),
        ),
        note="Documents stay highly parallel through parsing, then merge into progressively fewer immutable index shards.",
    ),
}


def make_tasks(workload: Workload) -> tuple[list[Task], list[tuple[int, int]]]:
    """Build a reproducible task graph for a workload."""
    rng = np.random.default_rng(SEED)
    tasks: list[Task] = []
    stage_ids: list[list[int]] = []
    edges: list[tuple[int, int]] = []

    for stage_index, (stage_name, count, base_duration) in enumerate(workload.stages):
        current: list[int] = []
        previous = stage_ids[-1] if stage_ids else []
        for index in range(count):
            task_id = len(tasks)
            if not previous:
                dependencies: tuple[int, ...] = ()
            elif count == 1:
                dependencies = tuple(previous)
            else:
                candidates = {previous[index % len(previous)]}
                if len(previous) > 1 and index % 3 == 0:
                    candidates.add(previous[(index * 3 + 1) % len(previous)])
                dependencies = tuple(sorted(candidates))
            duration = base_duration * rng.uniform(0.72, 1.34)
            tasks.append(
                {
                    "id": task_id,
                    "name": f"{stage_name.lower().replace(' ', '-')}-{index + 1:02d}",
                    "stage": stage_name,
                    "stage_index": stage_index,
                    "dependencies": dependencies,
                    "duration": duration,
                    "remaining": duration,
                    "status": "Waiting",
                    "worker": None,
                    "attempt": 0,
                    "straggler": False,
                    "injected_delay": 0.0,
                    "bar": None,
                }
            )
            edges.extend((dependency, task_id) for dependency in dependencies)
            current.append(task_id)
        stage_ids.append(current)

    return tasks, edges


def find_critical_path(tasks: list[Task]) -> set[int]:
    """Return the longest dependency path under nominal task durations."""
    scores: dict[int, float] = {}
    parents: dict[int, int | None] = {}
    for task in tasks:
        task_id = task["id"]
        dependencies = task["dependencies"]
        if dependencies:
            parent = max(dependencies, key=lambda dependency: scores[dependency])
            scores[task_id] = scores[parent] + task["duration"]
            parents[task_id] = parent
        else:
            scores[task_id] = task["duration"]
            parents[task_id] = None

    path: set[int] = set()
    current: int | None = max(scores, key=scores.__getitem__)
    while current is not None:
        path.add(current)
        current = parents[current]
    return path
