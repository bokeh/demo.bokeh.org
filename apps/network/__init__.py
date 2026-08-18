"""Explore research lineages through alternative network layouts."""

from __future__ import annotations

import json
import math
from html import escape
from pathlib import Path
from typing import Any, cast

import networkx as nx
from bokeh.layouts import column
from bokeh.models import (
    ColumnDataSource,
    Div,
    FactorRange,
    HoverTool,
    Label,
    LabelSet,
    NodesAndLinkedEdges,
    NumeralTickFormatter,
    RadioButtonGroup,
    Range1d,
    Select,
    Slider,
    Span,
    StaticLayoutProvider,
    Title,
)
from bokeh.plotting import figure

from apps._common import monitor_document, prepare_document, responsive_row, style_figure, wrap_row
from apps._common.colors import CORAL, GOLD, GRID, INK, MUTED, PAPER, TEAL, VIOLET, WARM

DATA = json.loads(Path(__file__).with_name("research_lineages.json").read_text())
LINEAGES = DATA["lineages"]
RELATION_COLORS = {"Foundation": TEAL, "Landmark": GOLD, "Follow-on": CORAL}
LAYOUTS = ("Opposing arcs", "Columns", "Radial timeline", "Arc diagram")
LANDMARK_BUTTON_CSS = f"""
:host {{ background: {PAPER}; }}
.bk-btn-group {{ height: auto; }}
.bk-btn-group > .bk-btn {{ min-height: 44px; padding: 8px 12px; white-space: normal; line-height: 1.2; background: {PAPER} !important; color: {INK} !important; }}
.bk-btn-group > .bk-btn.bk-active {{ background: {VIOLET} !important; border-color: {VIOLET} !important; color: {PAPER} !important; }}
@media (max-width: 700px) {{
  .bk-btn-group {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .bk-btn-group > .bk-btn {{ margin: -1px 0 0 -1px !important; border-radius: 0 !important; }}
}}
"""


def shorten(title: str, length: int = 42) -> str:
    return title if len(title) <= length else f"{title[: length - 1].rstrip()}…"


def compute_positions(nodes: list[dict], layout: str) -> dict[str, tuple[float, float]]:
    groups = {
        relation: sorted(
            (node for node in nodes if node["relation"] == relation),
            key=lambda node: (node["year"], node["citations"]),
        )
        for relation in RELATION_COLORS
    }
    landmark = groups["Landmark"][0]["id"]

    match layout:
        case "Columns":
            positions = {landmark: (0.0, 0.0)}
            for relation, x in (("Foundation", -1.0), ("Follow-on", 1.0)):
                group = groups[relation]
                step = 1.8 / max(len(group) - 1, 1)
                positions.update(
                    (node["id"], (x, 0.9 - index * step)) for index, node in enumerate(group)
                )
            return positions
        case "Opposing arcs":
            positions = {landmark: (0.0, 0.0)}
            for relation, direction in (("Foundation", -1.0), ("Follow-on", 1.0)):
                group = groups[relation]
                step = math.pi / max(len(group) - 1, 1)
                for index, node in enumerate(group):
                    angle = -math.pi / 2 + index * step
                    positions[node["id"]] = (
                        direction * (0.34 + 0.7 * math.cos(angle)),
                        0.9 * math.sin(angle),
                    )
            return positions
        case "Radial timeline":
            ordered = sorted(
                nodes, key=lambda node: (node["year"], node["relation"], -node["citations"])
            )
            positions = {}
            for index, node in enumerate(ordered):
                progress = index / max(len(ordered) - 1, 1)
                angle = -math.pi / 2 + 4 * math.pi * progress
                radius = 0.16 + 0.82 * progress
                positions[node["id"]] = (radius * math.cos(angle), radius * math.sin(angle))
            return positions
        case "Arc diagram":
            ordered = sorted(
                nodes, key=lambda node: (node["year"], node["relation"], -node["citations"])
            )
            step = 2.16 / max(len(ordered) - 1, 1)
            return {node["id"]: (-1.08 + index * step, -0.76) for index, node in enumerate(ordered)}
        case _:
            raise ValueError(f"Unknown network layout: {layout}")


def arc_paths(
    positions: dict[str, tuple[float, float]], edges: list[dict]
) -> tuple[list[list[float]], list[list[float]]]:
    xs, ys = [], []
    for edge in edges:
        start = positions[edge["source"]][0]
        end = positions[edge["target"]][0]
        left, right = sorted((start, end))
        center = (left + right) / 2
        radius = (right - left) / 2
        angles = [math.pi * index / 31 for index in range(32)]
        xs.append([center + radius * math.cos(angle) for angle in angles])
        ys.append([-0.76 + 1.45 * radius * math.sin(angle) for angle in angles])
    return xs, ys


def modify_document(document) -> None:
    performance = monitor_document(document, "/research-lineage")
    lineage_names = tuple(LINEAGES)
    lineage_buttons = RadioButtonGroup(
        labels=list(lineage_names),
        active=0,
        sizing_mode="stretch_width",
        styles={"background": PAPER},
        stylesheets=[LANDMARK_BUTTON_CSS],
        name="lineage-landmark-buttons",
    )
    metric_select = Select(
        title="Size papers by",
        value="Citation count",
        options=["Citation count", "PageRank in this view"],
    )
    layout_select = Select(title="Network layout", value=LAYOUTS[0], options=list(LAYOUTS))
    year = Slider(title="Reveal follow-on work through", start=2016, end=2026, value=2026, step=1)
    paper_select = Select(title="Inspect paper", value="", options=[])

    graph_title = Title(text="Citation network")
    graph_plot = figure(
        title=graph_title,
        height=660,
        sizing_mode="stretch_width",
        x_range=Range1d(start=-1.28, end=1.28),
        y_range=Range1d(start=-1.08, end=1.08),
        x_axis_location=None,
        y_axis_location=None,
        tools="tap",
        toolbar_location=None,
        name="lineage-network-plot",
    )
    style_figure(graph_plot)
    graph_plot.background_fill_color = WARM
    graph_plot.grid.visible = False
    graph_plot.outline_line_color = GRID
    layer_labels = []
    for x, heading in ((-1.0, "FOUNDATIONS"), (0.0, "LANDMARK"), (1.0, "FOLLOW-ON WORK")):
        label = Label(
            x=x,
            y=1.0,
            text=heading,
            text_align="center",
            text_color=MUTED,
            text_font_size="10px",
            text_font_style="bold",
        )
        layer_labels.append(label)
        graph_plot.add_layout(label)

    radial_guide_source = ColumnDataSource(data={"x": [], "y": []}, name="lineage-radial-guide")
    radial_guide = graph_plot.line(
        x="x",
        y="y",
        source=radial_guide_source,
        line_color=GRID,
        line_alpha=0.8,
        line_width=2,
        line_dash="dotted",
    )
    radial_guide.visible = False
    radial_year_source = ColumnDataSource(
        data={"x": [], "y": [], "text": []}, name="lineage-radial-years"
    )
    radial_year_labels = LabelSet(
        x="x",
        y="y",
        text="text",
        source=radial_year_source,
        x_offset=8,
        y_offset=-16,
        text_color=MUTED,
        text_font_size="10px",
        text_font_style="bold",
        background_fill_color=WARM,
        background_fill_alpha=0.9,
    )
    radial_year_labels.visible = False
    graph_plot.add_layout(radial_year_labels)

    arc_source = ColumnDataSource(
        data={"xs": [], "ys": [], "color": [], "alpha": [], "width": []}, name="lineage-arc-edges"
    )
    arc_renderer = graph_plot.multi_line(
        xs="xs",
        ys="ys",
        line_color="color",
        line_alpha="alpha",
        line_width="width",
        source=arc_source,
    )
    arc_renderer.visible = False
    arc_baseline = Span(
        location=-0.76, dimension="width", line_color=MUTED, line_alpha=0.55, line_width=1
    )
    arc_baseline.visible = False
    graph_plot.add_layout(arc_baseline)

    node_source = ColumnDataSource(name="lineage-nodes")
    edge_source = ColumnDataSource(name="lineage-edges")
    layout_provider = StaticLayoutProvider(graph_layout={})
    graph_renderer = graph_plot.graph(
        node_source,
        edge_source,
        layout_provider,
        name="lineage-graph",
        node_size="size",
        node_fill_color="color",
        node_fill_alpha=0.88,
        node_line_color=PAPER,
        node_line_width=1.5,
        node_selection_fill_color=VIOLET,
        node_selection_fill_alpha=1.0,
        node_selection_line_color=PAPER,
        node_selection_line_width=3,
        node_nonselection_fill_alpha=0.34,
        node_nonselection_line_alpha=0.5,
        node_hover_fill_color=GOLD,
        node_hover_fill_alpha=1.0,
        node_hover_line_color=INK,
        node_hover_line_width=2.5,
        edge_line_color=GRID,
        edge_line_alpha=0.62,
        edge_line_width=1.4,
        edge_selection_line_color=VIOLET,
        edge_selection_line_alpha=0.86,
        edge_selection_line_width=3,
        edge_nonselection_line_alpha=0.16,
        edge_hover_line_color=GOLD,
        edge_hover_line_alpha=0.9,
        edge_hover_line_width=3,
        selection_policy=NodesAndLinkedEdges(),
        inspection_policy=NodesAndLinkedEdges(),
    )
    graph_plot.add_tools(
        HoverTool(
            renderers=[graph_renderer.node_renderer],
            tooltips="""
        <div style="max-width:320px;padding:4px 6px">
          <div style="font-weight:700;line-height:1.3">@title</div>
          <div style="margin-top:5px;color:#6f686c">@authors · @year</div>
          <div style="margin-top:3px">@citations{0,0} citations · @relation</div>
        </div>
        """,
        )
    )

    label_source = ColumnDataSource(data={"x": [], "y": [], "text": [], "y_offset": []})
    graph_plot.add_layout(
        LabelSet(
            x="x",
            y="y",
            text="text",
            y_offset="y_offset",
            source=label_source,
            text_align="center",
            text_baseline="bottom",
            text_color=INK,
            text_font_size="11px",
            background_fill_color=PAPER,
            background_fill_alpha=0.92,
            border_line_color=GRID,
            border_line_alpha=0.8,
        )
    )

    timeline_source = ColumnDataSource(
        data={"year": [], "count": [], "color": []}, name="lineage-timeline"
    )
    timeline = figure(
        height=320,
        sizing_mode="stretch_width",
        toolbar_location=None,
        tools="",
        title="Papers citing the landmark each year",
        name="lineage-timeline-plot",
    )
    bars = timeline.vbar(
        x="year", top="count", width=0.78, color="color", line_color=None, source=timeline_source
    )
    timeline.add_tools(
        HoverTool(renderers=[bars], tooltips=[("Year", "@year"), ("Citing papers", "@count{0,0}")])
    )
    timeline.yaxis.axis_label = "Papers"
    timeline.xgrid.visible = False
    style_figure(timeline)
    cutoff = Span(
        location=year.value, dimension="height", line_color=VIOLET, line_width=2, line_dash="dashed"
    )
    timeline.add_layout(cutoff)

    ranking_source = ColumnDataSource(
        data={"label": [], "value": [], "color": [], "title": [], "year": []},
        name="lineage-ranking",
    )
    ranking_range = FactorRange()
    ranking_title = Title(text="Most cited papers in this view")
    ranking = figure(
        title=ranking_title,
        height=320,
        sizing_mode="stretch_width",
        y_range=ranking_range,
        toolbar_location=None,
        tools="",
        name="lineage-ranking-plot",
    )
    ranked_bars = ranking.hbar(
        y="label", right="value", height=0.62, color="color", line_color=None, source=ranking_source
    )
    ranking.add_tools(
        HoverTool(
            renderers=[ranked_bars],
            tooltips=[("Paper", "@title"), ("Published", "@year"), ("Value", "@value{0,0.000}")],
        )
    )
    ranking.xaxis.formatter = NumeralTickFormatter(format="0,0")
    ranking.ygrid.visible = False
    style_figure(ranking)

    lineage_note = Div(name="lineage-note")
    details = Div(name="lineage-details")
    state: dict[str, Any] = {"updating": False, "nodes": [], "positions": {}, "metrics": {}}

    def lineage_name() -> str:
        active = lineage_buttons.active
        assert active is not None
        return lineage_names[active]

    def visible_nodes() -> list[dict]:
        lineage = LINEAGES[lineage_name()]
        return [
            node
            for node in lineage["nodes"]
            if node["relation"] != "Follow-on" or node["year"] <= year.value
        ]

    def update_arc_edge_style() -> None:
        selected = set(edge_source.selected.indices)
        count = len(arc_source.data["xs"])
        arc_source.data = {
            "xs": list(arc_source.data["xs"]),
            "ys": list(arc_source.data["ys"]),
            "color": [VIOLET if index in selected else GRID for index in range(count)],
            "alpha": [0.86 if index in selected else 0.16 for index in range(count)],
            "width": [3 if index in selected else 1.4 for index in range(count)],
        }

    def update_inspector(paper_id: str) -> None:
        nodes = state["nodes"]
        index = next(index for index, node in enumerate(nodes) if node["id"] == paper_id)
        node_source.selected.indices = [index]
        edge_source.selected.indices = [
            edge_index
            for edge_index, (source, target) in enumerate(
                zip(edge_source.data["start"], edge_source.data["end"], strict=True)
            )
            if paper_id in (source, target)
        ]
        if layout_select.value == "Arc diagram":
            update_arc_edge_style()
        selected = nodes[index]
        position = state["positions"][paper_id]
        label_source.data = {
            "x": [position[0]],
            "y": [position[1]],
            "text": [shorten(selected["title"], 36)],
            "y_offset": [14 + cast(float, node_source.data["size"][index]) / 2],
        }
        connection = {
            "Foundation": "The landmark paper cites this earlier work.",
            "Landmark": "The paper at the center of this lineage.",
            "Follow-on": "This later paper cites the landmark result.",
        }[selected["relation"]]
        link = selected["doi"] or f"https://openalex.org/{selected['id']}"
        details.text = (
            f'<article style="padding:22px;border:1px solid {GRID};border-top:4px solid {RELATION_COLORS[selected["relation"]]};background:{PAPER}">'
            f'<p style="margin:0;color:{RELATION_COLORS[selected["relation"]]};font:700 10px monospace;letter-spacing:.1em;text-transform:uppercase">{selected["relation"]}</p>'
            f'<h3 style="margin:10px 0 8px;font:400 25px/1.18 Georgia,serif">{escape(selected["title"])}</h3>'
            f'<p style="margin:0;color:{MUTED}">{escape(selected["authors"])} · {selected["year"]}</p>'
            f'<p style="margin:16px 0 0"><strong>{selected["citations"]:,}</strong> OpenAlex citations<br>{escape(selected["topic"])} · {escape(selected["type"])}</p>'
            f'<p style="margin:14px 0 0;color:{MUTED}">{connection}</p>'
            f'<a href="{escape(link)}" target="_blank" rel="noreferrer" style="display:inline-block;margin-top:16px;color:{CORAL};font-weight:700">Open paper ↗</a>'
            "</article>"
        )
        values = state["metrics"][metric_select.value]
        ranked = sorted(nodes, key=lambda item: values[item["id"]], reverse=True)[:9]
        labels = [
            f"{rank:02d} · {shorten(item['title'], 27)} · {item['year']}"
            for rank, item in enumerate(ranked, start=1)
        ]
        ranking_range.factors = list(reversed(labels))
        ranking_source.data = {
            "label": labels,
            "value": [values[item["id"]] for item in ranked],
            "color": [
                VIOLET if item["id"] == paper_id else RELATION_COLORS[item["relation"]]
                for item in ranked
            ],
            "title": [item["title"] for item in ranked],
            "year": [item["year"] for item in ranked],
        }

    def update_graph() -> None:
        nodes = visible_nodes()
        node_ids = {node["id"] for node in nodes}
        lineage = LINEAGES[lineage_name()]
        edges = [
            edge
            for edge in lineage["edges"]
            if edge["source"] in node_ids and edge["target"] in node_ids
        ]
        graph = nx.DiGraph((edge["source"], edge["target"]) for edge in edges)
        graph.add_nodes_from(node_ids)
        pagerank = nx.pagerank(graph)
        metrics = {
            "Citation count": {node["id"]: node["citations"] for node in nodes},
            "PageRank in this view": pagerank,
        }
        values = metrics[metric_select.value]
        transformed = {
            node_id: math.log1p(value) if metric_select.value == "Citation count" else value
            for node_id, value in values.items()
        }
        low, high = min(transformed.values()), max(transformed.values())
        sizes = {
            node_id: 14 + 30 * (value - low) / (high - low or 1)
            for node_id, value in transformed.items()
        }
        positions = compute_positions(nodes, layout_select.value)
        selected_id = paper_select.value if paper_select.value in node_ids else lineage["seed"]

        state["updating"] = True
        state["nodes"] = nodes
        state["positions"] = positions
        state["metrics"] = metrics
        node_source.data = {
            "index": [node["id"] for node in nodes],
            "title": [node["title"] for node in nodes],
            "authors": [node["authors"] for node in nodes],
            "year": [node["year"] for node in nodes],
            "citations": [node["citations"] for node in nodes],
            "relation": [node["relation"] for node in nodes],
            "color": [RELATION_COLORS[node["relation"]] for node in nodes],
            "size": [sizes[node["id"]] for node in nodes],
        }
        edge_source.data = {
            "start": [edge["source"] for edge in edges],
            "end": [edge["target"] for edge in edges],
        }
        layout_provider.graph_layout = cast(Any, positions)
        radial = layout_select.value == "Radial timeline"
        radial_guide.visible = radial
        radial_year_labels.visible = radial
        if radial:
            ordered = sorted(
                nodes, key=lambda node: (node["year"], node["relation"], -node["citations"])
            )
            radial_guide_source.data = {
                "x": [positions[node["id"]][0] for node in ordered],
                "y": [positions[node["id"]][1] for node in ordered],
            }
            markers = [
                ordered[0],
                next(node for node in nodes if node["id"] == lineage["seed"]),
                ordered[-1],
            ]
            radial_year_source.data = {
                "x": [positions[node["id"]][0] for node in markers],
                "y": [positions[node["id"]][1] for node in markers],
                "text": [str(node["year"]) for node in markers],
            }
        else:
            radial_guide_source.data = {"x": [], "y": []}
            radial_year_source.data = {"x": [], "y": [], "text": []}

        arc = layout_select.value == "Arc diagram"
        graph_renderer.edge_renderer.visible = not arc
        arc_renderer.visible = arc
        arc_baseline.visible = arc
        if arc:
            xs, ys = arc_paths(positions, edges)
            arc_source.data = {
                "xs": xs,
                "ys": ys,
                "color": [GRID] * len(edges),
                "alpha": [0.16] * len(edges),
                "width": [1.4] * len(edges),
            }
        else:
            arc_source.data = {"xs": [], "ys": [], "color": [], "alpha": [], "width": []}
        for label in layer_labels:
            label.visible = layout_select.value in {"Opposing arcs", "Columns"}
        paper_select.options = [
            (node["id"], f"{shorten(node['title'], 72)} · {node['year']}")
            for node in sorted(
                nodes,
                key=lambda item: (item["relation"] != "Landmark", item["year"], item["title"]),
            )
        ]
        paper_select.value = selected_id
        graph_title.text = f"Citation network · {lineage_name()}"
        ranking_title.text = (
            "Most cited papers in this view"
            if metric_select.value == "Citation count"
            else "Highest PageRank in this view"
        )
        ranking.xaxis.formatter = NumeralTickFormatter(
            format="0,0" if metric_select.value == "Citation count" else "0.000"
        )
        lineage_note.text = (
            f'<div style="padding:16px 18px;background:{WARM};border-left:4px solid {VIOLET}">'
            f'<strong>{lineage_name()}</strong><br><span style="color:{MUTED}">{escape(lineage["description"])}</span></div>'
        )
        state["updating"] = False
        update_inspector(selected_id)

    def update_timeline() -> None:
        counts = LINEAGES[lineage_name()]["year_counts"]
        timeline_source.data = {
            "year": [item["year"] for item in counts],
            "count": [item["count"] for item in counts],
            "color": [TEAL if item["year"] <= year.value else GRID for item in counts],
        }
        cutoff.location = year.value

    def refresh_lineage() -> None:
        lineage = LINEAGES[lineage_name()]
        seed = next(node for node in lineage["nodes"] if node["id"] == lineage["seed"])
        last_year = max(item["year"] for item in lineage["year_counts"])
        state["updating"] = True
        year.start = seed["year"]
        year.end = last_year
        year.value = last_year
        paper_select.value = ""
        state["updating"] = False
        update_timeline()
        update_graph()

    def lineage_changed(_attr: str, _old: object, _new: object) -> None:
        if not state["updating"]:
            refresh_lineage()

    def view_changed(_attr: str, _old: object, _new: object) -> None:
        if not state["updating"]:
            update_timeline()
            update_graph()

    def graph_changed(_attr: str, _old: object, _new: object) -> None:
        if not state["updating"]:
            update_graph()

    def paper_changed(_attr: str, _old: object, paper_id: str) -> None:
        if not state["updating"] and paper_id:
            update_inspector(paper_id)

    def graph_selected(_attr: str, _old: list[int], indices: list[int]) -> None:
        if state["updating"] or not indices:
            return
        paper_id = str(node_source.data["index"][indices[0]])
        state["updating"] = True
        paper_select.value = paper_id
        state["updating"] = False
        update_inspector(paper_id)

    lineage_buttons.on_change("active", performance.measure(lineage_changed))
    metric_select.on_change("value", performance.measure(graph_changed))
    layout_select.on_change("value", performance.measure(graph_changed))
    year.on_change("value_throttled", performance.measure(view_changed))
    paper_select.on_change("value", performance.measure(paper_changed))
    node_source.selected.on_change("indices", performance.measure(graph_selected))
    refresh_lineage()

    intro = Div(
        text=(
            "<h2>Follow an idea backward and forward</h2>"
            "<p>Choose a landmark result, reveal later work over time, or tap any paper to see how it fits. "
            "The graph recomputes PageRank and the linked ranking for the papers currently in view.</p>"
        )
    )
    relation_key = Div(
        name="lineage-relation-key",
        text=(
            f'<div style="padding:14px 16px;border:1px solid {GRID};background:{WARM};font-size:13px">'
            f'<span style="display:inline-block;width:13px;height:13px;margin-right:6px;border-radius:50%;background:{TEAL};vertical-align:-2px"></span>foundation &nbsp; '
            f'<span style="display:inline-block;width:13px;height:13px;margin-right:6px;border-radius:50%;background:{GOLD};vertical-align:-2px"></span>landmark &nbsp; '
            f'<span style="display:inline-block;width:13px;height:13px;margin-right:6px;border-radius:50%;background:{CORAL};vertical-align:-2px"></span>follow-on work'
            f'<p style="margin:8px 0 0;color:{MUTED}">Connections run from a paper to work it cites.</p></div>'
        ),
    )
    sidebar = column(paper_select, relation_key, details, width=365, spacing=14)
    source_note = Div(
        text=(
            f'<p style="color:{MUTED};font-size:12px"><strong>Data:</strong> OpenAlex metadata captured {DATA["snapshot_date"]}. '
            "Each view contains the landmark, its sixteen most-cited references, and up to twenty highly cited papers that cite it; "
            "the timeline counts all citing records in OpenAlex. The current year is incomplete.</p>"
        )
    )
    document.add_root(
        column(
            intro,
            Div(
                text=f'<p style="margin:0;color:{MUTED};font-size:13px;font-weight:700">Landmark paper</p>'
            ),
            lineage_buttons,
            wrap_row(metric_select, layout_select, year, sizing_mode="stretch_width"),
            lineage_note,
            responsive_row(graph_plot, sidebar, sizing_mode="stretch_width"),
            responsive_row(timeline, ranking, sizing_mode="stretch_width"),
            source_note,
            sizing_mode="stretch_width",
            spacing=22,
        )
    )
    prepare_document(document, "/research-lineage")
