"""Offline helpers for the flaring sources checked in Phase S: annual flare-site files and
night-time FIRMS detections near plants. No network; tested in tests/test_spike.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.clients.flares import in_bbox, read_flare_sites  # owned by the app client since Phase 2
from app.geo.projection import local_aeqd
from app.settings import REPO_ROOT

FLARE_DIR = REPO_ROOT / "data" / "registry" / "raw" / "flares"
NIGHTFIRE_DIR = REPO_ROOT / "data" / "raw" / "nightfire"

__all__ = ["in_bbox", "read_flare_sites"]


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
