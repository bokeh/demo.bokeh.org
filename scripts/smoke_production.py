#!/usr/bin/env python3
"""Exercise the production catalog and a cookie-affined Bokeh WebSocket."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import socket
import ssl
import struct
import time
from http.client import HTTPResponse
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

TOKEN_PATTERN = re.compile(rb'"token":"([^"]+)"')
LOGGER = logging.getLogger(__name__)


def fetch(url: str) -> tuple[HTTPResponse, bytes]:
    response = urlopen(Request(url, headers={"User-Agent": "bokeh-production-smoke/1"}), timeout=15)
    return response, response.read()


def cookies(response: HTTPResponse) -> str:
    return "; ".join(value.split(";", 1)[0] for value in response.headers.get_all("Set-Cookie", []))


def session_token(page: bytes) -> tuple[str, str]:
    match = TOKEN_PATTERN.search(page)
    if match is None:
        raise RuntimeError("application page did not contain a Bokeh session token")
    token = match.group(1).decode()
    padding = "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(token + padding))
    return token, payload["session_id"]


def websocket_handshake(
    base_url: str, route: str, token: str, session_id: str, cookie: str
) -> None:
    target = urlsplit(base_url)
    host = target.hostname
    if host is None:
        raise ValueError(f"base URL has no host: {base_url}")
    port = target.port or 443
    key = base64.b64encode(os.urandom(16)).decode()
    query = urlencode({"bokeh-protocol-version": "1.0", "bokeh-session-id": session_id})
    request_target = f"{route.rstrip('/')}/ws?{query}"
    headers = [
        f"GET {request_target} HTTP/1.1",
        f"Host: {target.netloc}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Origin: {target.scheme}://{target.netloc}",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        f"Sec-WebSocket-Protocol: bokeh, {token}",
    ]
    if cookie:
        headers.append(f"Cookie: {cookie}")

    with (
        socket.create_connection((host, port), timeout=15) as raw,
        ssl.create_default_context().wrap_socket(raw, server_hostname=host) as connection,
    ):
        connection.sendall(("\r\n".join((*headers, "", ""))).encode())
        response = b""
        while b"\r\n\r\n" not in response and len(response) < 65_536:
            block = connection.recv(4096)
            if not block:
                break
            response += block

        head = response.partition(b"\r\n\r\n")[0]
        lines = head.split(b"\r\n")
        if not lines or b" 101 " not in lines[0]:
            raise RuntimeError(f"WebSocket handshake failed: {lines[0].decode(errors='replace')}")
        response_headers = {
            name.strip().lower(): value.strip()
            for line in lines[1:]
            if b":" in line
            for name, value in [line.split(b":", 1)]
        }
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(), usedforsecurity=False
            ).digest()
        )
        if response_headers.get(b"sec-websocket-accept") != expected:
            raise RuntimeError("WebSocket handshake returned an invalid accept key")

        payload = struct.pack("!H", 1000)
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        connection.sendall(b"\x88\x82" + mask + masked)


def check(base_url: str) -> None:
    _health_response, health_body = fetch(urljoin(base_url, "/healthz"))
    if json.loads(health_body)["status"] not in {"ok", "degraded"}:
        raise RuntimeError("health endpoint returned an unknown status")

    _index_response, index = fetch(urljoin(base_url, "/"))
    if b"Bokeh in action" not in index:
        raise RuntimeError("catalog marker was not present")
    if b"/biomass-change" in index:
        raise RuntimeError("unlisted biomass application appeared in the catalog")

    _sitemap_response, sitemap = fetch(urljoin(base_url, "/sitemap.xml"))
    ElementTree.fromstring(sitemap)
    if b"/biomass-change" in sitemap:
        raise RuntimeError("unlisted biomass application appeared in the sitemap")

    route = "/airport-access"
    app_response, app_page = fetch(urljoin(base_url, route))
    if b"Regional airport access" not in app_page:
        raise RuntimeError("representative application marker was not present")
    token, session_id = session_token(app_page)
    websocket_handshake(base_url, route, token, session_id, cookies(app_response))

    biomass_route = "/biomass-change"
    biomass_response, biomass_page = fetch(urljoin(base_url, biomass_route))
    if b"Global biomass change explorer" not in biomass_page:
        raise RuntimeError("biomass application marker was not present")
    token, session_id = session_token(biomass_page)
    websocket_handshake(base_url, biomass_route, token, session_id, cookies(biomass_response))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://demo.bokeh.org")
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--retry-delay", type=float, default=5)
    args = parser.parse_args()

    for attempt in range(1, args.attempts + 1):
        try:
            check(args.base_url)
        except Exception as error:
            if attempt == args.attempts:
                raise
            LOGGER.warning("Production smoke attempt %d failed: %s; retrying", attempt, error)
            time.sleep(args.retry_delay)
        else:
            LOGGER.info("Production catalog, sitemap, application, and WebSocket are healthy")
            return


if __name__ == "__main__":
    main()
