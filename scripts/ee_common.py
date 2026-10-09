"""Live helpers shared by the Phase S scripts (spike_ee.py, make_fixtures.py).

Everything here talks to real services and needs the Phase 0 credentials in .env.
Nothing in the app or the test suite imports this module.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any, TypeVar

import httpx
import numpy as np
import pandas as pd
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.geo.projection import local_aeqd
from app.settings import REPO_ROOT

T = TypeVar("T")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "land-emissions-monitor/0.1 (research prototype)"  # Overpass rejects requests without one
FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov"
RETRYABLE = re.compile(r"429|500|502|503|504|quota|too many|rate limit|deadline|timed? ?out|unavailable", re.I)

# Overpass selectors per slice kind (plan Phase 2, clients/osm.py).
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


class LiveEnv(BaseSettings):
    """Credentials for the live scripts, read from .env (see .env.example)."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    ee_project: str = ""
    ee_service_account: str = ""
    ee_key_file: str = "secrets/ee-key.json"
    firms_map_key: str = ""
    cds_url: str = ""
    cds_key: str = ""


def init_ee(env: LiveEnv) -> None:
    import ee

    key_file = REPO_ROOT / env.ee_key_file
    if not (env.ee_project and env.ee_service_account and key_file.exists()):
        raise SystemExit(
            "Earth Engine is not configured: set EE_PROJECT and EE_SERVICE_ACCOUNT in .env "
            f"and place the service-account key at {key_file} (plan Phase 0)."
        )
    ee.Initialize(ee.ServiceAccountCredentials(env.ee_service_account, str(key_file)), project=env.ee_project)


def retry(fn: Callable[[], T], tries: int = 5, base_seconds: float = 2.0) -> T:
    """Call `fn`, retrying quota and server errors with exponential backoff and jitter."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception as exc:
            if attempt == tries - 1 or not RETRYABLE.search(str(exc)):
                raise
            time.sleep(base_seconds * 2**attempt + random.uniform(0, 1))
    raise AssertionError("unreachable")


def last_days(end: date, n: int) -> list[date]:
    return [end - timedelta(days=i) for i in range(n - 1, -1, -1)]


def window_bbox(lon: float, lat: float, half_km: float) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a square window of half-width `half_km` around a point."""
    _, to_wgs84 = local_aeqd(lon, lat)
    west, _ = to_wgs84.transform(-half_km * 1000, 0)
    east, _ = to_wgs84.transform(half_km * 1000, 0)
    _, south = to_wgs84.transform(0, -half_km * 1000)
    _, north = to_wgs84.transform(0, half_km * 1000)
    return west, south, east, north


def grid_spec(bbox: Sequence[float], step_deg: float) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """computePixels grid for a bbox, plus the cell-centre latitudes (ascending) and longitudes."""
    west, south, east, north = bbox
    width = max(1, round((east - west) / step_deg))
    height = max(1, round((north - south) / step_deg))
    spec = {
        "dimensions": {"width": width, "height": height},
        "affineTransform": {
            "scaleX": step_deg,
            "shearX": 0,
            "translateX": west,
            "shearY": 0,
            "scaleY": -step_deg,
            "translateY": north,
        },
        "crsCode": "EPSG:4326",
    }
    lats = north - (np.arange(height) + 0.5) * step_deg
    lons = west + (np.arange(width) + 0.5) * step_deg
    return spec, lats[::-1].copy(), lons


def fetch_daily_grids(
    collection_id: str,
    bands: Sequence[str],
    bbox: Sequence[float],
    days: Sequence[date],
    step_deg: float,
    chunk_days: int = 20,
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Daily mean grids of `bands` as {band: (time, lat, lon) float32}, NaN where the product is masked.

    A day is a UTC calendar day. Days are stacked into one image per chunk, so the number of
    requests is len(days) / chunk_days, not len(days).
    """
    import ee

    bands = list(bands)
    n = len(bands)
    spec, lats, lons = grid_spec(bbox, step_deg)
    region = ee.Geometry.Rectangle(list(bbox), proj="EPSG:4326", geodesic=False)
    collection = ee.ImageCollection(collection_id).filterBounds(region).select(bands)
    # A fully masked image, so a day without data still yields the bands.
    template = ee.ImageCollection([ee.Image.constant([0] * n).rename(bands).toFloat().updateMask(0)])
    out = {b: np.full((len(days), len(lats), len(lons)), np.nan, dtype="float32") for b in bands}

    for first in range(0, len(days), chunk_days):
        part = days[first : first + chunk_days]
        layers = []
        for day in part:
            start = ee.Date(day.isoformat())
            mean = collection.filterDate(start, start.advance(1, "day")).merge(template).mean()
            layers += [mean.unmask(0).toFloat(), mean.mask().toFloat()]
        request = {"expression": ee.Image.cat(layers), "fileFormat": "NUMPY_NDARRAY", "grid": spec}
        pixels = retry(lambda request=request: ee.data.computePixels(request))
        planes = [pixels[name] for name in pixels.dtype.names]
        if len(planes) != len(part) * 2 * n:
            raise RuntimeError(f"{collection_id}: expected {len(part) * 2 * n} bands back, got {len(planes)}")
        for j in range(len(part)):
            for k, band in enumerate(bands):
                values = planes[j * 2 * n + k]
                mask = planes[j * 2 * n + n + k]
                out[band][first + j] = np.where(mask > 0, values, np.nan)[::-1]  # rows arrive north first
    return out, lats, lons


def point_timeseries(
    collection_id: str,
    bands: Sequence[str],
    lon: float,
    lat: float,
    start: date,
    end: date,
    scale_m: float,
    hour_utc: int | None = None,
    equals: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Values of `bands` at one point for every image between start and end (inclusive), one request.

    `hour_utc` keeps the images of that UTC hour; `equals` keeps images whose properties match.
    """
    import ee

    collection = (
        ee.ImageCollection(collection_id)
        .select(list(bands))
        .filterDate(start.isoformat(), (end + timedelta(days=1)).isoformat())
    )
    if hour_utc is not None:
        collection = collection.filter(ee.Filter.calendarRange(hour_utc, hour_utc, "hour"))
    for name, value in (equals or {}).items():
        collection = collection.filter(ee.Filter.eq(name, value))
    try:
        rows = retry(lambda: collection.getRegion(ee.Geometry.Point([lon, lat]), scale_m).getInfo())
    except ee.EEException as exc:
        if "No bands in collection" not in str(exc):  # that message means no image passed the filters
            raise
        return pd.DataFrame(columns=["time", *bands])
    frame = pd.DataFrame(rows[1:], columns=rows[0])
    frame["time"] = pd.to_datetime(frame["time"], unit="ms", utc=True)
    return frame.dropna(subset=list(bands)).sort_values("time").reset_index(drop=True)


def overpass(bbox: Sequence[float], kinds: Sequence[str], timeout_s: int = 180) -> dict[str, list[dict[str, Any]]]:
    """OSM elements per kind inside a bbox, with tags and geometry."""
    west, south, east, north = bbox
    area = f"({south},{west},{north},{east})"
    out: dict[str, list[dict[str, Any]]] = {}
    for kind in kinds:
        query = f"[out:json][timeout:{timeout_s}];{OSM_SELECTORS[kind]}{area};out tags geom;"
        response = retry(lambda query=query: _post_overpass(query, timeout_s))
        out[kind] = response["elements"]
        time.sleep(2)  # be polite to the public Overpass server
    return out


def _post_overpass(query: str, timeout_s: int) -> dict[str, Any]:
    response = httpx.post(
        OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=timeout_s + 30
    )
    if response.status_code != 200:
        raise RuntimeError(f"Overpass HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


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


def element_centre(element: dict[str, Any]) -> tuple[float, float] | None:
    geometry = element_geometry(element)
    if geometry is None:
        return None
    if geometry["type"] == "Point":
        return tuple(geometry["coordinates"])
    ring = np.array(geometry["coordinates"][0])
    return float(ring[:, 0].mean()), float(ring[:, 1].mean())


def discover_plants(bbox: Sequence[float], limit: int = 5) -> list[dict[str, Any]]:
    """The largest OSM power plants in the bbox (by the `plant:output:electricity` tag), biggest first.

    Phase S runs before the registry exists, so OSM stands in for it here.
    """
    plants = []
    for element in overpass(bbox, ["power_plant"])["power_plant"]:
        centre = element_centre(element)
        if centre is None:
            continue
        tags = element.get("tags", {})
        match = re.search(r"([\d.]+)\s*(MW|GW)", tags.get("plant:output:electricity", ""), re.I)
        capacity = float(match.group(1)) * (1000 if match and match.group(2).upper() == "GW" else 1) if match else None
        plants.append(
            {
                "name": tags.get("name:en") or tags.get("name") or f"osm {element['type']} {element['id']}",
                "lon": round(centre[0], 5),
                "lat": round(centre[1], 5),
                "capacity_mw": capacity,
                "source": tags.get("plant:source"),
            }
        )
    plants.sort(key=lambda p: p["capacity_mw"] or 0, reverse=True)
    return plants[:limit]


def firms_get(path: str, map_key: str, timeout_s: int = 120) -> httpx.Response:
    """GET a FIRMS URL. `path` contains the literal text {key}; the key never appears in errors."""
    try:
        return httpx.get(f"{FIRMS_BASE}{path.format(key=map_key)}", timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise RuntimeError(str(exc).replace(map_key, "***")) from None
