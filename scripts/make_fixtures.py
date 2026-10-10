"""Record a real fixture slice for one region (plan Phase S, task 3). Runs live, once.

    python scripts/make_fixtures.py --unit singrauli --days 120
    python scripts/make_fixtures.py --unit singrauli --days 120 --wind cds --include-nightfire

Run scripts/spike_ee.py first: asset ids and band names are read from docs/SPIKE_FACTS.json,
never typed in here. The slice goes to tests/fixtures/real_<unit>/ and is checked on the way out.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

import ee_common as live
import flare_sources
from app.clients.slice_format import WIND_COLUMNS, check_slice, make_grid_dataset, wind_dir_from_deg
from app.settings import REPO_ROOT, get_settings
from spike_ee import FACTS_PATH, WINDOW_HALF_KM, analysis_centre, best_wind_key, firms_area, wind_series

S2_BANDS = ("B2", "B3", "B4", "B8", "B11", "B12", "SCL")  # plan Phase 2; checked against the spike's band list
S2_CHIP_PX = 128
S2_PIXEL_M = 10
S2_MAX_CLOUD_PCT = 20
S2_DATES = 3
# Slice variable -> product in SPIKE_FACTS.json.
GRID_PRODUCTS = {"no2": "no2", "so2": "so2", "aer_ai": "aer_ai"}


def record_grids(
    facts: dict[str, Any], window: tuple[float, ...], days: list[date], step_deg: float | None, out: Path
) -> dict[str, str]:
    sources = {}
    for name, product_key in GRID_PRODUCTS.items():
        product = facts["products"][product_key]
        if not product.get("band"):
            print(f"  {name}: no band confirmed by the spike; skipped")
            continue
        bands = [b for b in (product["band"], product.get("cloud_band") if name == "no2" else None) if b]
        step = step_deg or round(product["scale_m"] / 111_320, 5)
        grids, lats, lons = live.fetch_daily_grids(product["id"], bands, window, days, step)
        variables = {name: grids[product["band"]]}
        if len(bands) == 2:
            variables["cloud_fraction"] = grids[bands[1]]
        ds = make_grid_dataset(
            variables, days, lats, lons, primary=name, source="earthengine", ee_id=product["id"], mode="live-recorded"
        )
        ds.attrs["ee_bands"] = json.dumps(dict(zip(variables, bands, strict=True)))
        encoding = {v: {"zlib": True, "complevel": 5} for v in ds.data_vars}
        ds.to_netcdf(out / f"{name}.nc", encoding=encoding)
        sources[name] = f"{product['id']} [{', '.join(bands)}]"
        print(f"  {name}.nc: {dict(ds.sizes)}")
    return sources


def wind_rows(frame: pd.DataFrame, lon: float, lat: float, source: str, level: str) -> pd.DataFrame:
    out = pd.DataFrame({"time": frame["time"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "lon": lon, "lat": lat})
    out["u"], out["v"] = frame["u"].to_numpy(), frame["v"].to_numpy()
    out["speed"] = np.hypot(out["u"], out["v"])
    out["dir_from_deg"] = wind_dir_from_deg(out["u"], out["v"])
    out["source"], out["level"] = source, level
    return out[list(WIND_COLUMNS)]


def record_wind_ee(facts: dict[str, Any], points: list[dict[str, Any]], days: list[date]) -> tuple[pd.DataFrame, str]:
    choice = best_wind_key(facts)
    if choice is None:
        raise SystemExit(
            "no Earth Engine wind collection covers the window; run the spike's wind section or use --wind cds"
        )
    key, height = choice
    frames = [
        wind_rows(
            wind_series(facts, key, height, p["lon"], p["lat"], days[0], days[-1]),
            p["lon"],
            p["lat"],
            key,
            f"{height}m",
        )
        for p in points
    ]
    return pd.concat(frames, ignore_index=True), f"{facts['collections'][key]['id']} at {height} m"


def record_wind_cds(
    facts: dict[str, Any], env: live.LiveEnv, points: list[dict[str, Any]], days: list[date], out: Path
) -> tuple[pd.DataFrame, str]:
    """ERA5 100 m winds from the CDS, with the request the spike found to work, one download per month."""
    import cdsapi

    cds = facts.get("cds", {})
    if cds.get("access") != "ok":
        raise SystemExit("the spike did not confirm CDS access; run `spike_ee.py --only cds` first")
    request = json.loads(cds["request that worked"])
    client = cdsapi.Client(url=env.cds_url or None, key=env.cds_key or None)
    frames = []
    for year, month in sorted({(d.year, d.month) for d in days}):
        month_days = [d for d in days if (d.year, d.month) == (year, month)]
        target = out / f"_cds_{year}{month:02d}.nc"
        client.retrieve(
            cds["dataset"],
            request | {"year": [str(year)], "month": [f"{month:02d}"], "day": [f"{d.day:02d}" for d in month_days]},
            str(target),
        )
        with xr.open_dataset(target) as ds:
            ds.load()
        target.unlink()
        time_name = next(n for n, c in ds.coords.items() if np.issubdtype(c.dtype, np.datetime64))
        lat_name = next(n for n in ds.coords if n.lower().startswith("lat"))
        lon_name = next(n for n in ds.coords if n.lower().startswith("lon"))
        u_name = next(v for v in ds.data_vars if v.lower().startswith("u"))
        v_name = next(v for v in ds.data_vars if v.lower().startswith("v"))
        for p in points:
            cell = ds.sel({lat_name: p["lat"], lon_name: p["lon"]}, method="nearest")
            frame = pd.DataFrame(
                {
                    "time": pd.to_datetime(cell[time_name].values, utc=True),
                    "u": cell[u_name].values.ravel(),
                    "v": cell[v_name].values.ravel(),
                }
            )
            frames.append(wind_rows(frame, p["lon"], p["lat"], "cds_era5_100m", "100m"))
    return pd.concat(frames, ignore_index=True), f"CDS {cds['dataset']} {cds['variables']}"


def record_firms(
    facts: dict[str, Any], env: live.LiveEnv, bbox: tuple[float, ...], days: list[date], out: Path
) -> tuple[str | None, list[str]]:
    notes, frames = [], []
    for source, entry in facts.get("firms", {}).get("sources", {}).items():
        if not entry.get("ok"):
            continue
        step = entry["day_range"]
        for first in range(0, len(days), step):
            part = days[first : first + step]
            try:
                frame = firms_area(env, source, bbox, len(part), part[0])
            except RuntimeError as exc:
                notes.append(f"firms {source} from {part[0]}: {str(exc)[:120]}")
                continue
            frame["source"] = source
            frames.append(frame)
            time.sleep(0.5)
    if not frames:
        return None, notes or ["firms: the spike confirmed no source"]
    pd.concat(frames, ignore_index=True).to_csv(out / "firms.csv", index=False)
    return "FIRMS area API", notes


def record_flare_sites(bbox: tuple[float, ...], out: Path) -> str | None:
    """Annual flare sites inside the region, from the files in data/registry/raw/flares/."""
    frames = []
    for entry in flare_sources.flare_sites_summary(flare_sources.FLARE_DIR, bbox)["files"]:
        if "error" in entry:
            continue
        sites = flare_sources.in_bbox(flare_sources.read_flare_sites(flare_sources.FLARE_DIR / entry["file"]), bbox)
        frames.append(sites.assign(source_file=entry["file"]))
    if not frames:
        return None
    pd.concat(frames, ignore_index=True).to_csv(out / "flare_sites.csv", index=False)
    return f"{len(frames)} annual flare files, {sum(len(f) for f in frames)} sites in the region"


def record_nightfire(bbox: tuple[float, ...], out: Path) -> str | None:
    """Clip the nightly Nightfire CSVs in data/raw/nightfire/ to the region. Only on request:
    the files are licence-gated, and the slice is committed."""
    west, south, east, north = bbox
    frames = []
    for path in sorted(flare_sources.NIGHTFIRE_DIR.glob("*.csv*")):
        frame = pd.read_csv(path)
        lat = next(c for c in frame.columns if re.match(r"lat", c, re.I))
        lon = next(c for c in frame.columns if re.match(r"lon", c, re.I))
        inside = frame[frame[lat].between(south, north) & frame[lon].between(west, east)].copy()
        inside["source_file"] = path.name
        frames.append(inside)
    if not frames:
        return None
    pd.concat(frames, ignore_index=True).to_csv(out / "nightfire.csv", index=False)
    return f"{len(frames)} nightly files from the Earth Observation Group"


def record_osm(bbox: tuple[float, ...], out: Path) -> str:
    features = []
    for kind, elements in live.overpass(bbox, list(live.OSM_SELECTORS)).items():
        for element in elements:
            geometry = live.element_geometry(element)
            if geometry is None:
                continue
            properties = {"kind": kind, "osm_type": element["type"], "osm_id": element["id"], **element.get("tags", {})}
            features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    collection = {"type": "FeatureCollection", "features": features}
    (out / "osm.geojson").write_text(json.dumps(collection), encoding="utf-8")
    return f"Overpass, {len(features)} features"


def record_chips(facts: dict[str, Any], lon: float, lat: float, days: list[date], out: Path) -> str:
    """The least cloudy Sentinel-2 chips around a point, with their acquisition times."""
    import ee

    s2 = facts["collections"]["s2_sr"]
    missing = [b for b in S2_BANDS if b not in s2.get("bands", [])]
    cloud_property = next((p for p in s2.get("props", []) if p.upper() == "CLOUDY_PIXEL_PERCENTAGE"), None)
    if not s2.get("ok") or missing or cloud_property is None:
        raise RuntimeError(
            f"Sentinel-2 not usable as recorded by the spike (missing bands {missing}, cloud property {cloud_property})"
        )

    point = ee.Geometry.Point([lon, lat])
    scenes = (
        ee.ImageCollection(s2["id"])
        .filterBounds(point)
        .filterDate(days[0].isoformat(), (days[-1] + timedelta(days=1)).isoformat())
        .filter(ee.Filter.lt(cloud_property, S2_MAX_CLOUD_PCT))
        .sort(cloud_property)
        .limit(S2_DATES)
    )
    listed = live.retry(
        lambda: scenes.reduceColumns(ee.Reducer.toList(2), ["system:index", "system:time_start"]).get("list").getInfo()
    )
    if not listed:
        raise RuntimeError(f"no Sentinel-2 scene under {S2_MAX_CLOUD_PCT}% cloud in the window")

    dlat = S2_PIXEL_M / 111_320
    dlon = dlat / np.cos(np.radians(lat))
    half = S2_CHIP_PX / 2
    grid = {
        "dimensions": {"width": S2_CHIP_PX, "height": S2_CHIP_PX},
        "affineTransform": {
            "scaleX": dlon,
            "shearX": 0,
            "translateX": lon - half * dlon,
            "shearY": 0,
            "scaleY": -dlat,
            "translateY": lat + half * dlat,
        },  # fmt: skip
        "crsCode": "EPSG:4326",
    }
    chips, times = [], []
    for index, ms in sorted(listed, key=lambda row: row[1]):
        image = ee.Image(f"{s2['id']}/{index}").select(list(S2_BANDS)).toUint16()
        request = {"expression": image, "fileFormat": "NUMPY_NDARRAY", "grid": grid}
        pixels = live.retry(lambda request=request: ee.data.computePixels(request))
        chips.append(np.stack([pixels[b] for b in pixels.dtype.names]))
        times.append(datetime.fromtimestamp(ms / 1000, UTC).replace(tzinfo=None))
    ds = xr.Dataset(
        {"chips": (("time", "band", "y", "x"), np.stack(chips).astype("uint16"))},
        coords={
            "time": pd.DatetimeIndex(times),
            "band": list(S2_BANDS),
            "lat": ("y", lat + (half - 0.5 - np.arange(S2_CHIP_PX)) * dlat),
            "lon": ("x", lon + (np.arange(S2_CHIP_PX) + 0.5 - half) * dlon),
        },
        attrs={
            "source": "earthengine",
            "ee_id": s2["id"],
            "mode": "live-recorded",
            "pixel_m": S2_PIXEL_M,
            "resampled_to": "EPSG:4326",
        },
    )
    ds["time"].attrs["time_zone"] = "UTC"
    ds.to_netcdf(out / "s2_chips.nc", encoding={"chips": {"zlib": True, "complevel": 5}})
    return f"{s2['id']}, {len(times)} chips at {[t.isoformat() for t in times]}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--unit", required=True, help="region name; must be the region in config/settings.yaml")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--end", type=date.fromisoformat, help="last day of the slice (default: the spike's last day)")
    parser.add_argument("--wind", choices=("ee", "cds"), default="ee", help="wind source to record (gate G1 decides)")
    parser.add_argument("--step-deg", type=float, help="grid step in degrees; set a larger one to shrink the slice")
    parser.add_argument(
        "--include-nightfire",
        action="store_true",
        help="also record data/raw/nightfire/*.csv; check that your licence allows committing them",
    )
    args = parser.parse_args()

    cfg = get_settings().config
    if args.unit != cfg.region.name:
        raise SystemExit(f"--unit {args.unit} is not the configured region ({cfg.region.name})")
    if not FACTS_PATH.exists():
        raise SystemExit("docs/SPIKE_FACTS.json is missing: run scripts/spike_ee.py first")
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    env = live.LiveEnv()
    live.init_ee(env)

    out = REPO_ROOT / "tests" / "fixtures" / f"real_{args.unit}"
    out.mkdir(parents=True, exist_ok=True)
    west, south, east, north = cfg.region.bbox
    lon0, lat0 = analysis_centre(facts, {"centroid": ((west + east) / 2, (south + north) / 2)})
    window = live.window_bbox(lon0, lat0, WINDOW_HALF_KM)
    end = args.end or date.fromisoformat(facts["run"]["end"])
    days = live.last_days(end, args.days)
    plants = facts.get("plants") or []
    points = [{"name": "analysis centre", "lon": lon0, "lat": lat0}, *plants]

    sources: dict[str, Any] = {}
    notes: list[str] = []
    print("grids ...")
    sources |= record_grids(facts, window, days, args.step_deg, out)
    print("wind ...")
    wind, sources["wind"] = (
        record_wind_cds(facts, env, points, days, out) if args.wind == "cds" else record_wind_ee(facts, points, days)
    )
    wind.to_csv(out / "wind.csv", index=False)

    optional = {
        "firms": lambda: record_firms(facts, env, cfg.region.bbox, days, out),
        "flare_sites": lambda: (record_flare_sites(cfg.region.bbox, out), []),
        "osm": lambda: (record_osm(cfg.region.bbox, out), []),
        "s2_chips": lambda: (
            record_chips(facts, plants[0]["lon"] if plants else lon0, plants[0]["lat"] if plants else lat0, days, out),
            [],
        ),
    }
    if args.include_nightfire:
        optional["nightfire"] = lambda: (record_nightfire(cfg.region.bbox, out), [])
    for name, record in optional.items():
        print(f"{name} ...")
        try:
            source, extra = record()
            notes += extra
            if source:
                sources[name] = source
            else:
                notes.append(f"{name}: nothing recorded")
        except Exception as exc:
            notes.append(f"{name}: {str(exc)[:200]}")

    manifest = {
        "unit": args.unit,
        "created_at": datetime.now(UTC).isoformat(),
        "start": days[0].isoformat(),
        "end": days[-1].isoformat(),
        "days": len(days),
        "bbox": list(window),
        "region_bbox": list(cfg.region.bbox),
        "centre": [lon0, lat0],
        "plants": plants,
        "sources": sources,
        "notes": notes,
        "files": sorted(p.name for p in out.iterdir() if p.name != "manifest.json"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    problems = check_slice(out)
    print(f"wrote {out.relative_to(REPO_ROOT)} ({sum(p.stat().st_size for p in out.iterdir()) / 1e6:.1f} MB)")
    for note in notes:
        print("note:", note)
    if problems:
        raise SystemExit("slice has problems:\n  " + "\n  ".join(problems))
    print("slice passes the integrity check; commit it and run `make test`")


if __name__ == "__main__":
    main()
