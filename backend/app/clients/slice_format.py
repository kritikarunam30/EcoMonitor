"""Format of a recorded fixture slice (tests/fixtures/real_<unit>/) and its integrity check.

`scripts/make_fixtures.py` writes a slice with these helpers; fixture-mode clients read it.
Grids follow plan §0.6: dims (time, lat, lon), regular WGS84 coordinates, NaN for missing data.

    manifest.json   what was recorded, when, and from which sources
    no2.nc          no2, valid, cloud_fraction (when the product has it)
    so2.nc          so2, valid
    aer_ai.nc       aer_ai, valid                                   (optional)
    wind.csv        time, lon, lat, u, v, speed, dir_from_deg, source, level
    firms.csv       FIRMS rows as delivered                         (optional)
    flare_sites.csv annual flare sites inside the region            (optional)
    nightfire.csv   Nightfire rows, only when recorded on purpose   (optional)
    osm.geojson     FeatureCollection, properties.kind per feature  (optional)
    s2_chips.nc     Sentinel-2 chips, dims (time, band, y, x)       (optional)
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

OVERPASS_HOUR_UTC = 8  # nominal TROPOMI overpass for India; a daily grid is stamped date + 08:00Z
MAX_SLICE_BYTES = 50 * 1024 * 1024

GRID_UNITS = {"no2": "mol/m^2", "so2": "mol/m^2", "ch4": "ppb", "cloud_fraction": "1", "aer_ai": "1"}
GRID_FILES = {"no2.nc": "no2", "so2.nc": "so2", "aer_ai.nc": "aer_ai"}
REQUIRED_GRID_FILES = ("no2.nc", "so2.nc")
GRID_ATTRS = ("source", "ee_id", "fetched_at", "mode")
MANIFEST_KEYS = ("unit", "created_at", "start", "end", "bbox", "sources", "files")
WIND_COLUMNS = ("time", "lon", "lat", "u", "v", "speed", "dir_from_deg", "source", "level")
OSM_KINDS = ("industrial", "power_plant", "chimney", "school", "hospital", "clinic", "village", "town")


def wind_dir_from_deg(u, v):
    """Direction the wind blows from, in degrees clockwise from north (u east, v north)."""
    return (270.0 - np.degrees(np.arctan2(v, u))) % 360.0


def overpass_times(days: Sequence[date]) -> pd.DatetimeIndex:
    """UTC overpass timestamps for calendar days (naive datetime64, UTC by convention)."""
    return pd.DatetimeIndex([datetime(d.year, d.month, d.day, OVERPASS_HOUR_UTC) for d in days])


def make_grid_dataset(
    variables: dict[str, np.ndarray],
    days: Sequence[date],
    lats: np.ndarray,
    lons: np.ndarray,
    *,
    primary: str,
    source: str,
    ee_id: str,
    mode: str,
) -> xr.Dataset:
    """Build a §0.6 grid dataset. `variables` maps names to (time, lat, lon) arrays with NaN for missing.

    `valid` is derived from `primary`: true where that variable has a value.
    """
    data = {name: (("time", "lat", "lon"), np.asarray(arr, dtype="float32")) for name, arr in variables.items()}
    ds = xr.Dataset(data, coords={"time": overpass_times(days), "lat": lats, "lon": lons})
    for name in variables:
        ds[name].attrs["units"] = GRID_UNITS[name]
    ds["valid"] = ds[primary].notnull()
    ds["valid"].attrs["long_name"] = f"{primary} has a value (the product's own QA mask passed)"
    ds["time"].attrs["time_zone"] = "UTC"
    ds.attrs.update(source=source, ee_id=ee_id, fetched_at=datetime.now(UTC).isoformat(), mode=mode)
    return ds


def _check_grid(path: Path, primary: str, bbox: Sequence[float]) -> list[str]:
    problems: list[str] = []
    name = path.name
    with xr.open_dataset(path) as ds:
        ds.load()

    for var in (primary, "valid"):
        if var not in ds:
            return [f"{name}: variable '{var}' is missing"]
    for attr in GRID_ATTRS:
        if not ds.attrs.get(attr):
            problems.append(f"{name}: attribute '{attr}' is missing")

    for var in ds.data_vars:
        if ds[var].dims != ("time", "lat", "lon"):
            problems.append(f"{name}: {var} has dims {ds[var].dims}, expected (time, lat, lon)")
        if var in GRID_UNITS and ds[var].attrs.get("units") != GRID_UNITS[var]:
            problems.append(f"{name}: {var} units are {ds[var].attrs.get('units')!r}, expected {GRID_UNITS[var]!r}")
    if problems:
        return problems

    for axis in ("lat", "lon"):
        steps = np.diff(ds[axis].values)
        if len(steps) == 0 or not np.allclose(steps, steps[0], rtol=1e-4) or steps[0] <= 0:
            problems.append(f"{name}: {axis} is not a regular ascending coordinate")
    west, south, east, north = bbox
    if ds.lon.min() < west - 1 or ds.lon.max() > east + 1 or ds.lat.min() < south - 1 or ds.lat.max() > north + 1:
        problems.append(f"{name}: grid lies outside the manifest bbox {list(bbox)}")

    times = pd.DatetimeIndex(ds.time.values)
    if ds.time.attrs.get("time_zone") != "UTC":
        problems.append(f"{name}: time has no time_zone='UTC' attribute")
    if not times.is_monotonic_increasing or not times.is_unique:
        problems.append(f"{name}: time is not sorted and unique")
    if not ((times.hour == OVERPASS_HOUR_UTC) & (times.minute == 0)).all():
        problems.append(f"{name}: times are not at {OVERPASS_HOUR_UTC:02d}:00 UTC")

    values = ds[primary].values
    valid = ds["valid"].values.astype(bool)
    if not np.array_equal(valid, ~np.isnan(values)):
        problems.append(f"{name}: 'valid' does not match where {primary} is not NaN (missing data must be NaN)")
    if not valid.any():
        problems.append(f"{name}: {primary} has no valid pixel at all")
    elif (values[valid] == 0).mean() > 0.2:
        problems.append(f"{name}: over 20% of valid {primary} pixels are exactly 0; missing data may be stored as 0")
    if "cloud_fraction" in ds:
        cloud = ds["cloud_fraction"].values
        if np.nanmin(cloud, initial=0) < 0 or np.nanmax(cloud, initial=0) > 1:
            problems.append(f"{name}: cloud_fraction is outside 0-1")
    return problems


def _check_wind(path: Path) -> list[str]:
    df = pd.read_csv(path)
    missing = [c for c in WIND_COLUMNS if c not in df.columns]
    if missing:
        return [f"wind.csv: columns missing: {missing}"]
    if df.empty:
        return ["wind.csv: no rows"]
    problems = []
    times = pd.to_datetime(df["time"], errors="coerce", utc=False)
    if times.isna().any() or getattr(times.dt, "tz", None) is None or str(times.dt.tz) != "UTC":
        problems.append("wind.csv: time must be ISO timestamps with a UTC offset")
    if not np.allclose(df["speed"], np.hypot(df["u"], df["v"]), atol=0.01):
        problems.append("wind.csv: speed is not hypot(u, v)")
    turn = np.abs((df["dir_from_deg"] - wind_dir_from_deg(df["u"], df["v"]) + 180) % 360 - 180)
    if (turn[df["speed"] > 0.1] > 1.0).any():
        problems.append("wind.csv: dir_from_deg does not match u and v")
    if df["source"].isna().any() or df["level"].isna().any():
        problems.append("wind.csv: source and level must be set on every row")
    return problems


def _check_osm(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        return ["osm.geojson: not a FeatureCollection"]
    problems = []
    kinds = {f.get("properties", {}).get("kind") for f in data.get("features", [])}
    unknown = kinds - set(OSM_KINDS)
    if unknown:
        problems.append(f"osm.geojson: unknown kinds {sorted(str(k) for k in unknown)}")
    return problems


def check_slice(directory: Path) -> list[str]:
    """Return every problem found in a recorded slice; an empty list means the slice is usable."""
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        return [f"{manifest_path} is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = [f"manifest.json: key '{k}' is missing" for k in MANIFEST_KEYS if k not in manifest]
    if problems:
        return problems

    for listed in manifest["files"]:
        if not (directory / listed).exists():
            problems.append(f"manifest.json lists {listed}, which does not exist")
    for required in (*REQUIRED_GRID_FILES, "wind.csv"):
        if not (directory / required).exists():
            problems.append(f"{required} is missing")

    for filename, primary in GRID_FILES.items():
        if (directory / filename).exists():
            problems += _check_grid(directory / filename, primary, manifest["bbox"])
    if (directory / "wind.csv").exists():
        problems += _check_wind(directory / "wind.csv")
    if (directory / "osm.geojson").exists():
        problems += _check_osm(directory / "osm.geojson")
    if (directory / "firms.csv").exists():
        columns = set(pd.read_csv(directory / "firms.csv", nrows=0).columns)
        if not {"latitude", "longitude"} <= columns:
            problems.append("firms.csv: latitude and longitude columns are missing")
    if (directory / "s2_chips.nc").exists():
        with xr.open_dataset(directory / "s2_chips.nc") as chips:
            if tuple(chips["chips"].dims) != ("time", "band", "y", "x"):
                problems.append(f"s2_chips.nc: dims are {chips['chips'].dims}, expected (time, band, y, x)")

    size = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
    if size > MAX_SLICE_BYTES:
        problems.append(f"slice is {size / 1e6:.1f} MB, over the 50 MB limit")
    return problems
