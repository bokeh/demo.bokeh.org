"""Test the shared site presentation."""

from __future__ import annotations

from dataclasses import replace

from bokeh.document import Document
from bokeh.models import (
    Button,
    Div,
    MultiChoice,
    Paragraph,
    RangeSlider,
    Row,
    Select,
    Slider,
    Toggle,
    Toolbar,
    WheelZoomTool,
)

import presentation
from catalog import DEMOS, LISTED_DEMOS, load_applications
from presentation import (
    APP_TEMPLATE,
    SITE_FOOTER,
    SITE_HEADER,
    SITE_ORIGIN,
    configure_document,
    render_index,
)


def test_every_application_stacks_its_main_composition_on_narrow_screens() -> None:
    for application_handler in load_applications().values():
        document = Document()
        application_handler(document)
        stylesheets = [
            str(stylesheet)
            for layout in document.select({"type": Row})
            for stylesheet in layout.stylesheets
        ]
        assert any(
            "max-width: 700px" in stylesheet and "flex-direction: column" in stylesheet
            for stylesheet in stylesheets
        )


def test_wheel_zoom_is_never_active_by_default() -> None:
    for application_handler in load_applications().values():
        document = Document()
        application_handler(document)
        for toolbar in document.select({"type": Toolbar}):
            if any(isinstance(tool, WheelZoomTool) for tool in toolbar.tools):
                assert toolbar.active_scroll is None


def test_text_and_control_surfaces_do_not_fall_back_to_bright_white() -> None:
    surface_types = (Div, Paragraph, Select, MultiChoice, Slider, RangeSlider, Button, Toggle)
    for application_handler in load_applications().values():
        document = Document()
        application_handler(document)
        for model_type in surface_types:
            for model in document.select({"type": model_type}):
                background = model.styles.get("background")
                assert background is not None
                assert background.casefold() not in {"white", "#fff", "#ffffff"}
                assert any(background in str(stylesheet) for stylesheet in model.stylesheets)
                assert any(
                    "color-scheme: light" in str(stylesheet) for stylesheet in model.stylesheets
                )


def test_landing_page_comes_from_catalog() -> None:
    html = render_index().decode()
    assert SITE_HEADER.strip() in html
    assert 'href="https://github.com/bokeh/tutorial"' not in SITE_HEADER
    assert (
        '<link rel="icon" href="/assets/bokeh-icon.svg?v=2" type="image/svg+xml" sizes="any">'
        in html
    )
    assert '<link rel="icon" href="/favicon.ico?v=2" type="image/png" sizes="16x16">' in html
    assert f'<link rel="canonical" href="{SITE_ORIGIN}/">' in html
    assert (
        f'<meta property="og:image" content="{SITE_ORIGIN}/assets/social-preview.png?v=1">' in html
    )
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert '<section class="asgi-band"' in html
    assert 'id="run-locally"' in html
    assert "Bokeh in action" in html
    assert "Clone, uv run, done." in html
    assert "Uvicorn / Hypercorn / etc." in html
    assert html.count("↔") == 2
    assert "section-kicker" not in html
    assert "Planned additions" not in html
    assert "runtime-section" not in html
    assert "uv run --locked uvicorn asgi:application" in html
    assert 'class="demo-card featured' not in html
    for demo in LISTED_DEMOS:
        assert f'href="{demo.route}"' in html
        assert demo.title in html
        assert f"/assets/{demo.preview}?v=11" in html


def test_landing_page_legacy_notice_is_opt_in() -> None:
    ordinary = render_index().decode()
    legacy = render_index(show_legacy_notice=True).decode()

    assert "legacy-notice" not in ordinary
    assert "legacy-notice" in legacy
    assert "The demo gallery has changed" in legacy


def test_landing_page_escapes_catalog_content(monkeypatch) -> None:
    unsafe = replace(LISTED_DEMOS[0], title="<script>alert('bad')</script>")
    monkeypatch.setattr(presentation, "LISTED_DEMOS", (unsafe,))

    html = render_index().decode()

    assert "&lt;script&gt;alert" in html
    assert "<script>alert" not in html


def test_configure_document_installs_shared_application_chrome() -> None:
    document = Document()
    demo = DEMOS[0]

    configure_document(document, demo)

    assert document.title == f"{demo.title} · Bokeh demos"
    assert document.template == APP_TEMPLATE
    assert "View demo source code" in document.template
    assert document.template_variables == {
        "demo": demo,
        "site_origin": SITE_ORIGIN,
        "site_header": SITE_HEADER,
        "site_footer": SITE_FOOTER,
    }
    assert '<meta name="description" content="{{ demo.description }}">' in document.template
    assert '<link rel="canonical" href="{{ site_origin }}{{ demo.route }}">' in document.template
    assert (
        '<meta property="og:title" content="{{ demo.title }} · Bokeh demos">' in document.template
    )
