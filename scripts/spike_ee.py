"""Phase S spike: look at the real data once, before anything is built on it.

Runs live (needs the Phase 0 credentials in .env) and writes docs/SPIKE_REPORT.md and
docs/SPIKE_FACTS.json. A section that fails is recorded in the report and the run continues.

    python scripts/spike_ee.py                       # everything
    python scripts/spike_ee.py --only collections wind
    python scripts/spike_ee.py --quota-tier "Community"

Asset ids below are the ones to probe. Band names are never typed in: they are picked from the
bands each collection reports, by pattern, and the report shows what was picked.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import traceback
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

import ee_common as live
import flare_sources
import spike_analysis as analysis
from app.geo.projection import local_aeqd
from app.settings import REPO_ROOT, get_settings
from spike_report import render

REPORT_PATH = REPO_ROOT / "docs" / "SPIKE_REPORT.md"
FACTS_PATH = REPO_ROOT / "docs" / "SPIKE_FACTS.json"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "spike"

# Ids to probe (plan Phase S, task 1). The report says which of them resolve.
CANDIDATES = {
    "s5p_no2_offl": "COPERNICUS/S5P/OFFL/L3_NO2",
    "s5p_no2_nrti": "COPERNICUS/S5P/NRTI/L3_NO2",
    "s5p_so2_offl": "COPERNICUS/S5P/OFFL/L3_SO2",
    "s5p_so2_nrti": "COPERNICUS/S5P/NRTI/L3_SO2",
    "s5p_ch4_offl": "COPERNICUS/S5P/OFFL/L3_CH4",
    "s5p_aer_ai_offl": "COPERNICUS/S5P/OFFL/L3_AER_AI",
    "s5p_aer_ai_nrti": "COPERNICUS/S5P/NRTI/L3_AER_AI",
    "era5_land_hourly": "ECMWF/ERA5_LAND/HOURLY",
    "era5_hourly": "ECMWF/ERA5/HOURLY",
    "gfs": "NOAA/GFS0P25",
    "s2_sr": "COPERNICUS/S2_SR_HARMONIZED",
    "worldcover": "ESA/WorldCover/v200",
    "worldpop": "WorldPop/GP/100m/pop",
    "modis_burned": "MODIS/061/MCD64A1",
}
# Product -> (collection key, pattern for its band, pattern for its cloud band or None).
PRODUCT_PATTERNS = {
    "no2": ("s5p_no2_offl", r"tropospheric.*NO2.*column", r"^cloud_fraction$"),
    "no2_nrti": ("s5p_no2_nrti", r"tropospheric.*NO2.*column", r"^cloud_fraction$"),
    "so2": ("s5p_so2_offl", r"^SO2_column_number_density$", r"^cloud_fraction$"),
    "so2_nrti": ("s5p_so2_nrti", r"^SO2_column_number_density$", r"^cloud_fraction$"),
    "ch4": ("s5p_ch4_offl", r"CH4_column_volume_mixing_ratio", None),
    "aer_ai": ("s5p_aer_ai_offl", r"aerosol_index", None),
    "aer_ai_nrti": ("s5p_aer_ai_nrti", r"aerosol_index", None),
}
WIND_KEYS = ("era5_hourly", "era5_land_hourly", "gfs")
WIND_BAND = re.compile(r"^(?P<component>[uv])_component_of_wind_(?P<height>\d+)m")
QA_BAND = re.compile(r"qa|cloud|quality", re.I)
FIRMS_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_SNPP_SP")
# CDS request to try for ERA5 100 m winds; the report records whether it worked.
CDS_DATASET = "reanalysis-era5-single-levels"
CDS_VARIABLES = ["100m_u_component_of_wind", "100m_v_component_of_wind"]

WINDOW_HALF_KM = 60
SO2_ALONG_KM = 30  # plan Phase 4, task 3
SO2_ACROSS_KM = 10
YEAR_DAYS = 365
DRY_SEASON_END = (2, 28)  # month, day: the dry-season comparison window ends here
CLUSTER_MAX_KM = 40  # plants farther than this from the analysis centre are left out
SECTIONS = ("collections", "plants", "wind", "cds", "grids", "timing", "firms", "flares")


def now_utc() -> datetime:
    return datetime.now(UTC)


def ms_to_iso(ms: float | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M") if ms else None


# --- collections -----------------------------------------------------------------------------


def probe_collection(asset_id: str, region: Any) -> dict[str, Any]:
    import ee

    info: dict[str, Any] = {"id": asset_id, "ok": False}
    try:
        collection = ee.ImageCollection(asset_id)
        first = ee.Image(collection.first())
        info["bands"] = live.retry(lambda: first.bandNames().getInfo())
        info["props"] = sorted(
            p for p in live.retry(lambda: first.propertyNames().getInfo()) if not p.startswith("system:")
        )
        projection = first.select(0).projection()
        info["scale_m"] = round(live.retry(lambda: projection.nominalScale().getInfo()), 2)
        info["crs"] = live.retry(lambda: projection.crs().getInfo())

        local = collection.filterBounds(region)
        latest = None
        for lookback_days in (30, 400, None):  # widen only when the recent window is empty
            scoped = (
                local
                if lookback_days is None
                else local.filterDate(ee.Date(now_utc().isoformat()).advance(-lookback_days, "day"), "2100-01-01")
            )
            latest = live.retry(lambda scoped=scoped: scoped.aggregate_max("system:time_start").getInfo())
            if latest:
                break
        info["latest"] = ms_to_iso(latest)
        if latest:
            info["latest_ms"] = latest
            info["latency_days"] = round((now_utc().timestamp() - latest / 1000) / 86400, 2)
        info["ok"] = True
    except Exception as exc:
        info["error"] = str(exc)[:300]
    return info


def pick_band(bands: list[str], pattern: str | None) -> str | None:
    if not pattern:
        return None
    matches = [b for b in bands if re.search(pattern, b, re.I)]
    return matches[0] if matches else None


def section_collections(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    facts["collections"] = {key: probe_collection(asset_id, ctx["region"]) for key, asset_id in CANDIDATES.items()}
    products = {}
    for name, (key, pattern, cloud_pattern) in PRODUCT_PATTERNS.items():
        collection = facts["collections"][key]
        bands = collection.get("bands", [])
        band = pick_band(bands, pattern)
        note = None
        if not collection["ok"]:
            note = "collection did not resolve"
        elif band is None:
            note = f"no band matches /{pattern}/; choose one from the band list by hand"
        elif len([b for b in bands if re.search(pattern, b, re.I)]) > 1:
            note = f"several bands match /{pattern}/; the first was taken"
        products[name] = {
            "collection_key": key,
            "id": collection["id"],
            "band": band,
            "cloud_band": pick_band(bands, cloud_pattern),
            "scale_m": collection.get("scale_m"),
            "note": note,
        }
    facts["products"] = products
    facts["s5p_qa"] = {
        key: {"qa_bands": [b for b in c.get("bands", []) if QA_BAND.search(b)]}
        for key, c in facts["collections"].items()
        if key.startswith("s5p_") and c["ok"]
    }


# --- plants and wind -------------------------------------------------------------------------


def section_plants(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    facts["plants"] = live.discover_plants(ctx["bbox"])


def analysis_centre(facts: dict[str, Any], ctx: dict[str, Any]) -> tuple[float, float]:
    """Centre of the analysis window: the mean position of the largest plants, else the bbox centroid."""
    plants = facts.get("plants") or []
    if not plants:
        return ctx["centroid"]
    return float(np.mean([p["lon"] for p in plants])), float(np.mean([p["lat"] for p in plants]))


def wind_pairs(bands: list[str]) -> dict[int, tuple[str, str]]:
    """{height_m: (u band, v band)} for the heights that have both components."""
    found: dict[int, dict[str, str]] = {}
    for band in bands:
        match = WIND_BAND.match(band)
        if match:
            found.setdefault(int(match["height"]), {}).setdefault(match["component"], band)
    return {h: (c["u"], c["v"]) for h, c in sorted(found.items()) if {"u", "v"} <= set(c)}


def forecast_filter(props: list[str]) -> dict[str, Any] | None:
    """For forecast collections keep the analysis step only, when such a property exists."""
    name = next((p for p in props if re.fullmatch(r"forecast_hours?", p)), None)
    return {name: 0} if name else None


def wind_series(
    facts: dict[str, Any], key: str, height: int, lon: float, lat: float, start: date, end: date, hour_utc: int = 8
) -> pd.DataFrame:
    """Daily wind at a point at one UTC hour (the 08:00 overpass by default): columns time, u, v."""
    collection = facts["collections"][key]
    u_band, v_band = wind_pairs(collection["bands"])[height]
    frame = live.point_timeseries(
        collection["id"], [u_band, v_band], lon, lat, start, end, collection["scale_m"],
        hour_utc=hour_utc, equals=forecast_filter(collection.get("props", [])),
    )  # fmt: skip
    return frame.rename(columns={u_band: "u", v_band: "v"})[["time", "u", "v"]].drop_duplicates("time")


def section_wind(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    lon, lat = analysis_centre(facts, ctx)
    start, end = ctx["days"][0], ctx["days"][-1]
    collections: dict[str, Any] = {}
    ratios = []
    for key in WIND_KEYS:
        collection = facts["collections"].get(key, {})
        if not collection.get("ok"):
            continue
        pairs = wind_pairs(collection["bands"])
        entry: dict[str, Any] = {"heights": list(pairs), "props": collection.get("props", [])[:12]}
        collections[key] = entry
        if not pairs:
            entry["note"] = "no u/v band pair matched; see the band list"
            continue
        top = max(pairs)
        entry["days_covered"] = len(wind_series(facts, key, top, lon, lat, start, end))
        if entry["days_covered"] == 0 and forecast_filter(collection.get("props", [])):
            # A forecast collection has analyses only at its run hours; look at the run before the overpass.
            at_six = len(wind_series(facts, key, top, lon, lat, start, end, hour_utc=6))
            entry["note"] = f"no analysis step at 08:00 UTC; the 06:00 UTC analysis covers {at_six} days of the window"
        if len(pairs) < 2:
            continue
        low = min(pairs)
        for plant in facts.get("plants", [])[:3] or [{"name": "region centroid", "lon": lon, "lat": lat}]:
            lo = wind_series(facts, key, low, plant["lon"], plant["lat"], start, end)
            hi = wind_series(facts, key, top, plant["lon"], plant["lat"], start, end)
            both = lo.merge(hi, on="time", suffixes=("_lo", "_hi"))
            if both.empty:
                continue
            mean_low = float(np.hypot(both["u_lo"], both["v_lo"]).mean())
            mean_high = float(np.hypot(both["u_hi"], both["v_hi"]).mean())
            ratios.append(
                {
                    "collection_key": key,
                    "plant": plant["name"],
                    "low_m": low,
                    "high_m": top,
                    "mean_low": mean_low,
                    "mean_high": mean_high,
                    "ratio": mean_high / mean_low if mean_low else None,
                    "n": len(both),
                }  # fmt: skip
            )
    facts["wind"] = {"collections": collections, "ratios": ratios}


def best_wind_key(facts: dict[str, Any]) -> tuple[str, int] | None:
    """The Earth Engine wind collection covering most days of the window; ties go to the higher level."""
    options = [
        (w.get("days_covered", 0), max(w["heights"]), key)
        for key, w in facts.get("wind", {}).get("collections", {}).items()
        if w.get("heights")
    ]
    if not options or max(options)[0] == 0:
        return None
    _, height, key = max(options)
    return key, height


def section_cds(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    import cdsapi
    import xarray as xr

    env = ctx["env"]
    west, south, east, north = ctx["bbox"]
    client = cdsapi.Client(url=env.cds_url or None, key=env.cds_key or None)  # falls back to ~/.cdsapirc
    result: dict[str, Any] = {"dataset": CDS_DATASET, "variables": CDS_VARIABLES}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for days_back in (6, 9, 14):  # the newest day that can be retrieved is the latency
        day = date.today() - timedelta(days=days_back)
        target = CACHE_DIR / f"cds_probe_{day.isoformat()}.nc"
        request = {
            "product_type": ["reanalysis"],
            "variable": CDS_VARIABLES,
            "year": [f"{day.year}"],
            "month": [f"{day.month:02d}"],
            "day": [f"{day.day:02d}"],
            "time": ["08:00"],
            "area": [north, west, south, east],
            "data_format": "netcdf",
            "download_format": "unarchived",
        }
        started = time.perf_counter()
        try:
            client.retrieve(CDS_DATASET, request, str(target))
        except Exception as exc:
            result[f"error at {days_back} days back"] = str(exc)[:300]
            continue
        result["seconds for one small request"] = round(time.perf_counter() - started, 1)
        result["newest day retrieved"] = day.isoformat()
        result["latency (days), at most"] = days_back
        with xr.open_dataset(target) as ds:
            result["variables in the file"] = list(ds.data_vars)
            result["dimensions in the file"] = {k: int(v) for k, v in ds.sizes.items()}
        result["request that worked"] = json.dumps(request)
        break
    result["access"] = "ok" if "newest day retrieved" in result else "failed"
    facts["cds"] = result


# --- grids: valid days, null buffers, SO2 window ----------------------------------------------


def cached_grids(
    name: str, product: dict[str, Any], bbox: tuple[float, ...], days: list[date]
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Daily grids of a product over the window; cached on disk so a re-run does not download again."""
    bands = [b for b in (product["band"], product.get("cloud_band")) if b]
    step_deg = round(product["scale_m"] / 111_320, 5) if product.get("scale_m") else 0.01
    path = CACHE_DIR / f"{name}_{days[0].isoformat()}_{days[-1].isoformat()}.npz"
    if path.exists():
        with np.load(path) as saved:
            return {b: saved[b] for b in bands}, saved["lats"], saved["lons"]
    grids, lats, lons = live.fetch_daily_grids(product["id"], bands, bbox, days, step_deg)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, lats=lats, lons=lons, **grids)
    return grids, lats, lons


def _weighted(months: pd.DataFrame) -> pd.DataFrame:
    """Per month the day-weighted share valid at 0.3, for months split across two downloads."""
    months = months.assign(ok_030=months["fraction_ok_030"] * months["days"])
    total = months.groupby("month", as_index=False)[["ok_030", "days"]].sum()
    return total.assign(fraction_ok_030=total["ok_030"] / total["days"])[["month", "fraction_ok_030"]]


def section_grids(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    cfg = ctx["cfg"]
    lon0, lat0 = analysis_centre(facts, ctx)
    facts["run"]["analysis_centre"] = [round(lon0, 4), round(lat0, 4)]
    days: list[date] = ctx["days"]
    window = live.window_bbox(lon0, lat0, WINDOW_HALF_KM)
    plants = facts.get("plants") or [{"name": "region centroid", "lon": lon0, "lat": lat0}]
    to_local = local_aeqd(lon0, lat0)[0]
    plants_km = [tuple(c / 1000 for c in to_local.transform(p["lon"], p["lat"])) for p in plants]
    plants_km = [p for p in plants_km if np.hypot(*p) <= CLUSTER_MAX_KM]
    min_fraction = cfg.detect["valid_fraction_min"]

    facts["valid_days"] = {}
    grids: dict[str, np.ndarray] = {}
    for name in ("no2", "so2"):
        product = facts["products"][name]
        if not product["band"]:
            raise RuntimeError(f"no band was picked for {name}; fix section 2 first")
        data, lats, lons = cached_grids(name, product, window, days)
        field = data[product["band"]]
        valid = ~np.isnan(field)
        months = analysis.valid_fraction_by_month(valid, days, min_fraction)
        months["fraction_ok_030"] = analysis.valid_fraction_by_month(valid, days, 0.3)["fraction_ok"]
        if name == "no2":
            # The detector window can fall wholly in the monsoon; a full year shows every season.
            earlier = live.last_days(days[0] - timedelta(days=1), YEAR_DAYS - len(days))
            band_only = product | {"cloud_band": None}
            year_field = cached_grids("no2_year", band_only, window, earlier)[0][product["band"]]
            year_valid = ~np.isnan(year_field)
            before = analysis.valid_fraction_by_month(year_valid, earlier, min_fraction)
            before["fraction_ok_030"] = analysis.valid_fraction_by_month(year_valid, earlier, 0.3)["fraction_ok"]
            months = (
                pd.concat([before, months])
                .groupby("month", as_index=False)[["days", "days_ok"]]
                .sum()
                .merge(_weighted(pd.concat([before, months])), on="month")
            )
            months["fraction_ok"] = months["days_ok"] / months["days"]
        facts["valid_days"][name] = {
            "min_fraction": min_fraction,
            "months": json.loads(months.to_json(orient="records")),
        }
        if product.get("cloud_band") and name == "no2":
            field = np.where(data[product["cloud_band"]] <= cfg.detect["cloud_max"], field, np.nan)
        grids[name] = field
        ctx["grid_axes"] = (lats, lons)
        key = product["collection_key"]
        if key in facts.get("s5p_qa", {}):
            facts["s5p_qa"][key]["masked_share"] = float(1 - valid[-1].mean())

    lats, lons = ctx["grid_axes"]
    geometry = {"lats": lats, "lons": lons, "centre": (lon0, lat0), "plants": plants, "plants_km": plants_km}
    facts["null_buffer"], facts["so2_window"] = run_prototypes(facts, cfg, grids["no2"], grids["so2"], days, geometry)

    # The same prototypes on the last dry season, when most days are valid.
    dry_end = max(
        d for d in (date(days[0].year, *DRY_SEASON_END), date(days[0].year - 1, *DRY_SEASON_END)) if d < days[0]
    )
    dry_days = live.last_days(dry_end, len(days))
    dry = {}
    for name in ("no2", "so2"):
        product = facts["products"][name]
        data = cached_grids(f"{name}_dry", product, window, dry_days)[0]
        dry[name] = data[product["band"]]
        if product.get("cloud_band") and name == "no2":
            dry[name] = np.where(data[product["cloud_band"]] <= cfg.detect["cloud_max"], dry[name], np.nan)
    null_buffer, so2_window = run_prototypes(facts, cfg, dry["no2"], dry["so2"], dry_days, geometry)
    facts["dry_season"] = {
        "start": dry_days[0].isoformat(),
        "end": dry_end.isoformat(),
        "null_buffer": null_buffer,
        "so2_window": so2_window,
    }


def run_prototypes(
    facts: dict[str, Any], cfg: Any, no2: np.ndarray, so2: np.ndarray, days: list[date], geometry: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The null-buffer test per day and the SO2 window test per plant, for one stretch of days."""
    lats, lons = geometry["lats"], geometry["lons"]
    min_fraction = cfg.detect["valid_fraction_min"]
    x_km, y_km = analysis.km_offsets(lats, lons, *geometry["centre"])

    rows = []
    for i, day in enumerate(days):
        result = analysis.null_buffer_z(
            no2[i], x_km, y_km, geometry["plants_km"],
            local_radius_km=cfg.detect["local_radius_km"], annulus_km=tuple(cfg.detect["null_annulus_km"]),
            mask_km=cfg.detect["null_mask_km"], n_null=cfg.detect["n_null"],
            n_null_min_valid=cfg.detect["n_null_min_valid"], min_valid_fraction=min_fraction,
            rng=np.random.default_rng([day.toordinal(), 1]),
        )  # fmt: skip
        if result:
            rows.append(result)
    tested = pd.DataFrame(rows)
    z_min = cfg.detect["z_bg_min"]
    null_buffer: dict[str, Any] = {"days": len(days), "days_tested": len(tested), "z_bg_min": z_min}
    if not tested.empty:
        null_buffer |= {
            "days_detected": int((tested["z_bg"] >= z_min).sum()),
            "median_excess": float((tested["local"] - tested["null_median"]).median()),
            "median_sigma": float(tested["null_sigma"].median()),
            "median_z": float(tested["z_bg"].median()),
        }

    so2_windows: list[dict[str, Any]] = []
    wind_choice = best_wind_key(facts)
    if wind_choice is None:
        raise RuntimeError("no Earth Engine wind collection covers the window; the SO2 window prototype was skipped")
    key, height = wind_choice
    window_days = cfg.detect["so2_window_days"]
    for plant in geometry["plants"][:3]:
        wind = wind_series(facts, key, height, plant["lon"], plant["lat"], days[0], days[-1])
        by_day = {t.date(): (u, v) for t, u, v in zip(wind["time"], wind["u"], wind["v"], strict=True)}
        px, py = analysis.km_offsets(lats, lons, plant["lon"], plant["lat"])
        for end in range(len(days), window_days - 1, -window_days):
            index = [i for i in range(end - window_days, end) if days[i] in by_day]
            result = analysis.so2_window_z(
                so2[index], [by_day[days[i]] for i in index], px, py,
                along_km=SO2_ALONG_KM, across_km=SO2_ACROSS_KM, min_valid_fraction=min_fraction,
                n_boot=cfg.detect["so2_boot"], rng=np.random.default_rng([days[end - 1].toordinal(), 2]),
            )  # fmt: skip
            so2_windows.append(
                {"plant": plant["name"], "window_end": days[end - 1].isoformat(), "wind_source": f"{key} {height} m"}
                | result
            )
    return null_buffer, so2_windows


# --- timing ----------------------------------------------------------------------------------


def section_timing(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    import ee

    product = facts["products"]["no2"]
    days: list[date] = ctx["days"]
    west, south, east, north = ctx["bbox"]
    rng = np.random.default_rng(0)
    points = [(float(rng.uniform(west, east)), float(rng.uniform(south, north))) for _ in range(20)]
    radius_m = ctx["cfg"].detect["local_radius_km"] * 1000
    buffers = ee.FeatureCollection(
        [ee.Feature(ee.Geometry.Point(list(p)).buffer(radius_m), {"unit_id": i}) for i, p in enumerate(points)]
    )
    collection = ee.ImageCollection(product["id"]).select([product["band"]])
    template = ee.ImageCollection([ee.Image.constant(0).rename([product["band"]]).toFloat().updateMask(0)])
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)

    def daily(day: Any) -> Any:
        start = ee.Date(day)
        return collection.filterDate(start, start.advance(1, "day")).merge(template).mean()

    timing = []
    small = {"test": "small reduceRegion calls, one day and one buffer each", "calls": 0}
    started = time.perf_counter()
    try:
        for i in range(100):
            image = daily(days[-1 - (i % len(days))].isoformat())
            image.reduceRegion(reducer, buffers.first().geometry(), product["scale_m"]).getInfo()
            small["calls"] += 1
    except Exception as exc:
        small["error"] = str(exc)[:300]
    small["seconds"] = round(time.perf_counter() - started, 1)
    timing.append(small)

    quarter = [d.isoformat() for d in days[-90:]]
    rows_expected = len(quarter) * len(points)

    # (a) one reduceRegions per day inside a mapped list: many aggregations in one request.
    nested = {"test": f"one request, reduceRegions mapped over {len(quarter)} days x {len(points)} buffers", "calls": 1}
    started = time.perf_counter()
    try:
        per_day = ee.List(quarter).map(
            lambda day: (
                daily(day)
                .reduceRegions(buffers, reducer, product["scale_m"])
                .map(
                    lambda f: ee.Feature(
                        None, {"unit_id": f.get("unit_id"), "mean": f.get("mean"), "count": f.get("count"), "date": day}
                    )
                )
            )
        )
        nested["rows"] = len(ee.FeatureCollection(per_day).flatten().getInfo()["features"])
    except Exception as exc:
        nested["error"] = str(exc)[:300]
    nested["seconds"] = round(time.perf_counter() - started, 1)
    timing.append(nested)

    # (b) the days stacked as bands of one image: a single reduceRegions, one aggregation.
    stacked = {"test": f"one request, one reduceRegions over {len(quarter)} days stacked as bands", "calls": 1}
    started = time.perf_counter()
    try:
        image = ee.Image.cat([daily(day).rename(["d" + day.replace("-", "")]) for day in quarter])
        table = image.reduceRegions(buffers, reducer, product["scale_m"]).map(lambda f: f.setGeometry(None))
        features = table.getInfo()["features"]
        values = sum(1 for f in features for k in f["properties"] if k.endswith("_count"))
        stacked["rows"] = values
        if values != rows_expected:
            stacked["error"] = f"expected {rows_expected} unit-days, got {values}"
    except Exception as exc:
        stacked["error"] = str(exc)[:300]
    stacked["seconds"] = round(time.perf_counter() - started, 1)
    timing.append(stacked)
    facts["timing"] = timing


# --- FIRMS and flare sources ------------------------------------------------------------------


def firms_area(env: live.LiveEnv, source: str, bbox: tuple[float, ...], day_range: int, start: date) -> pd.DataFrame:
    """One FIRMS area request. Raises with the response text when FIRMS does not return a CSV table."""
    from io import StringIO

    area = ",".join(f"{c:.4f}" for c in bbox)
    response = live.firms_get(
        f"/api/area/csv/{{key}}/{source}/{area}/{day_range}/{start.isoformat()}", env.firms_map_key
    )
    text = response.text
    if response.status_code != 200 or "latitude" not in text.splitlines()[0]:
        raise RuntimeError(f"HTTP {response.status_code}: {text[:200]}".replace(env.firms_map_key, "***"))
    return pd.read_csv(StringIO(text))


def section_firms(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    env = ctx["env"]
    if not env.firms_map_key:
        raise RuntimeError("FIRMS_MAP_KEY is not set in .env")
    result: dict[str, Any] = {"sources": {}}
    status = live.firms_get("/mapserver/mapkey_status/?MAP_KEY={key}", env.firms_map_key)
    result["key_status"] = status.text[:300].replace(env.firms_map_key, "***")

    available: dict[str, str] = {}
    listing = live.firms_get("/api/data_availability/csv/{key}/all", env.firms_map_key)
    for line in listing.text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 3:
            available[parts[0]] = f"{parts[1]} to {parts[2]}"

    today = date.today()
    for source in FIRMS_SOURCES:
        entry: dict[str, Any] = {"ok": False, "available": available.get(source)}
        result["sources"][source] = entry
        try:
            day_range = None
            for candidate in (10, 5, 1):  # find the largest day range the API accepts
                try:
                    firms_area(env, source, ctx["bbox"], candidate, today - timedelta(days=candidate - 1))
                    day_range = candidate
                    break
                except RuntimeError as exc:
                    entry["error"] = str(exc)
            if day_range is None:
                continue
            entry.pop("error", None)
            frames = []
            for back in range(90, 0, -day_range):
                frames.append(firms_area(env, source, ctx["bbox"], day_range, today - timedelta(days=back - 1)))
                time.sleep(0.5)
            rows = pd.concat(frames, ignore_index=True)
            entry |= {"ok": True, "day_range": day_range, "rows_90d": len(rows), "columns": list(rows.columns)}
            flaring = ctx["cfg"].flaring
            entry["near_plants"] = flare_sources.night_counts_near(
                rows, facts.get("plants", []), flaring["radius_km"], flaring["window_days"], flaring["min_frp_mw"]
            )
        except Exception as exc:
            entry["error"] = str(exc)[:300]
    facts["firms"] = result


def section_flares(facts: dict[str, Any], ctx: dict[str, Any]) -> None:
    """Annual flare-site files and hand-downloaded Nightfire files on disk. No network, no EOG credentials."""
    summary = flare_sources.flare_sites_summary(flare_sources.FLARE_DIR, ctx["bbox"])
    nightfire_dir = flare_sources.NIGHTFIRE_DIR
    summary["nightfire_files_on_disk"] = len(list(nightfire_dir.glob("*.csv*"))) if nightfire_dir.exists() else 0
    facts["flares"] = summary


# --- decisions -------------------------------------------------------------------------------


def suggest_decisions(facts: dict[str, Any], cfg: Any) -> list[dict[str, str]]:
    decisions = []
    collections = facts.get("collections", {})

    def add(decision: str, suggestion: str, basis: str) -> None:
        decisions.append({"decision": decision, "suggestion": suggestion, "basis": basis})

    wind = facts.get("wind", {}).get("collections", {})
    cds = facts.get("cds", {})
    if wind or cds:
        parts = []
        for key, w in wind.items():
            latency = collections.get(key, {}).get("latency_days")
            parts.append(
                f"{key}: levels {w.get('heights')} m, {w.get('days_covered', 0)} window days, latency {latency} d"
            )
        cds_latency = cds.get("latency (days), at most", "?")
        parts.append(f"CDS ERA5 100 m: access {cds.get('access', 'not checked')}, latency at most {cds_latency} d")
        add(
            "Wind chain",
            "History: the highest level that covers the window. Today: the source with the smallest latency. "
            "Keep a 10 m source last.",
            "; ".join(parts),
        )

    s5p_keys = ("s5p_no2_offl", "s5p_no2_nrti", "s5p_so2_offl", "s5p_so2_nrti")
    lag = {k: collections.get(k, {}).get("latency_days") for k in s5p_keys}
    if any(v is not None for v in lag.values()):
        add(
            "Source for today and for history",
            "Near-real-time collections for today when their latency is under 1 day; "
            "offline collections for history and re-runs.",
            ", ".join(f"{k} {v} d" for k, v in lag.items()),
        )

    months = facts.get("valid_days", {}).get("no2", {}).get("months", [])
    winter = [m for m in months if int(m["month"][5:]) in (10, 11, 12, 1, 2, 3)]
    if winter:
        share = sum(m["days_ok"] for m in winter) / sum(m["days"] for m in winter)
        threshold = cfg.detect["valid_fraction_min"]
        add(
            "valid_fraction_min and windows",
            "Keep the threshold." if share >= 0.4 else "Below 40 %: widen the windows in config (gate G1).",
            f"Oct–Mar months in the window: {share:.0%} of days valid at threshold {threshold}",
        )

    dry = facts.get("dry_season", {})
    so2_rows = facts.get("so2_window", []) + dry.get("so2_window", [])
    windows = [w for w in so2_rows if isinstance(w.get("z"), float) and not np.isnan(w["z"])]
    if windows:
        z_min = cfg.detect["z_bg_min"]
        best = max(w["z"] for w in windows)
        min_days = cfg.detect["so2_min_valid_days"]
        passed = sum(1 for w in windows if w["z"] >= z_min and w["p5"] > 0 and w.get("n_valid_days", 0) >= min_days)
        enough = sum(1 for w in windows if w.get("n_valid_days", 0) >= min_days)
        add(
            "SO2 scope (gate G1)",
            "SO2 detector stays."
            if passed
            else "No window passes: show SO2 as a regional layer only and move #2 to the trim list.",
            f"{passed} of {len(windows)} plant-windows have z ≥ {z_min}, a positive 5th percentile and at least "
            f"{min_days} valid days; "
            f"only {enough} windows have that many valid days; largest z {best:.2f} "
            f"(recent window and dry season {dry.get('start', 'not run')} to {dry.get('end', '')} together)",
        )

    flares = facts.get("flares")
    firms_sources = facts.get("firms", {}).get("sources", {})
    if flares is not None or firms_sources:
        min_nights = cfg.flaring["min_nights"]
        near = [row for source in firms_sources.values() for row in source.get("near_plants", [])]
        persistent = sorted({row["plant"] for row in near if row.get("max_nights_in_window_min_frp", 0) >= min_nights})
        sites = (flares or {}).get("sites_in_region", 0)
        nightfire_files = (flares or {}).get("nightfire_files_on_disk", 0)
        add(
            "Flaring source (`flaring.source`)",
            "firms_persistent."
            + (" Annual flare sites exist in the region: load them as a prior." if sites else "")
            + (" Nightfire files are on disk: `nightfire` can be tried." if nightfire_files else ""),
            f"{sites} annual flare sites in the region; {nightfire_files} Nightfire files on disk; "
            f"plants with at least {min_nights} nights of FRP ≥ {cfg.flaring['min_frp_mw']} MW "
            f"in a {cfg.flaring['window_days']}-day window: {', '.join(persistent) or 'none'}",
        )

    timing = {t["test"]: t for t in facts.get("timing", [])}
    if timing:
        add(
            "History requests",
            "Use the batched table call per quarter (get_buffer_timeseries); never one call per day.",
            "; ".join(f"{name}: {t.get('seconds')} s, error: {t.get('error', 'none')}" for name, t in timing.items()),
        )
    return decisions


# --- main ------------------------------------------------------------------------------------


def run_section(
    name: str, fn: Callable[[dict[str, Any], dict[str, Any]], None], facts: dict[str, Any], ctx: dict[str, Any]
) -> None:
    print(f"[{name}] running ...", flush=True)
    facts.setdefault("errors", {}).pop(name, None)
    try:
        fn(facts, ctx)
        print(f"[{name}] done", flush=True)
    except Exception as exc:
        traceback.print_exc()
        facts["errors"][name] = str(exc)[:400]
    FACTS_PATH.write_text(json.dumps(facts, indent=2, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", choices=SECTIONS, help="run only these sections; other results are kept")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--quota-tier", help="Earth Engine quota tier shown in the Cloud console")
    parser.add_argument("--skip-cds", action="store_true", help="skip the Copernicus CDS check")
    args = parser.parse_args()

    import ee

    env = live.LiveEnv()
    live.init_ee(env)
    cfg = get_settings().config
    west, south, east, north = cfg.region.bbox
    centroid = ((west + east) / 2, (south + north) / 2)

    facts: dict[str, Any] = json.loads(FACTS_PATH.read_text(encoding="utf-8")) if FACTS_PATH.exists() else {}
    ctx: dict[str, Any] = {
        "env": env, "cfg": cfg, "bbox": cfg.region.bbox, "centroid": centroid,
        "region": ee.Geometry.Rectangle([west, south, east, north], proj="EPSG:4326", geodesic=False),
    }  # fmt: skip
    wanted = [s for s in SECTIONS if (not args.only or s in args.only) and not (s == "cds" and args.skip_cds)]

    if "collections" in wanted or "collections" not in facts:
        run_section("collections", section_collections, facts, ctx)
    newest = facts.get("collections", {}).get("s5p_no2_offl", {}).get("latest_ms")
    end = datetime.fromtimestamp(newest / 1000, UTC).date() if newest else date.today() - timedelta(days=7)
    ctx["days"] = live.last_days(end, args.days)
    previous_tier = facts.get("run", {}).get("quota_tier")
    facts["run"] = {
        "started_at": now_utc().strftime("%Y-%m-%d %H:%M"), "region": cfg.region.name, "bbox": list(cfg.region.bbox),
        "centroid": [round(c, 4) for c in centroid], "window_km": 2 * WINDOW_HALF_KM, "days": args.days,
        "start": ctx["days"][0].isoformat(), "end": end.isoformat(), "ee_project": env.ee_project,
        "quota_tier": args.quota_tier or previous_tier,
    }  # fmt: skip

    sections = {
        "plants": section_plants, "wind": section_wind, "cds": section_cds, "grids": section_grids,
        "timing": section_timing, "firms": section_firms, "flares": section_flares,
    }  # fmt: skip
    for name in wanted:
        if name != "collections":
            run_section(name, sections[name], facts, ctx)

    facts["decisions"] = suggest_decisions(facts, cfg)
    FACTS_PATH.write_text(json.dumps(facts, indent=2, default=str), encoding="utf-8")
    REPORT_PATH.write_text(render(facts), encoding="utf-8")
    print(f"wrote {REPORT_PATH.relative_to(REPO_ROOT)} and {FACTS_PATH.relative_to(REPO_ROOT)}")
    if facts.get("errors"):
        print("sections with errors:", ", ".join(facts["errors"]))


if __name__ == "__main__":
    main()
