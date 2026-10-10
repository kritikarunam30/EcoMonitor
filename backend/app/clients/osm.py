"""OpenStreetMap objects through Overpass: industrial areas, power plants, chimneys, and the
schools, hospitals, clinics, villages and towns used for impact (plan Phase 2, task 3)."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import geopandas as gpd
import httpx
import shapely
from shapely.geometry import shape

from app.clients.base import Bbox, cached, data_mode, fixture_paths, retry
from app.settings import get_settings

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "land-emissions-monitor/0.1 (research prototype)"  # Overpass rejects requests without one
PAUSE_SECONDS = 2  # between queries; be polite to the public Overpass server
OSM_SELECTORS = {
    "power_plant": 'nwr["power"="plant"]',
    "industrial": 'nwr["landuse"="industrial"]',
    "chimney": 'node["man_made"="chimney"]',
    "school": 'nwr["amenity"="school"]',
    "hospital": 'nwr["amenity"="hospital"]',
    "clinic": 'nwr["amenity"="clinic"]',
    "village": 'node["place"="village"]',
    "town": 'node["place"="town"]',
}
COLUMNS = ["kind", "osm_type", "osm_id", "name", "tags", "geometry"]
ID_KEYS = ("kind", "osm_type", "osm_id")


def _post_overpass(query: str, timeout_s: int) -> dict[str, Any]:
    response = httpx.post(
        OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=timeout_s + 30
    )
    if response.status_code != 200:
        raise RuntimeError(f"Overpass HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


def overpass(bbox: Bbox, kinds: Sequence[str], timeout_s: int = 180) -> dict[str, list[dict[str, Any]]]:
    """OSM elements per kind inside a bbox, with tags and geometry. One query per kind."""
    west, south, east, north = bbox
    area = f"({south},{west},{north},{east})"
    out: dict[str, list[dict[str, Any]]] = {}
    for kind in kinds:
        query = f"[out:json][timeout:{timeout_s}];{OSM_SELECTORS[kind]}{area};out tags geom;"
        response = retry(lambda query=query: _post_overpass(query, timeout_s))
        out[kind] = response["elements"]
        time.sleep(PAUSE_SECONDS)
    return out


def element_geometry(element: dict[str, Any]) -> dict[str, Any] | None:
    """GeoJSON geometry of an Overpass element: a point for nodes, a polygon for closed ways,
    and the centre of the bounds for anything else."""
    if element["type"] == "node":
        return {"type": "Point", "coordinates": [element["lon"], element["lat"]]}
    ring = [[p["lon"], p["lat"]] for p in element.get("geometry", []) if p]
    if element["type"] == "way" and len(ring) >= 4 and ring[0] == ring[-1]:
        return {"type": "Polygon", "coordinates": [ring]}
    bounds = element.get("bounds")
    if bounds:
        lon = (bounds["minlon"] + bounds["maxlon"]) / 2
        lat = (bounds["minlat"] + bounds["maxlat"]) / 2
        return {"type": "Point", "coordinates": [lon, lat]}
    return None


def elements_to_features(kind: str, elements: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """GeoJSON features in the layout of the recorded slice: properties kind, osm_type, osm_id and the tags."""
    features = []
    for element in elements:
        geometry = element_geometry(element)
        if geometry is None:
            continue
        properties = {"kind": kind, "osm_type": element["type"], "osm_id": element["id"], **element.get("tags", {})}
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    return features


def get_osm(bbox: Bbox, kinds: Sequence[str] | None = None) -> gpd.GeoDataFrame:
    """OSM objects that touch a bbox: kind, osm_type, osm_id, name, tags (dict) and geometry (WGS84).

    `kinds` are keys of OSM_SELECTORS; the default is all of them.
    """
    kinds = list(kinds) if kinds is not None else list(OSM_SELECTORS)
    unknown = [k for k in kinds if k not in OSM_SELECTORS]
    if unknown:
        raise ValueError(f"unknown OSM kinds {unknown}; known: {list(OSM_SELECTORS)}")

    if data_mode() == "fixture":
        features = [
            f
            for path in fixture_paths("osm.geojson")
            for f in json.loads(path.read_text(encoding="utf-8"))["features"]
            if f["properties"]["kind"] in kinds
        ]
    else:
        timeout_s = get_settings().config.data["overpass_timeout_s"]
        features = []
        for kind in kinds:
            features += cached(
                "osm",
                [kind, list(bbox)],
                "json",
                lambda kind=kind: elements_to_features(kind, overpass(bbox, [kind], timeout_s)[kind]),
            )

    rows = []
    for feature in features:
        p = feature["properties"]
        tags = {k: v for k, v in p.items() if k not in ID_KEYS}
        name = tags.get("name:en") or tags.get("name")
        rows.append({**{k: p[k] for k in ID_KEYS}, "name": name, "tags": tags, "geometry": shape(feature["geometry"])})
    frame = gpd.GeoDataFrame(rows, columns=COLUMNS, geometry="geometry", crs="EPSG:4326")
    return frame[frame.intersects(shapely.box(*bbox))].reset_index(drop=True)
