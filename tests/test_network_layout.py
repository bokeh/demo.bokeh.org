"""Test the research-network layout helpers."""

from __future__ import annotations

import numpy as np
import pytest

from apps.network import LAYOUTS, arc_paths, compute_positions, shorten

NODES = [
    {"id": "foundation-a", "relation": "Foundation", "year": 1990, "citations": 20},
    {"id": "foundation-b", "relation": "Foundation", "year": 1995, "citations": 10},
    {"id": "landmark", "relation": "Landmark", "year": 2000, "citations": 100},
    {"id": "follow-a", "relation": "Follow-on", "year": 2005, "citations": 30},
    {"id": "follow-b", "relation": "Follow-on", "year": 2010, "citations": 40},
]


def test_shorten_leaves_short_titles_and_ellipsizes_long_ones() -> None:
    assert shorten("Short title", 20) == "Short title"
    assert shorten("A title with trailing words", 12) == "A title wit…"


@pytest.mark.parametrize("layout", LAYOUTS)
def test_compute_positions_includes_every_node_with_finite_coordinates(layout: str) -> None:
    positions = compute_positions(NODES, layout)

    assert set(positions) == {node["id"] for node in NODES}
    assert all(np.isfinite(coordinate) for point in positions.values() for coordinate in point)


def test_columns_puts_relationships_on_fixed_sides() -> None:
    positions = compute_positions(NODES, "Columns")
    assert positions["landmark"] == (0, 0)
    assert positions["foundation-a"][0] == positions["foundation-b"][0] == -1
    assert positions["follow-a"][0] == positions["follow-b"][0] == 1


def test_opposing_arcs_keep_foundations_and_follow_ons_apart() -> None:
    positions = compute_positions(NODES, "Opposing arcs")
    assert all(positions[node][0] < 0 for node in ("foundation-a", "foundation-b"))
    assert all(positions[node][0] > 0 for node in ("follow-a", "follow-b"))


def test_radial_timeline_moves_outward_in_chronological_order() -> None:
    positions = compute_positions(NODES, "Radial timeline")
    ordered = sorted(NODES, key=lambda node: (node["year"], node["relation"], -node["citations"]))
    radii = [np.hypot(*positions[node["id"]]) for node in ordered]
    assert np.all(np.diff(radii) > 0)


def test_arc_diagram_orders_nodes_by_year_on_one_baseline() -> None:
    positions = compute_positions(NODES, "Arc diagram")
    ordered = sorted(NODES, key=lambda node: (node["year"], node["relation"], -node["citations"]))
    x = [positions[node["id"]][0] for node in ordered]

    assert np.all(np.diff(x) > 0)
    assert {positions[node["id"]][1] for node in ordered} == {-0.76}


def test_compute_positions_rejects_unknown_layout() -> None:
    with pytest.raises(ValueError, match="Unknown network layout"):
        compute_positions(NODES, "Missing")


def test_arc_paths_join_endpoints_with_smooth_upper_arcs() -> None:
    positions = {"a": (-1.0, -0.76), "b": (1.0, -0.76)}
    xs, ys = arc_paths(positions, [{"source": "a", "target": "b"}])

    assert len(xs[0]) == len(ys[0]) == 32
    assert sorted((xs[0][0], xs[0][-1])) == pytest.approx([-1, 1])
    assert ys[0][0] == pytest.approx(-0.76)
    assert ys[0][-1] == pytest.approx(-0.76)
    assert max(ys[0]) > 0.6
