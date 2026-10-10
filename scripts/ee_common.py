"""Live helpers shared by the Phase S scripts (spike_ee.py, make_fixtures.py).

Everything here talks to real services and needs the Phase 0 credentials in .env.
The app does not import this module; the helpers both sides need live in app/clients/.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from pydantic_settings import BaseSettings, SettingsConfigDict

# Shared with the app since Phase 2: the clients own these, the scripts use the same code.
from app.clients.base import retry
from app.clients.ee_client import daily_grids as fetch_daily_grids
from app.clients.ee_client import grid_spec
from app.clients.firms import firms_get
from app.clients.osm import OSM_SELECTORS, element_geometry, overpass
from app.geo.projection import local_aeqd
from app.settings import REPO_ROOT

__all__ = ["OSM_SELECTORS", "element_geometry", "fetch_daily_grids", "firms_get", "grid_spec", "overpass", "retry"]


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
