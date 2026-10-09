"""Offline helpers for the flaring sources checked in Phase S: annual flare-site files and
night-time FIRMS detections near plants. No network; tested in tests/test_spike.py.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.geo.projection import local_aeqd
from app.settings import REPO_ROOT

FLARE_DIR = REPO_ROOT / "data" / "registry" / "raw" / "flares"
NIGHTFIRE_DIR = REPO_ROOT / "data" / "raw" / "nightfire"
LAT_COLUMN = re.compile(r"^lat", re.I)
LON_COLUMN = re.compile(r"^(lon|lng)", re.I)
KML_COORDINATES = re.compile(r"<coordinates>\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)")


def read_flare_sites(path: Path) -> pd.DataFrame:
    """Flare sites of one annual file with `lon` and `lat` columns added.

    Reads .csv, .xlsx (every sheet that has latitude and longitude columns) and .kml (placemark points).
    The latitude and longitude columns are found by name, so the file's own layout is kept.
    """
    suffix = path.suffix.lower()
    if suffix == ".kml":
        pairs = KML_COORDINATES.findall(path.read_text(encoding="utf-8", errors="replace"))
        return pd.DataFrame({"lon": [float(lon) for lon, _ in pairs], "lat": [float(lat) for _, lat in pairs]})
    if suffix == ".csv":
        sheets = {"csv": pd.read_csv(path)}
    elif suffix == ".xlsx":
        sheets = pd.read_excel(path, sheet_name=None)
    else:
        raise ValueError(f"{path.name}: unsupported file type (use .xlsx, .csv or .kml)")

    frames = []
    for name, sheet in sheets.items():
        lat = next((c for c in sheet.columns if LAT_COLUMN.match(str(c))), None)
        lon = next((c for c in sheet.columns if LON_COLUMN.match(str(c))), None)
        if lat is None or lon is None:
            continue
        sheet = sheet.assign(
            lon=pd.to_numeric(sheet[lon], errors="coerce"), lat=pd.to_numeric(sheet[lat], errors="coerce")
        )
        frames.append(sheet.dropna(subset=["lon", "lat"]).assign(sheet=name))
    if not frames:
        raise ValueError(f"{path.name}: no sheet has both a latitude and a longitude column")
    return pd.concat(frames, ignore_index=True)


def in_bbox(sites: pd.DataFrame, bbox: Sequence[float]) -> pd.DataFrame:
    west, south, east, north = bbox
    return sites[sites["lon"].between(west, east) & sites["lat"].between(south, north)]


def flare_sites_summary(directory: Path, bbox: Sequence[float]) -> dict[str, Any]:
    """Per annual flare file: sites in the file and inside the region. A missing folder is not an error."""
    files = sorted(p for p in directory.glob("*") if p.is_file() and p.name != ".gitkeep") if directory.exists() else []
    where = directory.relative_to(REPO_ROOT).as_posix()
    summary: dict[str, Any] = {"directory": where, "files": [], "sites_in_region": 0}
    for path in files:
        entry: dict[str, Any] = {"file": path.name}
        try:
            sites = read_flare_sites(path)
            entry |= {"sites": len(sites), "sites_in_region": len(in_bbox(sites, bbox))}
            summary["sites_in_region"] += entry["sites_in_region"]
        except Exception as exc:
            entry["error"] = str(exc)[:200]
        summary["files"].append(entry)
    return summary


def night_counts_near(
    rows: pd.DataFrame, plants: Sequence[dict[str, Any]], radius_km: float, window_days: int, min_frp_mw: float
) -> list[dict[str, Any]]:
    """Night-time FIRMS detections within `radius_km` of each plant.

    Per plant: detections, distinct nights, the largest number of distinct nights inside any
    `window_days` window (what the persistence rule looks at), the same for detections with
    FRP >= `min_frp_mw`, and the median FRP. Raises when FIRMS did not deliver the columns needed.
    """
    columns = {c.lower(): c for c in rows.columns}
    missing = [c for c in ("latitude", "longitude", "acq_date", "daynight") if c not in columns]
    if missing:
        raise ValueError(f"FIRMS rows lack columns {missing}; columns are {list(rows.columns)}")
    night = rows[rows[columns["daynight"]].astype(str).str.upper().str.startswith("N")]
    lons = night[columns["longitude"]].to_numpy(dtype=float)
    lats = night[columns["latitude"]].to_numpy(dtype=float)
    frp_column = columns.get("frp")

    out = []
    for plant in plants:
        to_local, _ = local_aeqd(plant["lon"], plant["lat"])
        x, y = to_local.transform(lons, lats) if len(night) else (np.array([]), np.array([]))
        near = night[np.hypot(x, y) <= radius_km * 1000]
        entry: dict[str, Any] = {
            "plant": plant["name"],
            "detections": len(near),
            "nights": int(near[columns["acq_date"]].nunique()),
            "max_nights_in_window": max_dates_in_window(near[columns["acq_date"]], window_days),
        }
        if frp_column:
            strong = near[pd.to_numeric(near[frp_column], errors="coerce") >= min_frp_mw]
            entry["max_nights_in_window_min_frp"] = max_dates_in_window(strong[columns["acq_date"]], window_days)
            entry["median_frp_mw"] = (
                float(pd.to_numeric(near[frp_column], errors="coerce").median()) if len(near) else None
            )
        out.append(entry)
    return out


def max_dates_in_window(dates: pd.Series, window_days: int) -> int:
    """Largest number of distinct dates that fall inside any window of `window_days` days."""
    days = np.sort(pd.to_datetime(dates.drop_duplicates()).to_numpy())
    if len(days) == 0:
        return 0
    window = np.timedelta64(window_days, "D")
    return int(max(np.searchsorted(days, day + window, side="left") - i for i, day in enumerate(days)))
