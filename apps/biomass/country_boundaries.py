"""Load a lightweight Natural Earth country-boundary overlay."""

from __future__ import annotations

import json
from functools import cache
from typing import Any
from urllib.request import Request, urlopen

NATURAL_EARTH_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "9380cca83db5f9aef52d5e762765100745f84b27/geojson/"
    "ne_110m_admin_0_countries.geojson"
)


def _extract_boundaries(collection: dict[str, Any]) -> dict[str, list[list[float]]]:
    """Convert Polygon and MultiPolygon rings to Bokeh ``multi_line`` data."""
    xs: list[list[float]] = []
    ys: list[list[float]] = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        match geometry.get("type"):
            case "Polygon":
                polygons = [coordinates]
            case "MultiPolygon":
                polygons = coordinates
            case _:
                continue
        for polygon in polygons:
            for ring in polygon:
                if len(ring) < 2:
                    continue
                xs.append([float(point[0]) for point in ring])
                ys.append([float(point[1]) for point in ring])
    return {"xs": xs, "ys": ys}


@cache
def load_country_boundaries() -> dict[str, list[list[float]]]:
    """Fetch and cache Natural Earth 1:110m boundaries for this server process."""
    request = Request(NATURAL_EARTH_URL, headers={"User-Agent": "demo.bokeh.org"})
    with urlopen(request, timeout=8) as response:
        collection = json.load(response)
    return _extract_boundaries(collection)
