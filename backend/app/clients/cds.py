"""Copernicus Climate Data Store: ERA5 winds at 100 m (wind provider `cds_era5_100m`).

Dataset, variables and the request shape are the ones the spike found to work (config/sources.yaml).
One download per calendar month, cached as NetCDF. The CDS queue is slow (55 s for one small request
in the spike), so this provider sits behind Earth Engine's copy of the same data in `wind.chain`.
"""

from __future__ import annotations

import math
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from app.clients.base import cached
from app.settings import get_settings

GRID_DEG = 0.25  # the request area is widened to whole cells of the ERA5 grid


def _download(dataset: str, request: dict[str, Any], target: Path) -> None:
    import cdsapi

    settings = get_settings()
    client = cdsapi.Client(url=settings.cds_url or None, key=settings.cds_key or None)  # falls back to ~/.cdsapirc
    client.retrieve(dataset, request, str(target))


def normalise(ds: xr.Dataset, u_name: str, v_name: str) -> xr.Dataset:
    """Rename a CDS file to dims (time, lat, lon) with variables `u` and `v`, latitudes ascending."""
    time_name = next(n for n, c in ds.coords.items() if np.issubdtype(c.dtype, np.datetime64) and c.ndim == 1)
    lat_name = next(n for n in ds.dims if str(n).lower().startswith("lat"))
    lon_name = next(n for n in ds.dims if str(n).lower().startswith("lon"))
    out = ds[[u_name, v_name]].rename({u_name: "u", v_name: "v", time_name: "time", lat_name: "lat", lon_name: "lon"})
    out = out.drop_vars([c for c in out.coords if c not in ("time", "lat", "lon")])
    return out.transpose("time", "lat", "lon").sortby("lat")


def era5_100m(points: Sequence[tuple[float, float]], times: pd.DatetimeIndex) -> xr.Dataset:
    """ERA5 100 m wind `u`, `v` (time, lat, lon) on the cells around `points` at the hours of `times` (UTC)."""
    spec = get_settings().sources["wind"]["cds_era5_100m"]
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    area = [  # north, west, south, east
        math.ceil(max(lats) / GRID_DEG) * GRID_DEG + GRID_DEG,
        math.floor(min(lons) / GRID_DEG) * GRID_DEG - GRID_DEG,
        math.floor(min(lats) / GRID_DEG) * GRID_DEG - GRID_DEG,
        math.ceil(max(lons) / GRID_DEG) * GRID_DEG + GRID_DEG,
    ]
    hours = sorted({f"{t.hour:02d}:00" for t in times})
    parts = []
    for (year, month), group in pd.Series(times, index=times).groupby([times.year, times.month]):
        days = sorted({f"{t.day:02d}" for t in group})
        request = spec["request"] | {
            "year": [str(year)],
            "month": [f"{month:02d}"],
            "day": days,
            "time": hours,
            "area": area,
        }

        def fetch(request: dict[str, Any] = request) -> xr.Dataset:
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "era5.nc"
                _download(spec["dataset"], request, target)
                with xr.open_dataset(target) as ds:
                    return normalise(ds.load(), spec["u_variable"], spec["v_variable"])

        # The CDS delivers the days it has; a file with recent days is fetched again until they have settled.
        key = ["era5_100m", area, f"{year}-{month:02d}", days, hours]
        parts.append(cached("cds", key, "nc", fetch, data_end=group.max().date()))
    return xr.concat(parts, dim="time").sortby("time")
