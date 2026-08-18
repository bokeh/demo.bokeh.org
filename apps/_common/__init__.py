"""Provide internal styling and layout helpers for the demo applications."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from bokeh.events import DocumentReady
from bokeh.layouts import row
from bokeh.models import (
    Button,
    CustomJS,
    Div,
    MultiChoice,
    Paragraph,
    RangeSlider,
    Select,
    Slider,
    Toggle,
)
from jinja2 import Environment, FileSystemLoader, select_autoescape

from catalog import DEMOS
from presentation import SITE, configure_document

from . import colors
from .activity import PUBLIC_ACTIVITY
from .callbacks import on_throttled_value as on_throttled_value
from .performance import monitor_document
from .streaming import PeriodicCoalescer as PeriodicCoalescer

REMOVE_LOADING_JS = (SITE / "remove_loading.js").read_text()
ASSETS = Path(__file__).parent
TEMPLATE_ENVIRONMENT = Environment(
    loader=FileSystemLoader(ASSETS),
    autoescape=select_autoescape(("html", "xml", "jinja")),
    trim_blocks=True,
    lstrip_blocks=True,
)
BACKGROUND_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("background.css.jinja")
METRIC_TEMPLATE = TEMPLATE_ENVIRONMENT.get_template("metric.html.jinja")
METRIC_CSS = (ASSETS / "metric.css").read_text()
METRIC_ROW_CSS = (ASSETS / "metric_row.css").read_text()
STACK_ROW_CSS = (ASSETS / "stack_row.css").read_text()
WRAP_ROW_CSS = (ASSETS / "wrap_row.css").read_text()


@cache
def load_javascript(module_file: str, filename: str) -> str:
    """Load a JavaScript file next to an application module."""
    return Path(module_file).with_name(filename).read_text()


def demo_for_route(route: str):
    """Return the catalog entry for an application route."""
    return next(demo for demo in DEMOS if demo.route == route)


def prepare_document(document, route: str, *, measure_performance: bool = True) -> None:
    """Apply shared metadata, loading behavior, theme, and surface colors."""
    configure_document(document, demo_for_route(route))
    document.js_on_event(DocumentReady, CustomJS(code=REMOVE_LOADING_JS))
    document.theme = "light_minimal"
    for root in document.roots:
        match_background(root, colors.PAPER)
    if route != "/monitor":
        PUBLIC_ACTIVITY.track_session(document)
    if measure_performance:
        monitor_document(document, route).start(document)


def match_background(model, background: str) -> None:
    """Match unstyled Bokeh layout and control surfaces to their container."""
    surface_background = background
    if hasattr(model, "styles"):
        styles = dict(model.styles)
        if "background" not in styles and "background-color" not in styles:
            styles["background"] = background
            model.styles = styles
        surface_background = styles.get("background", styles.get("background-color", background))

    if isinstance(model, (Select, MultiChoice)):
        control = "input"
    elif isinstance(model, (Button, Toggle)):
        control = "button"
    elif isinstance(model, (Slider, RangeSlider, Div, Paragraph)):
        control = "surface"
    else:
        control = None

    if control is not None:
        stylesheet = BACKGROUND_TEMPLATE.render(
            background=surface_background, control=control, ink=colors.INK, teal=colors.TEAL
        )
    else:
        stylesheet = ""

    if stylesheet and stylesheet not in model.stylesheets:
        model.stylesheets = [*model.stylesheets, stylesheet]

    for child in getattr(model, "children", []):
        match_background(child, surface_background)


def style_figure(plot) -> None:
    """Apply the shared light plot theme and unobtrusive toolbar defaults."""
    plot.background_fill_color = colors.PAPER
    plot.border_fill_color = colors.PAPER
    plot.outline_line_color = colors.GRID
    plot.grid.grid_line_color = colors.GRID
    plot.grid.grid_line_alpha = 0.55
    plot.axis.axis_line_color = "#a89fa3"
    plot.axis.major_tick_line_color = "#a89fa3"
    plot.axis.minor_tick_line_color = None
    plot.axis.major_label_text_color = colors.MUTED
    plot.axis.axis_label_text_color = colors.INK
    plot.toolbar.autohide = True
    plot.toolbar.logo = None
    plot.toolbar.active_scroll = None


def responsive_row(*children, **kwargs):
    """Keep a horizontal desktop composition and stack it on narrow screens."""
    return styled_row(STACK_ROW_CSS, *children, **kwargs)


def metric_row(*children, **kwargs):
    """Wrap summary cards into two columns on narrow screens."""
    return styled_row(METRIC_ROW_CSS, *children, **kwargs)


def wrap_row(*children, **kwargs):
    """Let compact controls wrap without forcing horizontal page scrolling."""
    return styled_row(WRAP_ROW_CSS, *children, **kwargs)


def styled_row(stylesheet: str, *children, **kwargs):
    """Build a row with an additional component-scoped stylesheet."""
    stylesheets = [*kwargs.pop("stylesheets", []), stylesheet]
    return row(*children, stylesheets=stylesheets, **kwargs)


def metric(label: str, value: str, *, accent: str = colors.CORAL) -> Div:
    """Create a summary card whose value can be updated in place."""
    return Div(
        text=metric_html(label, value, accent),
        sizing_mode="stretch_width",
        stylesheets=[METRIC_CSS],
        tags=[{"label": label, "accent": accent}],
    )


def set_metric(card: Div, value: str, *, label: str | None = None) -> None:
    """Update a summary card value and optionally replace its label."""
    metadata = card.tags[0]
    card.text = metric_html(
        label if label is not None else metadata["label"], value, metadata["accent"]
    )


def metric_html(label: str, value: str, accent: str) -> str:
    """Render escaped summary-card markup from the shared template."""
    return METRIC_TEMPLATE.render(label=label, value=value, accent=accent)
