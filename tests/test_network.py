"""Test the research lineage demo."""

from __future__ import annotations

import numpy as np
from bokeh.document import Document
from bokeh.models import ColumnDataSource, Div, GraphRenderer, RadioButtonGroup, Select, Slider

from apps._common.colors import TEAL
from apps.network import LAYOUTS
from catalog import load_applications


def test_research_lineage_links_time_selection_and_ranking() -> None:
    document = Document()
    load_applications()["/research-lineage"](document)
    lineage_buttons = document.select_one(
        {"type": RadioButtonGroup, "name": "lineage-landmark-buttons"}
    )
    metric = next(
        select for select in document.select({"type": Select}) if select.title == "Size papers by"
    )
    layout = next(
        select for select in document.select({"type": Select}) if select.title == "Network layout"
    )
    year = next(
        slider
        for slider in document.select({"type": Slider})
        if slider.title == "Reveal follow-on work through"
    )
    paper = next(
        select for select in document.select({"type": Select}) if select.title == "Inspect paper"
    )
    graph = document.select_one({"type": GraphRenderer})
    nodes = graph.node_renderer.data_source
    edges = graph.edge_renderer.data_source
    details = document.select_one({"type": Div, "name": "lineage-details"})
    relation_key = document.select_one({"type": Div, "name": "lineage-relation-key"})
    ranking = document.select_one({"name": "lineage-ranking-plot"})
    timeline = document.select_one({"type": ColumnDataSource, "name": "lineage-timeline"})

    assert set(lineage_buttons.labels) == {
        "Gravitational waves",
        "CRISPR genome editing",
        "Protein structure prediction",
        "Climate attribution",
    }
    assert lineage_buttons.active == 0
    assert tuple(layout.options) == LAYOUTS
    assert layout.value == "Opposing arcs"
    assert len(nodes.data["index"]) >= 30
    assert len(edges.data["start"]) > 50
    assert set(nodes.data["relation"]) == {"Foundation", "Landmark", "Follow-on"}
    assert len(nodes.selected.indices) == 1
    assert len(edges.selected.indices) > 0
    assert "OpenAlex citations" in details.text
    assert relation_key.text.count("width:13px") == 3
    assert all(
        color == TEAL if published <= year.value else color != TEAL
        for published, color in zip(timeline.data["year"], timeline.data["color"], strict=True)
    )

    layouts = set()
    for option in LAYOUTS:
        layout.value = option
        positions = graph.layout_provider.graph_layout
        layouts.add(
            tuple(
                sorted(
                    (node_id, round(float(x), 4), round(float(y), 4))
                    for node_id, (x, y) in positions.items()
                )
            )
        )
    assert len(layouts) == len(LAYOUTS)

    relations = dict(zip(nodes.data["index"], nodes.data["relation"], strict=True))
    layout.value = "Opposing arcs"
    positions = graph.layout_provider.graph_layout
    foundation_x = [
        positions[node_id][0] for node_id, relation in relations.items() if relation == "Foundation"
    ]
    follow_on_x = [
        positions[node_id][0] for node_id, relation in relations.items() if relation == "Follow-on"
    ]
    assert all(x < 0 for x in foundation_x)
    assert all(x > 0 for x in follow_on_x)
    assert np.ptp(foundation_x) > 0.5
    assert np.ptp(follow_on_x) > 0.5

    layout.value = "Columns"
    positions = graph.layout_provider.graph_layout
    assert {
        positions[node_id][0] for node_id, relation in relations.items() if relation == "Foundation"
    } == {-1.0}
    assert {
        positions[node_id][0] for node_id, relation in relations.items() if relation == "Follow-on"
    } == {1.0}

    layout.value = "Radial timeline"
    radial_guide = document.select_one({"type": ColumnDataSource, "name": "lineage-radial-guide"})
    assert len(radial_guide.data["x"]) == len(nodes.data["index"])
    radii = np.hypot(radial_guide.data["x"], radial_guide.data["y"])
    assert np.ptp(radii) > 0.75

    layout.value = "Arc diagram"
    arc_edges = document.select_one({"type": ColumnDataSource, "name": "lineage-arc-edges"})
    assert len(arc_edges.data["xs"]) == len(edges.data["start"])
    assert all(len(path) == 32 for path in arc_edges.data["xs"])
    assert any(max(path) > -0.2 for path in arc_edges.data["ys"])
    assert not graph.edge_renderer.visible
    layout.value = LAYOUTS[0]

    initial_count = len(nodes.data["index"])
    year.value = year.start
    year.trigger("value_throttled", year.value_throttled, year.value)
    assert len(nodes.data["index"]) < initial_count
    assert all(
        relation != "Follow-on" or published <= year.value
        for relation, published in zip(nodes.data["relation"], nodes.data["year"], strict=True)
    )

    metric.value = "PageRank in this view"
    assert ranking.title.text == "Highest PageRank in this view"
    lineage_buttons.active = 1
    assert "CRISPR" in document.select_one({"type": Div, "name": "lineage-note"}).text
    assert year.start == 2012
    follow_on = next(
        value for value, label in paper.options if "Landmark" not in label and value != paper.value
    )
    paper.value = follow_on
    selected = nodes.selected.indices[0]
    assert nodes.data["index"][selected] == follow_on
    assert all(
        follow_on in (edges.data["start"][index], edges.data["end"][index])
        for index in edges.selected.indices
    )
