"""Visualize a synthetic task scheduler, worker stream, and dependency graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
from bokeh.layouts import column
from bokeh.models import (
    Button,
    ColumnDataSource,
    Div,
    FactorRange,
    HoverTool,
    Label,
    NodesAndLinkedEdges,
    Range1d,
    Select,
    Slider,
    StaticLayoutProvider,
    Title,
    Toggle,
)
from bokeh.plotting import figure
from jinja2 import Environment, FileSystemLoader, select_autoescape

from apps._common import (
    match_background,
    monitor_document,
    prepare_document,
    responsive_row,
    style_figure,
    wrap_row,
)
from apps._common.colors import CORAL, GOLD, PAPER, PLUM, TEAL, VIOLET, WARM
from apps.task_scheduler.simulation import (
    SEED,
    STEP_SECONDS,
    STRAGGLER_DELAY,
    WORKER_OUTAGE,
    WORKLOADS,
    SchedulerState,
    Task,
    TaskStatus,
    WorkerState,
    WorkloadName,
    find_critical_path,
    make_tasks,
)

STATUS_COLORS: dict[TaskStatus, str] = {
    "Waiting": "#c9c2ba",
    "Ready": GOLD,
    "Running": CORAL,
    "Complete": TEAL,
}
STATUS_SIZES: dict[TaskStatus, int] = {"Waiting": 13, "Ready": 16, "Running": 21, "Complete": 13}
STAGE_COLORS = (TEAL, GOLD, CORAL, VIOLET, "#7f9475", "#a66c55")
DARK_GRID = "#66525f"
CHALK = "#f4ede5"
ASSETS = Path(__file__).parent
TEMPLATE_ENVIRONMENT = Environment(
    loader=FileSystemLoader(ASSETS),
    autoescape=select_autoescape(("html", "xml", "jinja")),
    trim_blocks=True,
    lstrip_blocks=True,
)
INTERRUPTION_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("interruption.html.jinja")
NOTE_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("note.html.jinja")
RUN_STATUS_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("run_status.html.jinja")
STAGE_LEGEND_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("stage_legend.html.jinja")
STATUS_LEGEND_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("status_legend.html.jinja")
TASK_DETAILS_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("task_details.html.jinja")
WORKLOAD_NOTE_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("workload_note.html.jinja")
INTRO_HTML = (ASSETS / "introduction.html").read_text()
SCHEDULER_CSS = (ASSETS / "scheduler.css").read_text()
TASK_HOVER_HTML = (ASSETS / "task_hover.html").read_text()


def modify_document(document) -> None:
    performance = monitor_document(document, "/task-scheduler")
    workload = Select(
        title="Synthetic workload",
        value="Satellite mosaic",
        options=cast(list[str | None], list(WORKLOADS)),
    )
    worker_count = Slider(title="Workers", start=2, end=8, value=5, step=1)
    playing = Toggle(label="Pause scheduler", active=True, button_type="primary")
    critical_path = Toggle(label="Show critical path", active=False)
    straggler = Button(label="Slow one running task")
    fail_worker = Button(label="Interrupt a worker")
    restart = Button(label="Restart workload")

    node_source = ColumnDataSource(data={}, name="scheduler-nodes")
    edge_source = ColumnDataSource(data={}, name="scheduler-edges")
    stream_source = ColumnDataSource(
        data={
            "run": [],
            "worker": [],
            "left": [],
            "right": [],
            "duration": [],
            "task": [],
            "stage": [],
            "attempt": [],
            "result": [],
            "color": [],
        },
        name="scheduler-task-stream",
    )
    delay_source = ColumnDataSource(
        data={"worker": [], "time": [], "event": []}, name="scheduler-delay-events"
    )
    interrupt_source = ColumnDataSource(
        data={"worker": [], "time": [], "event": []}, name="scheduler-interrupt-events"
    )

    graph_x_range = Range1d(start=-0.45, end=5.45)
    graph_title = Title(
        text="Dependency flow · tasks move left to right as prerequisites finish", text_color=CHALK
    )
    graph_plot = figure(
        title=graph_title,
        height=540,
        sizing_mode="stretch_width",
        x_range=graph_x_range,
        y_range=Range1d(start=-1.25, end=1.25),
        x_axis_location=None,
        y_axis_location=None,
        tools="tap",
        toolbar_location=None,
        name="scheduler-graph-plot",
    )
    style_figure(graph_plot)
    graph_plot.background_fill_color = PLUM
    graph_plot.border_fill_color = PLUM
    graph_plot.outline_line_color = DARK_GRID
    graph_plot.grid.visible = False

    layout_provider = StaticLayoutProvider(graph_layout={})
    graph = graph_plot.graph(
        node_source,
        edge_source,
        layout_provider,
        name="scheduler-graph",
        node_size="size",
        node_fill_color="color",
        node_fill_alpha=0.94,
        node_line_color="line_color",
        node_line_width="line_width",
        node_selection_line_color=CHALK,
        node_selection_line_width=3,
        node_nonselection_fill_alpha=0.46,
        node_nonselection_line_alpha=0.55,
        node_hover_line_color=CHALK,
        node_hover_line_width=2.5,
        edge_line_color="color",
        edge_line_alpha="alpha",
        edge_line_width="width",
        edge_selection_line_color=CHALK,
        edge_selection_line_alpha=0.9,
        edge_selection_line_width=3,
        edge_nonselection_line_alpha=0.12,
        edge_hover_line_color=CHALK,
        edge_hover_line_alpha=0.9,
        edge_hover_line_width=3,
        selection_policy=NodesAndLinkedEdges(),
        inspection_policy=NodesAndLinkedEdges(),
    )
    graph_plot.add_tools(
        HoverTool(
            renderers=[graph.node_renderer],
            tooltips=[
                ("Run", "@run"),
                ("Task", "@task"),
                ("Stage", "@stage"),
                ("State", "@status"),
                ("Nominal work", "@duration{0.0} s"),
            ],
        )
    )

    stream_x_range = Range1d(start=0, end=40)
    stream_y_range = FactorRange(factors=[f"Worker {index}" for index in range(8, 0, -1)])
    stream_title = Title(text="Worker lanes · color identifies pipeline stage", text_color=CHALK)
    stream_plot = figure(
        title=stream_title,
        height=245,
        sizing_mode="stretch_width",
        x_range=stream_x_range,
        y_range=stream_y_range,
        tools="",
        toolbar_location=None,
        name="scheduler-stream-plot",
    )
    bars = stream_plot.hbar(
        y="worker",
        left="left",
        right="right",
        height=0.62,
        source=stream_source,
        fill_color="color",
        fill_alpha=0.82,
        line_color=None,
    )
    delay_markers = stream_plot.scatter(
        x="time",
        y="worker",
        marker="diamond",
        size=18,
        source=delay_source,
        fill_color=CHALK,
        line_color=CHALK,
        line_width=2.5,
    )
    interrupt_markers = stream_plot.scatter(
        x="time",
        y="worker",
        marker="x",
        size=18,
        source=interrupt_source,
        line_color=CORAL,
        line_width=3,
    )
    stream_plot.add_tools(
        HoverTool(
            renderers=[delay_markers, interrupt_markers],
            point_policy="follow_mouse",
            tooltips=[
                ("Injected event", "@event"),
                ("Worker", "@worker"),
                ("Time", "@time{0.0} s"),
            ],
        )
    )
    stream_plot.add_tools(
        HoverTool(renderers=[bars], limit=1, point_policy="follow_mouse", tooltips=TASK_HOVER_HTML)
    )
    stream_plot.xaxis.axis_label = "Simulated time (s)"
    style_figure(stream_plot)
    stream_plot.background_fill_color = PLUM
    stream_plot.border_fill_color = PLUM
    stream_plot.outline_line_color = DARK_GRID
    stream_plot.ygrid.grid_line_color = None
    stream_plot.xgrid.grid_line_color = DARK_GRID
    stream_plot.xgrid.grid_line_alpha = 0.45
    stream_plot.axis.axis_line_color = DARK_GRID
    stream_plot.axis.major_tick_line_color = DARK_GRID
    stream_plot.axis.major_label_text_color = CHALK
    stream_plot.axis.axis_label_text_color = CHALK

    workload_note = Div(name="scheduler-workload-note")
    stage_legend = Div(
        name="scheduler-stage-legend", sizing_mode="stretch_width", stylesheets=[SCHEDULER_CSS]
    )
    status_legend = Div(
        name="scheduler-status-legend",
        sizing_mode="stretch_width",
        text=STATUS_LEGEND_TEMPLATE.render(statuses=STATUS_COLORS.items()),
        stylesheets=[SCHEDULER_CSS],
    )
    run_status = Div(
        name="scheduler-run-status",
        sizing_mode="stretch_width",
        css_classes=["scheduler-run-status"],
        stylesheets=[SCHEDULER_CSS],
    )
    task_details = Div(
        name="scheduler-task-details",
        sizing_mode="stretch_width",
        css_classes=["scheduler-task-details"],
        stylesheets=[SCHEDULER_CSS],
    )
    state = SchedulerState(
        tasks=[],
        edges=[],
        critical_path=set(),
        workers=[],
        clock=0.0,
        cycles_completed=0,
        rng=np.random.default_rng(SEED),
    )
    stage_labels: list[Label] = []

    def update_graph_styles() -> None:
        tasks = state.tasks
        path = state.critical_path if critical_path.active else set()
        node_source.patch(
            {
                "line_color": [
                    (
                        task["id"],
                        GOLD if task["id"] in path else (CHALK if task["straggler"] else PAPER),
                    )
                    for task in tasks
                ],
                "line_width": [
                    (task["id"], 3.0 if task["id"] in path or task["straggler"] else 1.2)
                    for task in tasks
                ],
            }
        )
        edges = state.edges
        edge_source.patch(
            {
                "color": [
                    (index, GOLD if start in path and end in path else DARK_GRID)
                    for index, (start, end) in enumerate(edges)
                ],
                "alpha": [
                    (index, 0.9 if start in path and end in path else 0.52)
                    for index, (start, end) in enumerate(edges)
                ],
                "width": [
                    (index, 2.8 if start in path and end in path else 1.2)
                    for index, (start, end) in enumerate(edges)
                ],
            }
        )

    def set_status(task: Task, status: TaskStatus) -> None:
        task["status"] = status
        task_id = task["id"]
        node_source.patch(
            {
                "status": [(task_id, status)],
                "color": [(task_id, STATUS_COLORS[status])],
                "size": [(task_id, STATUS_SIZES[status])],
            }
        )

    def refresh_ready() -> None:
        tasks = state.tasks
        complete = {task["id"] for task in tasks if task["status"] == "Complete"}
        for task in tasks:
            if task["status"] == "Waiting" and set(task["dependencies"]) <= complete:
                set_status(task, "Ready")

    def start_task(task: Task, worker: WorkerState) -> None:
        task["worker"] = worker["name"]
        task["attempt"] += 1
        worker["task"] = task["id"]
        set_status(task, "Running")
        row = len(stream_source.data["task"])
        task["bar"] = row
        stream_source.stream(
            {
                "run": [state.cycles_completed + 1],
                "worker": [worker["name"]],
                "left": [state.clock],
                "right": [state.clock],
                "duration": [0.0],
                "task": [task["name"]],
                "stage": [task["stage"]],
                "attempt": [task["attempt"]],
                "result": ["Running"],
                "color": [STAGE_COLORS[task["stage_index"] % len(STAGE_COLORS)]],
            }
        )

    def update_summary() -> None:
        tasks = state.tasks
        workers = state.workers
        counts = {
            status: sum(task["status"] == status for task in tasks) for status in STATUS_COLORS
        }
        clock = state.clock
        offline = sum(worker["offline_until"] > clock for worker in workers)
        completed_total = state.cycles_completed * len(tasks) + counts["Complete"]
        throughput = completed_total / max(clock, 1)
        run_status.text = RUN_STATUS_TEMPLATE.render(
            complete=counts["Complete"],
            coral=CORAL,
            gold=GOLD,
            offline=offline,
            ready=counts["Ready"],
            run=state.cycles_completed + 1,
            running=counts["Running"],
            throughput=throughput,
            total=len(tasks),
            waiting=counts["Waiting"],
        )

    def show_task(task_id: int | None) -> None:
        if task_id is None:
            task_details.text = TASK_DETAILS_TEMPLATE.render(task=None)
            return
        tasks = state.tasks
        task = tasks[task_id]
        dependencies = [tasks[index]["name"] for index in task["dependencies"]]
        dependency_text = ", ".join(dependencies) if dependencies else "none"
        worker = task["worker"] or "not assigned"
        task_details.text = TASK_DETAILS_TEMPLATE.render(
            dependencies=dependency_text, task=task, worker=worker
        )

    def start_next_run() -> None:
        tasks = state.tasks
        workers = state.workers
        rng = state.rng
        state.cycles_completed += 1

        if len(stream_source.data["task"]) > 260:
            stream_source.data = cast(
                Any, {name: list(values[-230:]) for name, values in stream_source.data.items()}
            )
        for task in tasks:
            task["remaining"] = task["duration"] * rng.uniform(0.86, 1.18)
            task["status"] = "Waiting"
            task["worker"] = None
            task["attempt"] = 0
            task["straggler"] = False
            task["injected_delay"] = 0.0
            task["bar"] = None
        for worker in workers:
            worker["task"] = None
        node_source.patch(
            {
                "status": [(task["id"], "Waiting") for task in tasks],
                "color": [(task["id"], STATUS_COLORS["Waiting"]) for task in tasks],
                "size": [(task["id"], STATUS_SIZES["Waiting"]) for task in tasks],
            }
        )
        refresh_ready()
        update_graph_styles()

    def reset_simulation() -> None:
        workload_name = cast(WorkloadName, workload.value)
        definition = WORKLOADS[workload_name]
        tasks, edges = make_tasks(definition)
        path = find_critical_path(tasks)
        stage_groups: dict[int, list[Task]] = {}
        for task in tasks:
            stage_groups.setdefault(task["stage_index"], []).append(task)
        positions = {}
        for stage_index, group in stage_groups.items():
            y_values = np.linspace(0.94, -0.94, len(group)) if len(group) > 1 else np.array([0.0])
            positions.update(
                (task["id"], (stage_index, float(y)))
                for task, y in zip(group, y_values, strict=True)
            )

        node_source.data = {
            "index": [task["id"] for task in tasks],
            "task": [task["name"] for task in tasks],
            "stage": [task["stage"] for task in tasks],
            "status": [task["status"] for task in tasks],
            "duration": [task["duration"] for task in tasks],
            "color": [STATUS_COLORS["Waiting"] for task in tasks],
            "line_color": [CHALK for task in tasks],
            "line_width": [1.2 for task in tasks],
            "size": [STATUS_SIZES["Waiting"] for task in tasks],
        }
        edge_source.data = {
            "start": [start for start, _ in edges],
            "end": [end for _, end in edges],
            "color": [DARK_GRID for _ in edges],
            "alpha": [0.52 for _ in edges],
            "width": [1.2 for _ in edges],
        }
        layout_provider.graph_layout = cast(Any, positions)
        stream_source.data = {name: [] for name in stream_source.data}
        delay_source.data = {name: [] for name in delay_source.data}
        interrupt_source.data = {name: [] for name in interrupt_source.data}
        state.tasks = tasks
        state.edges = edges
        state.critical_path = path
        state.workers = [
            {"name": f"Worker {index}", "task": None, "offline_until": 0.0}
            for index in range(1, int(worker_count.value) + 1)
        ]
        state.clock = 0.0
        state.cycles_completed = 0
        state.rng = np.random.default_rng(SEED + len(tasks))
        workload_note.text = WORKLOAD_NOTE_TEMPLATE.render(name=workload_name, note=definition.note)
        stage_legend.text = STAGE_LEGEND_TEMPLATE.render(
            stages=[
                (stage, STAGE_COLORS[index % len(STAGE_COLORS)])
                for index, (stage, _count, _duration) in enumerate(definition.stages)
            ]
        )
        graph_x_range.end = len(definition.stages) - 0.55
        stream_y_range.factors = [
            f"Worker {index}" for index in range(int(worker_count.value), 0, -1)
        ]
        graph_plot.center = [item for item in graph_plot.center if item not in stage_labels]
        stage_labels.clear()
        for stage_index, (stage_name, _count, _duration) in enumerate(definition.stages):
            label = Label(
                x=stage_index,
                y=1.13,
                text=stage_name.upper(),
                text_align="center",
                text_color=CHALK,
                text_font_size="9px",
                text_font_style="bold",
            )
            graph_plot.add_layout(label)
            stage_labels.append(label)
        node_source.selected.indices = []
        refresh_ready()
        update_graph_styles()
        show_task(None)
        update_summary()
        for _ in range(12):
            advance(force=True)

    def advance(*, force: bool = False) -> None:
        if not playing.active and not force:
            return
        tasks = state.tasks
        workers = state.workers
        step = STEP_SECONDS
        state.clock += step
        clock = state.clock

        right_patches: list[tuple[int, float]] = []
        duration_patches: list[tuple[int, float]] = []
        result_patches: list[tuple[int, str]] = []
        for worker in workers:
            task_id = worker["task"]
            if task_id is None:
                continue
            task = tasks[task_id]
            task["remaining"] -= step
            bar = task["bar"]
            assert bar is not None
            right_patches.append((bar, clock))
            duration_patches.append((bar, clock - cast(float, stream_source.data["left"][bar])))
            if task["remaining"] <= 0:
                set_status(task, "Complete")
                task["worker"] = None
                result = "Straggler complete" if task["straggler"] else "Complete"
                result_patches.append((bar, result))
                worker["task"] = None

        if right_patches:
            patches: dict[str, Any] = {"right": right_patches, "duration": duration_patches}
            if result_patches:
                patches["result"] = result_patches
            stream_source.patch(cast(Any, patches))

        refresh_ready()
        ready = [task for task in tasks if task["status"] == "Ready"]
        for worker in workers:
            if not ready:
                break
            if worker["task"] is None and worker["offline_until"] <= clock:
                start_task(ready.pop(0), worker)

        stream_x_range.end = max(40, clock + 3)
        stream_x_range.start = max(0, cast(float, stream_x_range.end) - 55)
        if all(task["status"] == "Complete" for task in tasks):
            start_next_run()
        update_summary()

    def selection_changed(_attr: str, _old: object, indices: list[int]) -> None:
        show_task(indices[0] if indices else None)

    def settings_changed(_attr: str, _old: object, _new: object) -> None:
        reset_simulation()

    def playback_changed(_attr: str, _old: bool, active: bool) -> None:
        playing.label = "Pause scheduler" if active else "Resume scheduler"

    def critical_changed(_attr: str, _old: bool, _new: bool) -> None:
        update_graph_styles()

    def slow_task() -> None:
        tasks = state.tasks
        running = [task for task in tasks if task["status"] == "Running" and not task["straggler"]]
        if not running:
            return
        task = max(running, key=lambda candidate: candidate["remaining"])
        delay = max(STRAGGLER_DELAY, 2.5 * task["duration"])
        task["remaining"] += delay
        task["straggler"] = True
        task["injected_delay"] += delay
        bar = task["bar"]
        assert bar is not None
        stream_source.patch({"result": [(bar, "Straggler")]})
        delay_source.stream(
            {
                "worker": [task["worker"]],
                "time": [state.clock],
                "event": [f"Delayed {task['name']} by {delay:.0f} s"],
            }
        )
        update_graph_styles()
        show_task(task["id"])

    def interrupt_worker() -> None:
        tasks = state.tasks
        workers = state.workers
        busy = [worker for worker in workers if worker["task"] is not None]
        if not busy:
            return
        worker = busy[int(state.rng.integers(0, len(busy)))]
        task_id = worker["task"]
        assert task_id is not None
        task = tasks[task_id]
        bar = task["bar"]
        assert bar is not None
        stream_source.patch({"result": [(bar, "Interrupted")]})
        interrupt_source.stream(
            {
                "worker": [worker["name"]],
                "time": [state.clock],
                "event": [f"Interrupted {worker['name']} for {WORKER_OUTAGE:.0f} s"],
            }
        )
        task["remaining"] = max(1.0, task["remaining"])
        task["worker"] = None
        task["bar"] = None
        set_status(task, "Ready")
        worker["task"] = None
        worker["offline_until"] = state.clock + WORKER_OUTAGE
        task_details.text = INTERRUPTION_TEMPLATE.render(
            outage=WORKER_OUTAGE, task=task["name"], worker=worker["name"]
        )
        update_summary()

    workload.on_change("value", performance.measure(settings_changed))
    worker_count.on_change("value_throttled", performance.measure(settings_changed))
    playing.on_change("active", performance.measure(playback_changed))
    critical_path.on_change("active", performance.measure(critical_changed))
    node_source.selected.on_change("indices", performance.measure(selection_changed))
    straggler.on_click(performance.measure(slow_task))
    fail_worker.on_click(performance.measure(interrupt_worker))
    restart.on_click(performance.measure(reset_simulation))
    reset_simulation()
    document.add_periodic_callback(performance.measure(advance), 150)

    controls = column(
        Div(text=INTRO_HTML, css_classes=["scheduler-introduction"], stylesheets=[SCHEDULER_CSS]),
        responsive_row(workload, worker_count, sizing_mode="stretch_width"),
        wrap_row(
            playing, critical_path, straggler, fail_worker, restart, sizing_mode="stretch_width"
        ),
        workload_note,
        sizing_mode="stretch_width",
        css_classes=["scheduler-controls"],
        stylesheets=[SCHEDULER_CSS],
    )
    match_background(controls, WARM)
    note = Div(text=NOTE_TEMPLATE.render(seed=SEED))
    console = column(
        run_status,
        stage_legend,
        stream_plot,
        status_legend,
        graph_plot,
        task_details,
        sizing_mode="stretch_width",
        spacing=0,
        name="scheduler-console",
        css_classes=["scheduler-console"],
        stylesheets=[SCHEDULER_CSS],
    )
    match_background(console, PLUM)
    document.add_root(column(controls, console, note, sizing_mode="stretch_width", spacing=16))
    prepare_document(document, "/task-scheduler")
