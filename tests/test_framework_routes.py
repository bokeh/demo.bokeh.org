"""Test isolated static framework pages without requiring a frontend build."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import asgi
from catalog import DEMOS

ROUTES = ("/react", "/vue", "/svelte", "/components", "/nextjs", "/next.js")


async def request(path: str, *, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    events: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event: dict) -> None:
        events.append(event)

    await asgi.application(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1),
        },
        receive,
        send,
    )
    start = next(event for event in events if event["type"] == "http.response.start")
    headers = {key.decode(): value.decode() for key, value in start["headers"]}
    body = b"".join(
        event.get("body", b"") for event in events if event["type"] == "http.response.body"
    )
    return start["status"], headers, body


@pytest.fixture
def framework_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for framework in ("react", "vue", "svelte", "components", "nextjs"):
        page = tmp_path / "frameworks" / framework / "index.html"
        page.parent.mkdir(parents=True)
        page.write_text(f"<!doctype html><title>{framework}</title>")
    for relative in ("assets/shared.js", "nextjs/_next/static/chunks/chart.js"):
        asset = tmp_path / "frameworks" / relative
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("export const source = 'npm';")
    monkeypatch.setattr(asgi, "ASSET_ROOT", tmp_path)

    async def unexpected_bokeh(_scope: dict, _receive, _send) -> None:
        pytest.fail("A static framework request reached the Python Bokeh application")

    monkeypatch.setattr(asgi.application, "_bokeh", unexpected_bokeh)
    return tmp_path


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("suffix", ["", "/"])
def test_framework_pages_are_static_and_share_browser_policy(
    framework_site: Path, route: str, suffix: str
) -> None:
    status, headers, body = asyncio.run(request(f"{route}{suffix}"))
    framework = "nextjs" if route == "/next.js" else route.lstrip("/")

    assert status == 200
    assert body == (framework_site / "frameworks" / framework / "index.html").read_bytes()
    assert headers["content-type"] == "text/html"
    assert headers["cache-control"] == "no-cache"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert headers["strict-transport-security"] == "max-age=31536000"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert asgi._counts_as_public_request(f"{route}{suffix}")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.usefixtures("framework_site")
def test_framework_pages_support_head_and_reject_post(route: str) -> None:
    status, headers, body = asyncio.run(request(route, method="HEAD"))
    assert status == 200
    assert int(headers["content-length"]) > 0
    assert body == b""

    status, headers, body = asyncio.run(request(route, method="POST"))
    assert status == 405
    assert headers["allow"] == "GET, HEAD"
    assert body == b""


@pytest.mark.parametrize("relative", ["assets/shared.js", "nextjs/_next/static/chunks/chart.js"])
def test_framework_bundles_use_the_existing_asset_route(
    framework_site: Path, relative: str
) -> None:
    route = f"/assets/frameworks/{relative}"
    status, headers, body = asyncio.run(request(route))

    assert status == 200
    assert body == (framework_site / "frameworks" / relative).read_bytes()
    assert headers["content-type"] in {"text/javascript", "application/javascript"}
    assert headers["cache-control"] == "public, max-age=3600"
    assert not asgi._counts_as_public_request(route)


def test_missing_build_and_asset_traversal_use_the_shared_404(framework_site: Path) -> None:
    (framework_site / "frameworks" / "react" / "index.html").unlink()
    (framework_site.parent / "outside.txt").write_text("outside the asset root")

    for route in ("/react", "/assets/frameworks/../../outside.txt"):
        status, _headers, body = asyncio.run(request(route))
        assert status == 404
        assert body == asgi.application._not_found
        assert b"outside the asset root" not in body


@pytest.mark.usefixtures("framework_site")
def test_framework_pages_are_absent_from_existing_gallery_and_sitemap() -> None:
    status, _headers, homepage = asyncio.run(request("/"))
    assert status == 200
    status, _headers, sitemap = asyncio.run(request("/sitemap.xml"))
    assert status == 200

    assert not set(ROUTES).intersection(demo.route for demo in DEMOS)
    assert b"/assets/frameworks/" not in homepage
    for route in ROUTES:
        assert f'href="{route}"'.encode() not in homepage
        assert f"<loc>{asgi.SITE_ORIGIN}{route}</loc>".encode() not in sitemap
