"""Load demo metadata and application entry points."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from tomllib import load
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bokeh.document import Document


ROOT = Path(__file__).parent
MANIFEST = ROOT / "catalog.toml"
SOURCE_BASE_URL = "https://github.com/bokeh/demo.bokeh.org/blob/main"


@dataclass(frozen=True)
class Demo:
    route: str
    module: str
    source: str
    title: str
    eyebrow: str
    description: str
    domain: str
    runtime: str
    tags: tuple[str, ...]
    accent: str
    preview: str

    @property
    def source_url(self) -> str:
        return f"{SOURCE_BASE_URL}/{self.source}"


@dataclass(frozen=True)
class RoadmapItem:
    state: str
    title: str
    description: str
    accent: str


def demo_from(data: dict[str, Any]) -> Demo:
    values = dict(data)
    values["tags"] = tuple(cast(list[str], values["tags"]))
    return Demo(**values)


def load_manifest() -> tuple[tuple[Demo, ...], tuple[RoadmapItem, ...]]:
    with MANIFEST.open("rb") as manifest:
        data = load(manifest)

    demos = tuple(demo_from(item) for item in cast(list[dict[str, Any]], data.get("demos", [])))
    roadmap = tuple(
        RoadmapItem(**item) for item in cast(list[dict[str, Any]], data.get("roadmap", []))
    )
    if not demos:
        raise ValueError(f"{MANIFEST} does not define any demos")

    routes = [demo.route for demo in demos]
    if len(routes) != len(set(routes)):
        raise ValueError(f"{MANIFEST} contains duplicate routes")
    if invalid_routes := [route for route in routes if not route.startswith("/") or route == "/"]:
        raise ValueError(f"{MANIFEST} contains invalid routes: {invalid_routes}")

    missing_sources = [demo.source for demo in demos if not (ROOT / demo.source).is_file()]
    if missing_sources:
        raise ValueError(f"{MANIFEST} references missing sources: {missing_sources}")

    return demos, roadmap


DEMOS, RUNTIME_ROADMAP = load_manifest()


def load_applications() -> Mapping[str, Callable[[Document], None]]:
    applications: dict[str, Callable[[Document], None]] = {}
    for demo in DEMOS:
        modify_document = import_module(demo.module).modify_document
        applications[demo.route] = modify_document
    return applications
