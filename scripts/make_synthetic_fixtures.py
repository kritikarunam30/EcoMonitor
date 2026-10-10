"""Write the small synthetic fixtures in tests/fixtures/synthetic/ (plan Phase 2, task 5). No network.

    python scripts/make_synthetic_fixtures.py

They stand in for products the recorded Singrauli slice does not hold: monthly CH4, land cover,
burned area, population, and a 10 m GFS wind for days after the slice (so the wind chain can be
seen to fall through). The values are made up and are marked `mode: synthetic`; only shapes, units
and variable names follow the real products. Asset ids are copied from config/sources.yaml.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import xarray as xr

from app.clients.slice_format import WIND_COLUMNS, wind_dir_from_deg
from app.settings import REPO_ROOT, get_settings

OUT = REPO_ROOT / "tests" / "fixtures" / "synthetic"
SLICE = REPO_ROOT / "tests" / "fixtures" / "real_singrauli"
STEP_DEG = 0.05
MONTHS = pd.DatetimeIndex(["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01"])
GFS_DAYS = pd.date_range("2026-03-01", "2026-03-05")  # the days after the recorded slice
GFS_ANALYSIS_HOUR = 6  # the spike found GFS analyses at run hours only, none at 08:00 UTC
LANDCOVER_CLASSES = [10, 30, 40, 50, 80]  # tree cover, grassland, cropland, built-up, water


def _attrs(ee_id: str) -> dict[str, str]:
    return {"source": "synthetic", "ee_id": ee_id, "fetched_at": "2026-10-10T00:00:00+00:00", "mode": "synthetic"}


def main() -> None:
    sources = get_settings().sources
    manifest = json.loads((SLICE / "manifest.json").read_text(encoding="utf-8"))
    west, south, east, north = manifest["bbox"]
    lats = np.round(np.arange(south + STEP_DEG / 2, north, STEP_DEG), 4)
    lons = np.round(np.arange(west + STEP_DEG / 2, east, STEP_DEG), 4)
    shape = (len(lats), len(lons))
    rng = np.random.default_rng(0)
    OUT.mkdir(parents=True, exist_ok=True)

    ch4 = rng.normal(1900.0, 8.0, (len(MONTHS), *shape)).astype("float32")
    ch4[rng.random(ch4.shape) < 0.3] = np.nan
    ds = xr.Dataset({"ch4": (("time", "lat", "lon"), ch4)}, coords={"time": MONTHS, "lat": lats, "lon": lons})
    ds["ch4"].attrs["units"] = "ppb"
    ds["valid"] = ds["ch4"].notnull()
    ds["time"].attrs["time_zone"] = "UTC"
    ds.attrs.update(_attrs(sources["products"]["ch4"]["id"]))
    ds.to_netcdf(OUT / "ch4.nc")

    landcover = rng.choice(LANDCOVER_CLASSES, size=shape, p=[0.3, 0.1, 0.45, 0.1, 0.05]).astype("float32")
    ds = xr.Dataset({"landcover": (("lat", "lon"), landcover)}, coords={"lat": lats, "lon": lons})
    ds.attrs.update(_attrs(sources["worldcover"]["id"]))
    ds.to_netcdf(OUT / "worldcover.nc")

    burn = np.full((len(MONTHS), *shape), np.nan, dtype="float32")
    burn[0, 2:5, 3:7] = rng.integers(305, 335, (3, 4))  # a few fields burned in November
    ds = xr.Dataset({"burn_date": (("time", "lat", "lon"), burn)}, coords={"time": MONTHS, "lat": lats, "lon": lons})
    ds["time"].attrs["time_zone"] = "UTC"
    ds.attrs.update(_attrs(sources["modis_burned"]["id"]))
    ds.to_netcdf(OUT / "burned_area.nc")

    population = rng.gamma(2.0, 4000.0, shape).round().astype("float32")  # people per cell
    ds = xr.Dataset({"population": (("lat", "lon"), population)}, coords={"lat": lats, "lon": lons})
    ds.attrs.update(_attrs(sources["worldpop"]["id"]))
    ds.to_netcdf(OUT / "population.nc")

    gfs = sources["wind"]["gfs_ee"]
    rows = []
    points = [manifest["centre"], *[[p["lon"], p["lat"]] for p in manifest["plants"]]]
    for day in GFS_DAYS:
        u, v = rng.normal(2.0, 1.0), rng.normal(-1.5, 1.0)
        for lon, lat in points:
            when = (day + pd.Timedelta(hours=GFS_ANALYSIS_HOUR)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            rows.append({"time": when, "lon": lon, "lat": lat, "u": round(u, 3), "v": round(v, 3)})
    wind = pd.DataFrame(rows)
    wind["speed"] = np.hypot(wind["u"], wind["v"])
    wind["dir_from_deg"] = wind_dir_from_deg(wind["u"], wind["v"])
    wind["source"], wind["level"] = gfs["collection"], gfs["level"]
    wind[list(WIND_COLUMNS)].to_csv(OUT / "wind.csv", index=False)
    print(f"wrote {sorted(p.name for p in OUT.iterdir() if p.name != '.gitkeep')} to {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
