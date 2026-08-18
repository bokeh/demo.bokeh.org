"""Test the common presentation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from bokeh.document import Document
from bokeh.models import Button, Div, Select, Slider
from bokeh.plotting import figure

from apps._common import (
    demo_for_route,
    load_javascript,
    match_background,
    metric,
    metric_html,
    metric_row,
    prepare_document,
    responsive_row,
    set_metric,
    style_figure,
    styled_row,
    wrap_row,
)
from apps._common.colors import GOLD, GRID, INK, PAPER


def test_metric_updates_reuse_static_metadata_by_default() -> None:
    card = metric("Stable label", "0", accent=GOLD)
    set_metric(card, "1")
    assert "Stable label" in card.text
    assert ">1</strong>" in card.text

    set_metric(card, "2", label="Dynamic label")
    assert "Dynamic label" in card.text
    assert ">2</strong>" in card.text


def test_metric_html_escapes_all_inserted_values() -> None:
    html = metric_html("<label>", "<strong>unsafe</strong>", 'red" onclick="bad')

    assert "&lt;label&gt;" in html
    assert "&lt;strong&gt;unsafe&lt;/strong&gt;" in html
    assert "onclick=&#34;bad" in html
    assert "<label>" not in html


def test_metric_records_label_and_accent_as_update_metadata() -> None:
    card = metric("Population", "12", accent=GOLD)
    assert card.tags == [{"label": "Population", "accent": GOLD}]
    assert card.sizing_mode == "stretch_width"
    assert card.stylesheets


def test_load_javascript_reads_a_sidecar_once(tmp_path: Path) -> None:
    module = tmp_path / "module.py"
    sidecar = tmp_path / "callback.js"
    module.write_text("# module")
    sidecar.write_text("first")
    load_javascript.cache_clear()

    assert load_javascript(str(module), "callback.js") == "first"
    sidecar.write_text("second")
    assert load_javascript(str(module), "callback.js") == "first"


def test_demo_for_route_finds_catalog_entry() -> None:
    demo = demo_for_route("/wave-field")
    assert demo.module == "apps.heatmap"
    assert demo.title == "Wave field explorer"


def test_demo_for_route_rejects_unknown_route() -> None:
    with pytest.raises(StopIteration):
        demo_for_route("/missing")


def test_match_background_recurses_through_layout_and_styles_controls() -> None:
    nested = responsive_row(
        Div(text="Text"),
        Select(options=["One"], value="One"),
        Button(label="Go"),
        Slider(start=0, end=1, value=0.5),
    )

    match_background(nested, PAPER)

    for model in [nested, *nested.children]:
        assert model.styles["background"] == PAPER
        stylesheet = "\n".join(str(value) for value in model.stylesheets)
        if model is not nested:
            assert "color-scheme: light" in stylesheet
    assert ".bk-input" in str(nested.children[1].stylesheets)
    assert ".bk-btn" in str(nested.children[2].stylesheets)


def test_match_background_preserves_explicit_child_surface_and_avoids_duplicates() -> None:
    child = Div(text="Text", styles={"background": "#abcdef"})
    layout = responsive_row(child)

    match_background(layout, PAPER)
    first_stylesheets = list(child.stylesheets)
    match_background(layout, PAPER)

    assert child.styles["background"] == "#abcdef"
    assert child.stylesheets == first_stylesheets
    assert "#abcdef" in str(child.stylesheets)


def test_style_figure_applies_shared_colors_and_toolbar_defaults() -> None:
    plot = figure(tools="wheel_zoom")
    style_figure(plot)

    assert plot.background_fill_color == PAPER
    assert plot.border_fill_color == PAPER
    assert plot.outline_line_color == GRID
    assert plot.grid.grid_line_color == [GRID, GRID]
    assert plot.axis.axis_label_text_color == [INK, INK]
    assert plot.toolbar.autohide
    assert plot.toolbar.logo is None
    assert plot.toolbar.active_scroll is None


@pytest.mark.parametrize(
    ("builder", "css_fragment"),
    [
        (responsive_row, "flex-direction: column"),
        (metric_row, "calc(50% - 5px)"),
        (wrap_row, "flex: 1 1 140px"),
    ],
)
def test_responsive_row_helpers_attach_expected_stylesheet(builder, css_fragment: str) -> None:
    layout = builder(Div(text="One"), Div(text="Two"))
    assert css_fragment in str(layout.stylesheets)


def test_styled_row_preserves_caller_stylesheets() -> None:
    layout = styled_row("responsive", Div(text="One"), stylesheets=["base"])
    assert [str(value) for value in layout.stylesheets] == ["base", "responsive"]


def test_prepare_document_configures_metadata_theme_and_surfaces() -> None:
    document = Document()
    root = Div(text="Demo")
    document.add_root(root)

    prepare_document(document, "/wave-field")

    assert document.title == "Wave field explorer · Bokeh demos"
    assert document.theme is not None
    assert document.template_variables["demo"].route == "/wave-field"
    assert root.styles["background"] == PAPER
    assert "site_header" in document.template_variables
