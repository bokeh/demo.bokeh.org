"""Test the task scheduler demo."""

from __future__ import annotations

from bokeh.document import Document
from bokeh.events import ButtonClick
from bokeh.models import Button, ColumnDataSource, GraphRenderer, HoverTool, Select, Slider, Toggle

from apps._common.colors import PLUM
from catalog import load_applications


def test_task_scheduler_streams_state_without_rebuilding_the_graph() -> None:
    document = Document()
    load_applications()["/task-scheduler"](document)
    graph = document.select_one({"type": GraphRenderer, "name": "scheduler-graph"})
    nodes = graph.node_renderer.data_source
    edges = graph.edge_renderer.data_source
    stream = document.select_one({"type": ColumnDataSource, "name": "scheduler-task-stream"})
    delays = document.select_one({"type": ColumnDataSource, "name": "scheduler-delay-events"})
    interruptions = document.select_one(
        {"type": ColumnDataSource, "name": "scheduler-interrupt-events"}
    )
    assert len(nodes.data["index"]) >= 40
    assert len(edges.data["start"]) > 40
    assert set(graph.layout_provider.graph_layout) == set(nodes.data["index"])
    original_edges = dict(edges.data)
    initial_bars = len(stream.data["task"])
    for _ in range(12):
        document.session_callbacks[0].callback()
    assert len(stream.data["task"]) > initial_bars
    assert edges.data["start"] == original_edges["start"]
    assert edges.data["end"] == original_edges["end"]
    task_stream = document.select_one({"name": "scheduler-stream-plot"})
    assert task_stream.output_backend == "canvas"
    assert task_stream.ygrid[0].grid_line_color is None
    task_hover = next(
        tool
        for tool in task_stream.toolbar.tools
        if isinstance(tool, HoverTool) and tool.limit == 1
    )
    assert task_hover.limit == 1
    assert task_hover.point_policy == "follow_mouse"
    assert "waiting" in document.select_one({"name": "scheduler-status-legend"}).text
    assert "Load scenes" in document.select_one({"name": "scheduler-stage-legend"}).text
    assert not any(select.title == "Replay pace" for select in document.select({"type": Select}))
    console = document.select_one({"name": "scheduler-console"})
    assert console.styles["background"] == PLUM
    assert console.children.index(task_stream) < console.children.index(
        document.select_one({"name": "scheduler-graph-plot"})
    )
    interrupt = next(
        button
        for button in document.select({"type": Button})
        if button.label == "Interrupt a worker"
    )
    interrupt._trigger_event(ButtonClick(interrupt))
    interrupted_bar = stream.data["result"].index("Interrupted")
    interrupted_worker = stream.data["worker"][interrupted_bar]
    interrupted_at = stream.data["right"][interrupted_bar]
    assert interruptions.data["event"][0].startswith("Interrupted ")
    assert delays.data["event"] == []
    assert (
        "offline for 16 simulated seconds"
        in document.select_one({"name": "scheduler-task-details"}).text
    )
    for _ in range(10):
        document.session_callbacks[0].callback()
    assert not (
        any(
            worker == interrupted_worker and left > interrupted_at
            for worker, left in zip(stream.data["worker"], stream.data["left"], strict=True)
        )
    )
    slow = next(
        button
        for button in document.select({"type": Button})
        if button.label == "Slow one running task"
    )
    slow._trigger_event(ButtonClick(slow))
    assert delays.data["event"][-1].startswith("Delayed ")
    assert len(interruptions.data["event"]) == 1
    assert "Injected delay: 18 s" in document.select_one({"name": "scheduler-task-details"}).text
    for _ in range(220):
        document.session_callbacks[0].callback()
    assert max(stream.data["run"]) >= 2
    assert next(
        toggle for toggle in document.select({"type": Toggle}) if toggle.label == "Pause scheduler"
    ).active
    workload = next(
        select
        for select in document.select({"type": Select})
        if select.title == "Synthetic workload"
    )
    workers = next(
        slider for slider in document.select({"type": Slider}) if slider.title == "Workers"
    )
    assert len(workload.options) >= 8
    workload.value = "Storm forecast ensemble"
    workers.value = 3
    assert task_stream.y_range.factors == ["Worker 3", "Worker 2", "Worker 1"]
    assert len(nodes.data["index"]) >= 40
