"""Test the ASGI and static routes."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from xml.etree import ElementTree

import asgi
from asgi import (
    LEGACY_DEMO_ROUTES,
    SITE_ORIGIN,
    DemoApplication,
    _counts_as_public_request,
    _render_security_txt,
    _runtime_health,
    _warm_biomass,
    application,
)
from catalog import DEMOS, LISTED_DEMOS


async def request(path: str, *, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    events: list[dict] = []
    request_path, _, query_string = path.partition("?")

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event: dict) -> None:
        events.append(event)

    await application(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": request_path,
            "raw_path": request_path.encode(),
            "query_string": query_string.encode(),
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1),
        },
        receive,
        send,
    )
    start = next(event for event in events if event["type"] == "http.response.start")
    body = b"".join(
        event.get("body", b"") for event in events if event["type"] == "http.response.body"
    )
    headers = {key.decode(): value.decode() for key, value in start["headers"]}
    return start["status"], headers, body


def test_legacy_demo_routes_redirect_to_the_updated_gallery() -> None:
    for route in LEGACY_DEMO_ROUTES:
        status, headers, body = asyncio.run(request(route))
        assert status == 302
        assert headers["location"] == "/?legacy-demo=1#demos"
        assert headers["cache-control"] == "no-store"
        assert body == b""

    status, _headers, body = asyncio.run(request("/?legacy-demo=1"))
    assert status == 200
    assert b"The demo gallery has changed." in body
    assert b"The demo gallery has changed." not in asyncio.run(request("/"))[2]


def test_health() -> None:
    status, headers, body = asyncio.run(request("/healthz"))
    assert status == 200
    assert headers["cache-control"] == "no-store"
    assert json.loads(body) == {
        "status": "ok",
        "python_gil": "enabled" if sys._is_gil_enabled() else "disabled",
    }


def test_biomass_tiles_are_lossless_webp_with_immutable_year_pair_urls(monkeypatch) -> None:
    requested: list[tuple[int, int, int, int, int, str]] = []

    def render(start: int, end: int, zoom: int, column: int, row: int, image_format: str):
        requested.append((start, end, zoom, column, row, image_format))
        return SimpleNamespace(image=b"RIFF\x08\x00\x00\x00WEBPrendered", media_type="image/webp")

    monkeypatch.setattr(asgi.shading, "query_tile", render)
    status, headers, body = asyncio.run(request("/biomass-tiles/2001/2024/3/4/2.webp"))

    assert status == 200
    assert headers["content-type"] == "image/webp"
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert body.startswith(b"RIFF")
    assert body[8:12] == b"WEBP"
    assert requested == [(2001, 2024, 3, 4, 2, "webp")]


def test_biomass_tile_route_keeps_png_compatibility(monkeypatch) -> None:
    def render(start: int, end: int, zoom: int, column: int, row: int, image_format: str):
        assert (start, end, zoom, column, row, image_format) == (2001, 2024, 3, 4, 2, "png")
        return SimpleNamespace(image=b"\x89PNG\r\n\x1a\nrendered", media_type="image/png")

    monkeypatch.setattr(asgi.shading, "query_tile", render)
    status, headers, body = asyncio.run(request("/biomass-tiles/2001/2024/3/4/2.png"))

    assert status == 200
    assert headers["content-type"] == "image/png"
    assert body.startswith(b"\x89PNG\r\n\x1a\n")


def test_biomass_tile_route_rejects_invalid_coordinates(monkeypatch) -> None:
    def render(*_args):
        raise ValueError("tile row is outside the selected zoom")

    monkeypatch.setattr(asgi.shading, "query_tile", render)
    status, headers, body = asyncio.run(request("/biomass-tiles/2000/2025/1/0/4.png"))

    assert status == 400
    assert headers["cache-control"] == "no-store"
    assert body == b"tile row is outside the selected zoom"


def test_lifespan_warms_data_before_starting_bokeh(monkeypatch) -> None:
    events: list[str] = []

    class Monitor:
        def start(self) -> None:
            events.append("monitor-start")

        def stop(self) -> None:
            events.append("monitor-stop")

    async def bokeh(_scope, _receive, _send) -> None:
        events.append("bokeh-start")

    async def receive() -> dict:
        return {"type": "lifespan.startup"}

    async def send(_event: dict) -> None:
        pass

    monkeypatch.setattr(asgi, "SERVICE_MONITOR", Monitor())
    app = DemoApplication(
        bokeh,
        b"{}",
        warmup=lambda: events.append("icechunk-warm") or 0.25,  # type: ignore[arg-type]
    )
    asyncio.run(app({"type": "lifespan"}, receive, send))

    assert events == ["monitor-start", "icechunk-warm", "bokeh-start", "monitor-stop"]


def test_biomass_warmup_compiles_renderer_before_loading_default_windows(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(asgi.shading, "warm_renderer", lambda: events.append("renderer") or 0.1)
    monkeypatch.setattr(
        asgi.icechunk_source, "warm_default_windows", lambda: events.append("icechunk") or 0.2
    )
    monkeypatch.setattr(
        asgi.shading, "warm_initial_tiles", lambda: events.append("initial-tiles") or 0.3
    )

    elapsed = _warm_biomass()

    assert events == ["renderer", "icechunk", "initial-tiles"]
    assert elapsed >= 0


def test_every_http_response_has_the_shared_browser_policy() -> None:
    expected = {
        "referrer-policy": "strict-origin-when-cross-origin",
        "strict-transport-security": "max-age=31536000",
        "x-content-type-options": "nosniff",
        "x-frame-options": "SAMEORIGIN",
    }

    application_headers: dict[str, str] = {}
    for path in ("/", "/airport-access", "/missing-demo", "/assets/site.css"):
        _status, headers, _body = asyncio.run(request(path))
        assert expected.items() <= headers.items()
        if path == "/airport-access":
            application_headers = headers

    assert application_headers["cache-control"] == "no-store"


def test_health_reports_an_unexpected_enabled_gil_as_degraded() -> None:
    health = _runtime_health({"PYTHON_GIL": "0"}, gil_enabled=lambda: True)

    assert json.loads(health) == {
        "status": "degraded",
        "reason": "python_gil_enabled",
        "python_gil": "enabled",
    }


def test_public_request_counter_excludes_monitor_and_health_traffic() -> None:
    assert _counts_as_public_request("/")
    assert _counts_as_public_request("/airport-access")
    assert not _counts_as_public_request("/assets/site.css")
    assert not _counts_as_public_request("/favicon.ico")
    assert not _counts_as_public_request("/healthz")
    assert not _counts_as_public_request("/robots.txt")
    assert not _counts_as_public_request("/sitemap.xml")
    assert not _counts_as_public_request("/monitor")
    assert not _counts_as_public_request("/monitor/ws")


def test_index_head_has_no_body() -> None:
    status, headers, body = asyncio.run(request("/", method="HEAD"))
    assert status == 200
    assert int(headers["content-length"]) > 1000
    assert body == b""


def test_css_asset() -> None:
    status, headers, body = asyncio.run(request("/assets/site.css"))
    assert status == 200
    assert headers["content-type"].startswith("text/css")
    assert b".site-header" in body


def test_favicon() -> None:
    status, headers, body = asyncio.run(request("/favicon.ico"))
    assert status == 200
    assert headers["content-type"] == "image/png"
    assert body.startswith(b"\x89PNG\r\n\x1a\n")

    status, headers, body = asyncio.run(request("/assets/bokeh-icon.svg"))
    assert status == 200
    assert headers["content-type"] == "image/svg+xml"
    assert b'<svg id="Layer_1"' in body


def test_robots_points_to_the_catalog_sitemap_without_advertising_monitor() -> None:
    status, headers, body = asyncio.run(request("/robots.txt"))

    assert status == 200
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert headers["cache-control"] == "public, max-age=3600"
    assert body.decode().splitlines() == [
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: {SITE_ORIGIN}/sitemap.xml",
    ]
    assert "/monitor" not in body.decode()


def test_sitemap_contains_only_the_homepage_and_listed_catalog_demos() -> None:
    status, headers, body = asyncio.run(request("/sitemap.xml"))

    assert status == 200
    assert headers["content-type"] == "application/xml; charset=utf-8"
    assert headers["cache-control"] == "public, max-age=3600"
    root = ElementTree.fromstring(body)
    namespace = {"sitemap": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = [element.text for element in root.findall("sitemap:url/sitemap:loc", namespace)]
    assert locations == [
        f"{SITE_ORIGIN}/",
        *(f"{SITE_ORIGIN}{demo.route}" for demo in LISTED_DEMOS),
    ]
    assert f"{SITE_ORIGIN}/monitor" not in locations
    assert all(f"{SITE_ORIGIN}{route}" not in locations for route in LEGACY_DEMO_ROUTES)


def test_security_txt_uses_the_private_reporting_policy() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    text = _render_security_txt(now).decode()

    assert text.splitlines() == [
        "Contact: https://tidelift.com/security",
        "Expires: 2027-08-18T12:00:00Z",
        f"Canonical: {SITE_ORIGIN}/.well-known/security.txt",
        "Policy: https://github.com/bokeh/bokeh/security/policy",
        "Preferred-Languages: en",
    ]

    status, headers, body = asyncio.run(request("/.well-known/security.txt"))
    assert status == 200
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert headers["cache-control"] == "public, max-age=3600"
    assert body.startswith(b"Contact: https://tidelift.com/security\n")


def test_every_catalog_preview_is_a_served_image() -> None:
    for demo in DEMOS:
        status, headers, body = asyncio.run(request(f"/assets/{demo.preview}"))
        assert status == 200
        assert headers["content-type"] == "image/jpeg"
        assert len(body) > 8_000

    status, headers, body = asyncio.run(request("/assets/social-preview.png"))
    assert status == 200
    assert headers["content-type"] == "image/png"
    assert body.startswith(b"\x89PNG\r\n\x1a\n")


def test_static_rejects_post() -> None:
    status, headers, body = asyncio.run(request("/healthz", method="POST"))
    assert status == 405
    assert headers["allow"] == "GET, HEAD"
    assert body == b""


def test_asset_path_cannot_escape() -> None:
    status, headers, body = asyncio.run(request("/assets/../asgi.py"))
    assert status == 404
    assert headers["content-type"].startswith("text/html")
    assert b"Node not <em>connected.</em>" in body


def test_shared_not_found_page() -> None:
    status, headers, body = asyncio.run(request("/404.html"))
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"Node not <em>connected.</em>" in body
    assert b"Rendered with Bokeh" in body

    status, headers, missing_body = asyncio.run(request("/missing-demo"))
    assert status == 404
    assert headers["content-type"].startswith("text/html")
    assert missing_body == body
