"""Render the shared site chrome and configure Bokeh documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from bokeh.document import Document
from jinja2 import Environment, FileSystemLoader, select_autoescape

from catalog import DEMOS, Demo

ROOT = Path(__file__).parent
SITE = ROOT / "site"

TEMPLATE_ENVIRONMENT = Environment(
    loader=FileSystemLoader(SITE),
    autoescape=select_autoescape(("html", "xml", "jinja")),
    trim_blocks=True,
    lstrip_blocks=True,
)
SITE_HEADER = TEMPLATE_ENVIRONMENT.get_template("header.html.jinja").render()
SITE_FOOTER = TEMPLATE_ENVIRONMENT.get_template("footer.html.jinja").render()
INDEX_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("index.html.jinja")
APP_TEMPLATE = (SITE / "application.html.jinja").read_text()


def render_index(*, show_legacy_notice: bool = False) -> bytes:
    return INDEX_TEMPLATE.render(
        demos=DEMOS,
        site_header=SITE_HEADER,
        site_footer=SITE_FOOTER,
        show_legacy_notice=show_legacy_notice,
    ).encode()


def configure_document(document: Document, demo: Demo) -> None:
    document.title = f"{demo.title} · Bokeh demos"
    document.template = cast(Any, APP_TEMPLATE)
    document.template_variables.update(
        {"demo": demo, "site_header": SITE_HEADER, "site_footer": SITE_FOOTER}
    )
