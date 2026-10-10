"""Flaring sources behind one interface, chosen by `flaring.source` (plan Phase 2, task 3):

    annual_sites      flare sites of the annual GFMR / EOG files in data/registry/raw/flares/
    firms_persistent  night-time FIRMS 375 m detections (the default; needs no licence)
    nightfire         nightly Nightfire files, when a person placed some in data/raw/nightfire/

Nightfire is optional. When it is unavailable the result falls back to `firms_persistent` and says so.
The persistence rule (nights per window, minimum FRP, distance to a facility) is the detector's job.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from app.clients import firms, nightfire
from app.clients.base import Bbox, cache_path, data_mode, fixture_paths, read_file, write_file
from app.settings import get_settings

SOURCES = ("annual_sites", "firms_persistent", "nightfire")
OBS_COLUMNS = ["lon", "lat", "observed_at", "frp_mw", "temp_k", "source"]
SITE_COLUMNS = ["lon", "lat", "volume_bcm", "year", "source_file"]
LAT_COLUMN = re.compile(r"^lat", re.I)
LON_COLUMN = re.compile(r"^(lon|lng)", re.I)
VOLUME_COLUMN = re.compile(r"^bcm$", re.I)
YEAR_COLUMN = re.compile(r"^year$", re.I)
KML_COORDINATES = re.compile(r"<coordinates>\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)")


@dataclass
class FlareObservations:
    """What a flaring source delivered. `source` differs from `requested` after a fallback."""

    requested: str
    source: str
    rows: pd.DataFrame  # lon, lat, observed_at (UTC; NaT for annual sites), frp_mw, temp_k, source
    note: str = ""


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


def _site_table(sites: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """The columns the app uses from an annual file: position, annual volume and year when present."""
    volume = next((c for c in sites.columns if VOLUME_COLUMN.match(str(c))), None)
    year = next((c for c in sites.columns if YEAR_COLUMN.match(str(c))), None)
    return pd.DataFrame(
        {
            "lon": sites["lon"].astype(float),
            "lat": sites["lat"].astype(float),
            "volume_bcm": pd.to_numeric(sites[volume], errors="coerce") if volume else float("nan"),
            "year": pd.to_numeric(sites[year], errors="coerce") if year else float("nan"),
            "source_file": sites.get("source_file", source_file),
        }
    )[SITE_COLUMNS]


def get_annual_sites(bbox: Bbox) -> gpd.GeoDataFrame:
    """Known flare sites inside a bbox: lon, lat, volume_bcm, year, source_file and point geometry.

    These are local files, not a network source. Parsing the large Excel file is slow, so each file
    is parsed once and kept as parquet in data/cache/flares/.
    """
    settings = get_settings()
    tables = []
    if data_mode() == "fixture":
        tables = [_site_table(pd.read_csv(path), path.name) for path in fixture_paths("flare_sites.csv")]
    else:
        folder = settings.resolve(settings.flare_dir)
        for path in sorted(p for p in folder.glob("*") if p.suffix.lower() in (".xlsx", ".csv", ".kml")):
            stat = path.stat()
            parsed = cache_path("flares", [path.name, stat.st_size, int(stat.st_mtime)], "parquet")
            if not parsed.exists():
                write_file(parsed, _site_table(read_flare_sites(path), path.name))
            tables.append(read_file(parsed))
    tables = [t for t in tables if not t.empty]
    sites = in_bbox(pd.concat(tables, ignore_index=True), bbox) if tables else pd.DataFrame(columns=SITE_COLUMNS)
    sites = sites.reset_index(drop=True).astype({"lon": "float64", "lat": "float64"})
    return gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites["lon"], sites["lat"]), crs="EPSG:4326")


def _from_firms(bbox: Bbox, start: date, end: date) -> pd.DataFrame:
    night = firms.night_only(firms.get_firms(bbox, start, end))
    return pd.DataFrame(
        {
            "lon": night["longitude"].astype(float),
            "lat": night["latitude"].astype(float),
            "observed_at": night["acq_datetime"],
            "frp_mw": pd.to_numeric(night["frp"], errors="coerce"),
            "temp_k": float("nan"),
            "source": night["source"],
        }
    ).reset_index(drop=True)[OBS_COLUMNS]


def get_flare_observations(bbox: Bbox, start: date, end: date, source: str | None = None) -> FlareObservations:
    """Flare candidates in a bbox and UTC day range from `source` (default: `flaring.source`)."""
    requested = source or get_settings().config.flaring["source"]
    if requested not in SOURCES:
        raise ValueError(f"unknown flaring source '{requested}'; use one of {SOURCES}")

    if requested == "annual_sites":
        sites = get_annual_sites(bbox)
        rows = pd.DataFrame(
            {
                "lon": sites["lon"],
                "lat": sites["lat"],
                "observed_at": pd.Series(pd.NaT, index=sites.index, dtype="datetime64[ns, UTC]"),
                "frp_mw": float("nan"),
                "temp_k": float("nan"),
                "source": "annual_sites",
            }
        )[OBS_COLUMNS]
        return FlareObservations(requested, "annual_sites", rows, f"{len(rows)} annual flare sites; no dates")

    note = ""
    if requested == "nightfire":
        found, note = nightfire.get_nightfire(bbox, start, end)
        if found is not None:
            rows = found.assign(frp_mw=float("nan"), source="nightfire")[OBS_COLUMNS]
            return FlareObservations(requested, "nightfire", rows, note)
        note += "; fell back to firms_persistent"
    return FlareObservations(requested, "firms_persistent", _from_firms(bbox, start, end), note)
