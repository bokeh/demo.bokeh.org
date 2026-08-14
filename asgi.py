"""Expose the demo catalog as a Bokeh ASGI application."""

from __future__ import annotations

import logging
import mimetypes
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs

from bokeh.server.asgi import BokehASGI

from catalog import load_applications
from presentation import ROOT, render_index

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


class DemoApplication:
    def __init__(self, bokeh: BokehASGI) -> None:
        self._bokeh = bokeh
        self._index = render_index()
        self._legacy_index = render_index(show_legacy_notice=True)
        self._not_found = (ASSET_ROOT / "404.html").read_bytes()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        path = scope.get("path", "/")

        if scope_type == "lifespan":
            await self._bokeh(scope, receive, send)
        elif scope_type == "http" and path.rstrip("/") in LEGACY_DEMO_ROUTES:
            await self._redirect(scope, send, "/?legacy-demo=1#demos")
        elif scope_type == "http" and path in ("/", "/index.html"):
            query = parse_qs(scope.get("query_string", b"").decode())
            index = self._legacy_index if "legacy-demo" in query else self._index
            await self._response(scope, send, index, "text/html; charset=utf-8")
        elif scope_type == "http" and path == "/healthz":
            await self._response(
                scope,
                send,
                b'{"status":"ok"}\n',
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
                    "headers": [(b"allow", b"GET, HEAD"), (b"content-length", b"0")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        headers = [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", cache_control.encode()),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"SAMEORIGIN"),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})

    @staticmethod
    async def _redirect(scope: Scope, send: Send, location: str) -> None:
        method = scope.get("method", "GET").upper()
        if method not in ("GET", "HEAD"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 405,
                    "headers": [(b"allow", b"GET, HEAD"), (b"content-length", b"0")],
                }
            )
        else:
            await send(
                {
                    "type": "http.response.start",
                    "status": 302,
                    "headers": [
                        (b"location", location.encode()),
                        (b"content-length", b"0"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
        await send({"type": "http.response.body", "body": b""})


def create_application() -> DemoApplication:
    origins = [
        origin.strip()
        for origin in os.environ.get("BOKEH_ALLOW_WS_ORIGIN", "").split(",")
        if origin.strip()
    ]
    bokeh = BokehASGI(load_applications(), redirect_root=False, extra_websocket_origins=origins)
    return DemoApplication(bokeh)


application = create_application()
