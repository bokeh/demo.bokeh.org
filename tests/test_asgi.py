"""Test the ASGI and static routes."""

from __future__ import annotations

import asyncio

from asgi import LEGACY_DEMO_ROUTES, application
from catalog import DEMOS


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
    assert body == b'{"status":"ok"}\n'


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


def test_every_catalog_preview_is_a_served_image() -> None:
    for demo in DEMOS:
        status, headers, body = asyncio.run(request(f"/assets/{demo.preview}"))
        assert status == 200
        assert headers["content-type"] == "image/jpeg"
        assert len(body) > 8_000


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
