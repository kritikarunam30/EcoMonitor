"""Wind for points and times through a provider chain (plan §0.6 and Phase 2, task 2).

`get_wind` is the only place the app gets wind from. Providers are tried in the order of `wind.chain`
in settings.yaml (gate G1: era5_100m_ee, cds_era5_100m, gfs_ee, era5_land_10m_ee). A time that the
first provider cannot answer for every point goes to the next one, and the result says which
provider answered each time, at which level and with which uncertainty. A 10 m wind is never returned
as if it were a 100 m wind: `level` is recorded per time and in the attrs.

    python -m app.clients.wind --smoke      # live check, needs DATA_MODE=live and the keys in .env
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from app.clients import cds, ee_client
from app.clients.base import cached, data_mode, fixture_paths, retry
from app.clients.slice_format import wind_dir_from_deg
from app.geo.projection import local_aeqd
from app.settings import get_settings

log = logging.getLogger(__name__)

Points = Sequence[tuple[float, float]]  # (lon, lat)
SAMPLE_COLUMNS = ["time", "lon", "lat", "u", "v"]
EE_CHUNK_DAYS = 92  # one getRegion request per quarter of the requested period


@dataclass(frozen=True)
class Provider:
    """One wind source. `fetch(points, times)` returns `u`, `v` as (time, point) arrays, NaN where it
    has no data, and per time the hours between the requested time and the data used."""

    name: str
    level: str
    fetch: Callable[[Points, pd.DatetimeIndex], tuple[np.ndarray, np.ndarray, np.ndarray]]


def utc_index(times: Iterable[datetime | pd.Timestamp | str]) -> pd.DatetimeIndex:
    """Times as a UTC index without a timezone (the convention of the grids); naive input is taken as UTC."""
    return pd.DatetimeIndex(pd.to_datetime(list(times), utc=True)).tz_localize(None)


def match_samples(
    samples: pd.DataFrame, points: Points, times: pd.DatetimeIndex, max_km: float, max_offset_h: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pick, for every point and time, the sample of the nearest location (within `max_km`) at the
    nearest time (within `max_offset_h`; 0 means the exact time). `samples` has time, lon, lat, u, v."""
    shape = (len(times), len(points))
    u, v = np.full(shape, np.nan), np.full(shape, np.nan)
    offset = np.full(shape, np.nan)
    if samples.empty or not len(times) or not len(points):
        return u, v, np.full(len(times), np.nan)
    sites = samples[["lon", "lat"]].drop_duplicates().to_numpy(dtype=float)
    tolerance = pd.Timedelta(hours=max_offset_h)
    for j, (lon, lat) in enumerate(points):
        to_local, _ = local_aeqd(lon, lat)
        x, y = to_local.transform(sites[:, 0], sites[:, 1])
        distance = np.hypot(x, y)
        nearest = int(distance.argmin())
        if distance[nearest] > max_km * 1000:
            continue
        here = samples[(samples["lon"] == sites[nearest, 0]) & (samples["lat"] == sites[nearest, 1])]
        series = here.dropna(subset=["u", "v"]).drop_duplicates("time").set_index("time").sort_index()
        if series.empty:
            continue
        found = series.index.get_indexer(times, method="nearest", tolerance=tolerance)
        ok = found >= 0
        u[ok, j] = series["u"].to_numpy()[found[ok]]
        v[ok, j] = series["v"].to_numpy()[found[ok]]
        offset[ok, j] = (series.index[found[ok]] - times[ok]) / pd.Timedelta(hours=1)
    worst = np.where(np.isnan(offset), -1.0, np.abs(offset)).max(axis=1)
    return u, v, np.where(worst < 0, np.nan, worst)


# --- where each provider's samples come from ------------------------------------------------------


def _fixture_samples(name: str, spec: dict[str, Any]) -> pd.DataFrame:
    """Rows of the fixture wind tables recorded from this provider, at this provider's level."""
    frames = []
    for path in fixture_paths("wind.csv"):
        rows = pd.read_csv(path)
        mine = rows["source"].isin([name, spec.get("collection")]) & (rows["level"] == spec["level"])
        frames.append(rows[mine])
    if not frames:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    rows = pd.concat(frames, ignore_index=True)
    rows["time"] = utc_index(rows["time"])
    return rows[SAMPLE_COLUMNS]


def _ee_samples(spec: dict[str, Any], points: Points, times: pd.DatetimeIndex, max_offset_h: float) -> pd.DataFrame:
    """Wind at the pixels under the points, one getRegion request per quarter (never one per day or point)."""
    ee = ee_client._ee()
    bands = [spec["u_band"], spec["v_band"]]
    where = ee.Geometry.MultiPoint([list(p) for p in points])
    pad = pd.Timedelta(hours=max_offset_h)
    frames = []
    for first in pd.date_range(times.min().normalize(), times.max(), freq=f"{EE_CHUNK_DAYS}D"):
        part = times[(times >= first) & (times < first + pd.Timedelta(days=EE_CHUNK_DAYS))]
        if not len(part):
            continue
        collection = (
            ee.ImageCollection(spec["id"])
            .select(bands)
            .filterDate((part.min() - pad).isoformat(), (part.max() + pad + pd.Timedelta(hours=1)).isoformat())
        )
        if spec.get("analysis_property"):  # a forecast collection: keep the analysis step of each run
            collection = collection.filter(ee.Filter.eq(spec["analysis_property"], 0))
        else:
            hours = [ee.Filter.calendarRange(int(h), int(h), "hour") for h in sorted(set(part.hour))]
            collection = collection.filter(ee.Filter.Or(*hours) if len(hours) > 1 else hours[0])
        try:
            rows = retry(lambda collection=collection: collection.getRegion(where, spec["scale_m"]).getInfo())
        except ee.EEException as exc:
            if "No bands in collection" not in str(exc):  # that message means no image passed the filters
                raise
            continue
        frame = pd.DataFrame(rows[1:], columns=rows[0])
        frame["time"] = pd.to_datetime(frame["time"], unit="ms")
        frames.append(
            frame.rename(columns={"longitude": "lon", "latitude": "lat", bands[0]: "u", bands[1]: "v"})[SAMPLE_COLUMNS]
        )
    if not frames:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    return pd.concat(frames, ignore_index=True).astype({"u": "float64", "v": "float64"})


def _cds_samples(points: Points, times: pd.DatetimeIndex) -> pd.DataFrame:
    grid = cds.era5_100m(points, times)
    return grid.to_dataframe().reset_index()[SAMPLE_COLUMNS]


def _provider(name: str) -> Provider:
    settings = get_settings()
    spec = settings.sources["wind"].get(name)
    if spec is None:
        raise ValueError(f"wind provider '{name}' is not in config/sources.yaml (not confirmed by the spike)")
    # A sample belongs to a point when it lies within one cell of the provider's grid.
    max_km = (spec.get("scale_m") or settings.sources["collections"]["era5_hourly"]["scale_m"]) / 1000
    max_offset_h = settings.config.wind["gfs_max_offset_hours"] if spec.get("analysis_property") else 0

    def fetch(points: Points, times: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if data_mode() == "fixture":
            samples = _fixture_samples(name, spec)
        elif "dataset" in spec:
            samples = _cds_samples(points, times)  # cached per month as NetCDF in clients/cds.py
        else:
            samples = cached(
                "wind",
                [name, [list(p) for p in points], [t.isoformat() for t in times]],
                "parquet",
                lambda: _ee_samples(spec, points, times, max_offset_h),
                data_end=times.max().date(),
            )
        return match_samples(samples, points, times, max_km, max_offset_h)

    return Provider(name=name, level=spec["level"], fetch=fetch)


# --- the chain ------------------------------------------------------------------------------------


def get_wind(
    points: Points, times: Iterable[datetime | pd.Timestamp | str], providers: Sequence[Provider] | None = None
) -> xr.Dataset:
    """Wind at (lon, lat) points and UTC times: `u`, `v`, `speed` (m/s) and `dir_from_deg`, dims (time, point).

    Per time: `source`, `level`, `uncertainty_frac` and `time_offset_h` (hours between the requested
    time and the data; non-zero only for gfs_ee, which has analyses at its run hours). A time no
    provider answered has NaN wind and an empty `source`. Attrs `source` and `level` list what was
    used, in chain order; `uncertainty_frac` is the largest one used; `notes` says why a provider was
    skipped. `providers` replaces the configured chain (tests).
    """
    cfg = get_settings().config.wind
    points = [(float(lon), float(lat)) for lon, lat in points]
    times = utc_index(times)
    chain = list(providers) if providers is not None else [_provider(name) for name in cfg["chain"]]

    shape = (len(times), len(points))
    u, v = np.full(shape, np.nan), np.full(shape, np.nan)
    source = np.full(len(times), "", dtype=object)
    level = np.full(len(times), "", dtype=object)
    uncertainty = np.full(len(times), np.nan)
    offset = np.full(len(times), np.nan)
    notes = []
    for provider in chain:
        todo = np.flatnonzero(source == "")
        if not len(todo) or not points:
            break
        try:
            pu, pv, poffset = provider.fetch(points, times[todo])
        except Exception as exc:  # a provider that is down must not stop the chain; the result says so
            log.warning("wind provider %s failed: %s", provider.name, exc)
            notes.append(f"{provider.name}: {str(exc)[:200]}")
            continue
        answered = np.isfinite(pu).all(axis=1) & np.isfinite(pv).all(axis=1)
        rows = todo[answered]
        u[rows], v[rows] = pu[answered], pv[answered]
        source[rows], level[rows] = provider.name, provider.level
        uncertainty[rows] = cfg["uncertainty_frac"][provider.name]
        offset[rows] = poffset[answered]

    used = [p for p in chain if (source == p.name).any()]
    ds = xr.Dataset(
        {
            "u": (("time", "point"), u),
            "v": (("time", "point"), v),
            "speed": (("time", "point"), np.hypot(u, v)),
            "dir_from_deg": (("time", "point"), wind_dir_from_deg(u, v)),
            "source": ("time", source.astype(str)),
            "level": ("time", level.astype(str)),
            "uncertainty_frac": ("time", uncertainty),
            "time_offset_h": ("time", offset),
        },
        coords={
            "time": times,
            "point": np.arange(len(points)),
            "lon": ("point", [p[0] for p in points]),
            "lat": ("point", [p[1] for p in points]),
        },
    )
    ds["time"].attrs["time_zone"] = "UTC"
    for name in ("u", "v", "speed"):
        ds[name].attrs["units"] = "m/s"
    ds.attrs.update(
        source=",".join(p.name for p in used) or "none",
        level=",".join(dict.fromkeys(p.level for p in used)) or "none",
        uncertainty_frac=float(np.nanmax(uncertainty)) if used else float("nan"),
        chain=",".join(p.name for p in chain),
        mode=data_mode(),
        notes="; ".join(notes),
    )
    return ds


def smoke() -> None:
    """Live: wind at the region centre for the last 12 overpasses, showing where the chain switches."""
    if data_mode() != "live":
        raise SystemExit("the smoke check talks to Earth Engine and the CDS: run it with DATA_MODE=live")
    west, south, east, north = get_settings().config.region.bbox
    today = pd.Timestamp.now(tz="UTC").normalize()
    times = [today - pd.Timedelta(days=back) + pd.Timedelta(hours=8) for back in range(12, 0, -1)]
    wind = get_wind([((west + east) / 2, (south + north) / 2)], times)
    for i, t in enumerate(wind.time.values):
        speed, direction = float(wind.speed[i, 0]), float(wind.dir_from_deg[i, 0])
        print(
            f"{pd.Timestamp(t):%Y-%m-%d %H:%M}  {speed:5.2f} m/s from {direction:5.1f}°"
            f"  {str(wind.source.values[i]) or 'no provider':18s} {wind.level.values[i]:5s}"
            f" ±{float(wind.uncertainty_frac[i]):.2f}  offset {float(wind.time_offset_h[i]):.0f} h"
        )
    print(f"attrs: source={wind.attrs['source']} level={wind.attrs['level']} notes={wind.attrs['notes'] or '-'}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="run a small live request and print the result")
    if parser.parse_args().smoke:
        smoke()
    else:
        parser.print_help()
