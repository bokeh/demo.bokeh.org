"""Load a lightweight Natural Earth country-boundary overlay."""

from __future__ import annotations

import json
from functools import cache
from itertools import pairwise
from typing import Any
from urllib.request import Request, urlopen

import numpy as np

from .shading import web_mercator

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


def project_boundaries(boundaries: dict[str, list[list[float]]]) -> dict[str, list[list[float]]]:
    """Project WGS84 rings to Web Mercator, splitting antimeridian crossings."""
    xs: list[list[float]] = []
    ys: list[list[float]] = []
    for longitudes, latitudes in zip(boundaries["xs"], boundaries["ys"], strict=True):
        starts = [0]
        starts.extend(
            index
            for index in range(1, len(longitudes))
            if abs(longitudes[index] - longitudes[index - 1]) > 180
        )
        starts.append(len(longitudes))
        for start, end in pairwise(starts):
            if end - start < 2:
                continue
            x, y = web_mercator(np.asarray(longitudes[start:end]), np.asarray(latitudes[start:end]))
            xs.append(x.tolist())
            ys.append(y.tolist())
    return {"xs": xs, "ys": ys}


@cache
def load_country_boundaries() -> dict[str, list[list[float]]]:
    """Fetch and cache Natural Earth 1:110m boundaries for this server process."""
    request = Request(NATURAL_EARTH_URL, headers={"User-Agent": "demo.bokeh.org"})
    with urlopen(request, timeout=8) as response:
        collection = json.load(response)
    return _extract_boundaries(collection)
