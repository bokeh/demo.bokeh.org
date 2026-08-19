"""Expose the demo catalog as a Bokeh ASGI application."""

from __future__ import annotations

import logging
import mimetypes
import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs
from xml.sax.saxutils import escape

from bokeh.server.asgi import BokehASGI

from apps._common.activity import PUBLIC_ACTIVITY, PublicActivity
from catalog import DEMOS, LISTED_DEMOS, load_applications
from presentation import ROOT, SITE_ORIGIN, render_index

os.environ.setdefault("BOKEH_RESOURCES", "cdn")

logging.basicConfig(level=os.environ.get("BOKEH_LOG_LEVEL", "info").upper())

type Message = dict[str, Any]
type Receive = Callable[[], Awaitable[Message]]
type Scope = dict[str, Any]
type Send = Callable[[Message], Awaitable[None]]

ASSET_ROOT = ROOT / "site"
LEGACY_DEMO_ROUTES = frozenset(
    {
        "/crossfilter",
        "/export_csv",
        "/gapminder",
        "/movies",
        "/population",
        "/selection_histogram",
        "/sliders",
        "/surface3d",
        "/weather",
    }
)


def _render_sitemap() -> bytes:
    locations = (f"{SITE_ORIGIN}/", *(f"{SITE_ORIGIN}{demo.route}" for demo in LISTED_DEMOS))
    urls = "\n".join(f"  <url><loc>{escape(location)}</loc></url>" for location in locations)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    ).encode()


SITEMAP = _render_sitemap()
ROBOTS = (f"User-agent: *\nAllow: /\n\nSitemap: {SITE_ORIGIN}/sitemap.xml\n").encode()
STANDARD_HEADERS = (
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"strict-transport-security", b"max-age=31536000"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"SAMEORIGIN"),
)
PUBLIC_PAGE_ROUTES = frozenset(
    {
        "/",
        "/index.html",
        *LEGACY_DEMO_ROUTES,
        *(demo.route for demo in DEMOS if demo.route != "/monitor"),
    }
)


class DemoApplication:
    def __init__(
        self, bokeh: BokehASGI, runtime_health: bytes, *, activity: PublicActivity = PUBLIC_ACTIVITY
    ) -> None:
        self._bokeh = bokeh
        self._runtime_health = runtime_health
        self._activity = activity
        self._index = render_index()
        self._legacy_index = render_index(show_legacy_notice=True)
        self._not_found = (ASSET_ROOT / "404.html").read_bytes()
        self._security = _render_security_txt()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        path = scope.get("path", "/")
        if scope_type == "http" and _counts_as_public_request(path):
            self._activity.record_request()

        if scope_type == "lifespan":
            await self._bokeh(scope, receive, send)
        elif scope_type == "http" and path.rstrip("/") in LEGACY_DEMO_ROUTES:
            await self._redirect(scope, send, "/?legacy-demo=1#demos")
        elif scope_type == "http" and path in ("/", "/index.html"):
            query = parse_qs(scope.get("query_string", b"").decode())
            index = self._legacy_index if "legacy-demo" in query else self._index
            await self._response(scope, send, index, "text/html; charset=utf-8")
        elif scope_type == "http" and path == "/robots.txt":
            await self._response(
                scope,
                send,
                ROBOTS,
                "text/plain; charset=utf-8",
                cache_control="public, max-age=3600",
            )
        elif scope_type == "http" and path == "/sitemap.xml":
            await self._response(
                scope,
                send,
                SITEMAP,
                "application/xml; charset=utf-8",
                cache_control="public, max-age=3600",
            )
        elif scope_type == "http" and path == "/.well-known/security.txt":
            await self._response(
                scope,
                send,
                self._security,
                "text/plain; charset=utf-8",
                cache_control="public, max-age=3600",
            )
        elif scope_type == "http" and path == "/healthz":
            await self._response(
                scope,
                send,
                self._runtime_health,
                "application/json; charset=utf-8",
                cache_control="no-store",
            )
        elif scope_type == "http" and path == "/favicon.ico":
            await self._asset(scope, send, "favicon.png")
        elif scope_type == "http" and path == "/404.html":
            await self._response(scope, send, self._not_found, "text/html; charset=utf-8")
        elif scope_type == "http" and path.startswith("/assets/"):
            await self._asset(scope, send, path.removeprefix("/assets/"))
        elif scope_type == "http":
            await self._bokeh_or_not_found(scope, receive, send)
        else:
            await self._bokeh(scope, receive, send)

    async def _bokeh_or_not_found(self, scope: Scope, receive: Receive, send: Send) -> None:
        not_found = False

        async def intercept(message: Message) -> None:
            nonlocal not_found
            if message["type"] == "http.response.start":
                not_found = message["status"] == 404
                if not not_found:
                    message = dict(message)
                    message["headers"] = _with_standard_headers(
                        message.get("headers", []), cache_control="no-store"
                    )
            if not not_found:
                await send(message)

        await self._bokeh(scope, receive, intercept)
        if not_found:
            await self._not_found_response(scope, send)

    async def _asset(self, scope: Scope, send: Send, relative: str) -> None:
        candidate = (ASSET_ROOT / relative).resolve()
        if ASSET_ROOT.resolve() not in candidate.parents or not candidate.is_file():
            await self._not_found_response(scope, send)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        await self._response(
            scope, send, candidate.read_bytes(), content_type, cache_control="public, max-age=3600"
        )

    async def _not_found_response(self, scope: Scope, send: Send) -> None:
        await self._response(scope, send, self._not_found, "text/html; charset=utf-8", status=404)

    @staticmethod
    async def _response(
        scope: Scope,
        send: Send,
        body: bytes,
        content_type: str,
        *,
        status: int = 200,
        cache_control: str = "no-cache",
    ) -> None:
        method = scope.get("method", "GET").upper()
        if method not in ("GET", "HEAD"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 405,
                    "headers": _with_standard_headers(
                        [(b"allow", b"GET, HEAD"), (b"content-length", b"0")],
                        cache_control="no-store",
                    ),
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        headers = [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
        ]
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": _with_standard_headers(headers, cache_control=cache_control),
            }
        )
        await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})

    @staticmethod
    async def _redirect(scope: Scope, send: Send, location: str) -> None:
        method = scope.get("method", "GET").upper()
        if method not in ("GET", "HEAD"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 405,
                    "headers": _with_standard_headers(
                        [(b"allow", b"GET, HEAD"), (b"content-length", b"0")],
                        cache_control="no-store",
                    ),
                }
            )
        else:
            await send(
                {
                    "type": "http.response.start",
                    "status": 302,
                    "headers": _with_standard_headers(
                        [(b"location", location.encode()), (b"content-length", b"0")],
                        cache_control="no-store",
                    ),
                }
            )
        await send({"type": "http.response.body", "body": b""})


def create_application() -> DemoApplication:
    origins = [
        origin.strip()
        for origin in os.environ.get("BOKEH_ALLOW_WS_ORIGIN", "").split(",")
        if origin.strip()
    ]
    applications = load_applications()
    bokeh = BokehASGI(applications, redirect_root=False, extra_websocket_origins=origins)
    return DemoApplication(bokeh, _runtime_health())


def _counts_as_public_request(path: str) -> bool:
    """Count page entry requests without monitor, health, or asset traffic."""
    return path in PUBLIC_PAGE_ROUTES


def _render_security_txt(now: datetime | None = None) -> bytes:
    """Render an RFC 9116 contact whose expiry advances with each deployment."""
    expires = (now or datetime.now(UTC)) + timedelta(days=364)
    return (
        "Contact: https://tidelift.com/security\n"
        f"Expires: {expires.isoformat(timespec='seconds').replace('+00:00', 'Z')}\n"
        f"Canonical: {SITE_ORIGIN}/.well-known/security.txt\n"
        "Policy: https://github.com/bokeh/bokeh/security/policy\n"
        "Preferred-Languages: en\n"
    ).encode()


def _with_standard_headers(
    headers: list[tuple[bytes, bytes]], *, cache_control: str
) -> list[tuple[bytes, bytes]]:
    """Add browser policy headers without overriding an upstream response."""
    result = list(headers)
    names = {name.lower() for name, _value in result}
    if b"cache-control" not in names:
        result.append((b"cache-control", cache_control.encode()))
    result.extend((name, value) for name, value in STANDARD_HEADERS if name not in names)
    return result


def _runtime_health(
    environment: Mapping[str, str] = os.environ,
    *,
    gil_enabled: Callable[[], bool] = sys._is_gil_enabled,
) -> bytes:
    """Describe the active GIL state without turning a degraded runtime into an outage."""
    enabled = gil_enabled()
    if environment.get("PYTHON_GIL") == "0" and enabled:
        return b'{"status":"degraded","reason":"python_gil_enabled","python_gil":"enabled"}\n'
    state = b"enabled" if enabled else b"disabled"
    return b'{"status":"ok","python_gil":"' + state + b'"}\n'


application = create_application()
