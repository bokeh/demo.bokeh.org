"""Test the demo catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
from bokeh.document import Document

import catalog
from catalog import DEMOS, RoadmapItem, demo_from, load_applications, load_manifest

ROOT = Path(__file__).parents[1]

DEMO_TEMPLATE = """
[[demos]]
route = "{route}"
module = "apps.example"
source = "{source}"
title = "Example"
eyebrow = "Test"
description = "Example description."
domain = "Testing"
runtime = "Python / ASGI"
tags = ["one", "two", "three", "four"]
accent = "gold"
preview = "example-preview.jpg"
"""


def configure_manifest(monkeypatch, tmp_path: Path, contents: str) -> None:
    manifest = tmp_path / "catalog.toml"
    manifest.write_text(contents)
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    monkeypatch.setattr(catalog, "MANIFEST", manifest)


def test_routes_are_unique_and_absolute() -> None:
    routes = [demo.route for demo in DEMOS]
    assert len(routes) == len(set(routes))
    assert all(route.startswith("/") and route != "/" for route in routes)


def test_every_application_constructs_a_document() -> None:
    applications = load_applications()
    assert set(applications) == {demo.route for demo in DEMOS}
    for demo in DEMOS:
        document = Document()
        applications[demo.route](document)
        assert len(document.roots) == 1
        assert demo.title in document.title
        assert "site_header" in document.template_variables
        assert 'href="/#run-locally"' in document.template


def test_catalog_covers_multiple_domains() -> None:
    assert len({demo.domain for demo in DEMOS}) == len(DEMOS)
    assert len({demo.preview for demo in DEMOS}) == len(DEMOS)
    assert all(demo.preview.endswith("-preview.jpg") for demo in DEMOS)
    assert all(len(demo.tags) >= 4 for demo in DEMOS)


def test_catalog_links_to_each_application_source() -> None:
    for demo in DEMOS:
        assert (ROOT / demo.source).is_file()
        assert demo.source_url.endswith(f"/{demo.source}")

    packaged = {
        "apps.cellular_automata",
        "apps.image_lab",
        "apps.network",
        "apps.spectrum",
        "apps.task_scheduler",
        "apps.terrain",
    }
    assert all(demo.source.endswith("/__init__.py") for demo in DEMOS if demo.module in packaged)


def test_catalog_uses_lab_for_only_one_demo() -> None:
    lab_titles = [demo.title for demo in DEMOS if "lab" in demo.title.casefold().split()]
    assert lab_titles == ["Radio spectrum lab"]
    climate = next(demo for demo in DEMOS if demo.route == "/climate")
    assert climate.title == "Seattle weather comparison"


def test_catalog_calls_out_ecosystem_and_math_examples() -> None:
    tags = {tag.casefold() for demo in DEMOS for tag in demo.tags}
    assert {"networkx", "xarray", "numba", "mathtext"} <= tags


def test_demo_from_normalizes_tags_without_mutating_input() -> None:
    values = {
        "route": "/example",
        "module": "apps.example",
        "source": "apps/example.py",
        "title": "Example",
        "eyebrow": "Test",
        "description": "Description",
        "domain": "Testing",
        "runtime": "Python / ASGI",
        "tags": ["one", "two"],
        "accent": "gold",
        "preview": "example.jpg",
    }
    demo = demo_from(values)

    assert demo.tags == ("one", "two")
    assert values["tags"] == ["one", "two"]
    assert demo.source_url.endswith("/apps/example.py")


def test_load_manifest_parses_demos_and_roadmap(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "apps" / "example.py"
    source.parent.mkdir()
    source.write_text("def modify_document(document): pass")
    contents = (
        DEMO_TEMPLATE.format(route="/example", source="apps/example.py")
        + """
[[roadmap]]
state = "Planned"
title = "More examples"
description = "Add more runtimes."
accent = "teal"
"""
    )
    configure_manifest(monkeypatch, tmp_path, contents)

    demos, roadmap = load_manifest()

    assert [demo.route for demo in demos] == ["/example"]
    assert demos[0].tags == ("one", "two", "three", "four")
    assert roadmap == (RoadmapItem("Planned", "More examples", "Add more runtimes.", "teal"),)


def test_load_manifest_requires_at_least_one_demo(monkeypatch, tmp_path: Path) -> None:
    configure_manifest(monkeypatch, tmp_path, "")
    with pytest.raises(ValueError, match="does not define any demos"):
        load_manifest()


def test_load_manifest_rejects_duplicate_routes(monkeypatch, tmp_path: Path) -> None:
    contents = DEMO_TEMPLATE.format(route="/same", source="first.py")
    contents += DEMO_TEMPLATE.format(route="/same", source="second.py")
    configure_manifest(monkeypatch, tmp_path, contents)
    with pytest.raises(ValueError, match="duplicate routes"):
        load_manifest()


@pytest.mark.parametrize("route", ["example", "/"])
def test_load_manifest_rejects_invalid_routes(monkeypatch, tmp_path: Path, route: str) -> None:
    contents = DEMO_TEMPLATE.format(route=route, source="missing.py")
    configure_manifest(monkeypatch, tmp_path, contents)
    with pytest.raises(ValueError, match="invalid routes"):
        load_manifest()


def test_load_manifest_rejects_missing_source(monkeypatch, tmp_path: Path) -> None:
    contents = DEMO_TEMPLATE.format(route="/example", source="missing.py")
    configure_manifest(monkeypatch, tmp_path, contents)
    with pytest.raises(ValueError, match="references missing sources"):
        load_manifest()
