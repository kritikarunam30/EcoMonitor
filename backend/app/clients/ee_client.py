"""Earth Engine client (plan Phase 2, task 1). Grids follow plan §0.6: dims (time, lat, lon), NaN for missing.

Asset ids and band names come only from config/sources.yaml, which is generated from the spike.
History is never read day by day: grids stack `data.ee_chunk_days` days into one pixel request, and
`get_buffer_timeseries` stacks a quarter of days as bands of one image for a single `reduceRegions`
(the spike found that mapping `reduceRegions` over days hits "Too many concurrent aggregations").

    python -m app.clients.ee_client --smoke      # live check, needs DATA_MODE=live and the keys in .env
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd
import shapely
import xarray as xr

from app.clients.base import (
    Bbox,
    DataUnavailable,
    cache_path,
    cached,
    data_mode,
    days_between,
    fixture_path,
    retry,
)
from app.clients.slice_format import make_grid_dataset
from app.geo.projection import local_aeqd
from app.settings import get_settings

Stream = Literal["offl", "nrti"]
TS_COLUMNS = ["unit_id", "date", "mean", "n_valid", "n_total", "cloud_mean"]
METRES_PER_DEGREE = 111_320
# Scene-classification values of the Sentinel-2 L2A product that hide the ground:
# cloud shadow, cloud (medium and high probability), thin cirrus.
SCL_CLOUD_CLASSES = (3, 8, 9, 10)

_initialised = False


def _ee() -> Any:
    """The `ee` module, initialised with the service account on first use."""
    global _initialised
    import ee

    if not _initialised:
        settings = get_settings()
        key_file = settings.resolve(settings.ee_key_file)
        if not (settings.ee_project and settings.ee_service_account and key_file.exists()):
            raise DataUnavailable(
                "Earth Engine is not configured: set EE_PROJECT and EE_SERVICE_ACCOUNT in .env "
                f"and place the service-account key at {key_file} (plan Phase 0)."
            )
        credentials = ee.ServiceAccountCredentials(settings.ee_service_account, str(key_file))
        ee.Initialize(credentials, project=settings.ee_project)
        _initialised = True
    return ee


def _sources() -> dict[str, Any]:
    return get_settings().sources


def _data_cfg() -> dict[str, Any]:
    return get_settings().config.data


def step_deg(scale_m: float) -> float:
    """Grid step in degrees for a product's native scale (0.01° for Sentinel-5P Level 3)."""
    return round(scale_m / METRES_PER_DEGREE, 5)


def grid_spec(bbox: Bbox, step_deg: float) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """computePixels grid for a bbox, plus the cell-centre latitudes (ascending) and longitudes."""
    west, south, east, north = bbox
    width = max(1, round((east - west) / step_deg))
    height = max(1, round((north - south) / step_deg))
    spec = {
        "dimensions": {"width": width, "height": height},
        "affineTransform": {
            "scaleX": step_deg,
            "shearX": 0,
            "translateX": west,
            "shearY": 0,
            "scaleY": -step_deg,
            "translateY": north,
        },
        "crsCode": "EPSG:4326",
    }
    lats = north - (np.arange(height) + 0.5) * step_deg
    lons = west + (np.arange(width) + 0.5) * step_deg
    return spec, lats[::-1].copy(), lons


def snap_bbox(bbox: Bbox, step_deg: float) -> tuple[float, float, float, float]:
    """Widen a bbox to whole cells of a grid whose cell edges are multiples of `step_deg`.

    The Sentinel-5P Level-3 grids are such grids (0.01° from -180, -90). Sampling them on a grid that
    is not aligned returns each native pixel under coordinates up to half a cell off, which changes a
    5 km buffer mean over a plume by several per cent.
    """
    west, south, east, north = bbox
    low = [math.floor(v / step_deg + 1e-6) * step_deg for v in (west, south)]
    high = [math.ceil(v / step_deg - 1e-6) * step_deg for v in (east, north)]
    return round(low[0], 6), round(low[1], 6), round(high[0], 6), round(high[1], 6)


def _masked_template(ee: Any, bands: Sequence[str]) -> Any:
    """A fully masked image with these bands, so a period without data still yields them."""
    return ee.ImageCollection([ee.Image.constant([0] * len(bands)).rename(list(bands)).toFloat().updateMask(0)])


def _pixels(image: Any, n_bands: int, bbox: Bbox, step: float) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
    """Sample the bands of an image on a regular grid, in one request.

    Returns one (lat, lon) float32 array per band, NaN where the image is masked, rows south first.
    """
    ee = _ee()
    spec, lats, lons = grid_spec(bbox, step)
    stacked = ee.Image.cat([image.unmask(0).toFloat(), image.mask().toFloat()])
    request = {"expression": stacked, "fileFormat": "NUMPY_NDARRAY", "grid": spec}
    pixels = retry(lambda: ee.data.computePixels(request))
    planes = [pixels[name] for name in pixels.dtype.names]
    if len(planes) != 2 * n_bands:
        raise RuntimeError(f"expected {2 * n_bands} bands back from Earth Engine, got {len(planes)}")
    arrays = [np.where(planes[n_bands + k] > 0, planes[k], np.nan)[::-1].astype("float32") for k in range(n_bands)]
    return arrays, lats, lons


def daily_grids(
    collection_id: str,
    bands: Sequence[str],
    bbox: Bbox,
    days: Sequence[date],
    step_deg: float,
    chunk_days: int = 20,
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Daily mean grids of `bands` as {band: (time, lat, lon) float32}, NaN where the product is masked.

    A day is a UTC calendar day. Days are stacked into one image per chunk, so the number of
    requests is len(days) / chunk_days, not len(days). The bbox is widened to whole grid cells
    (`snap_bbox`), so the returned coordinates are the centres of the product's own pixels.
    """
    ee = _ee()
    bands = list(bands)
    n = len(bands)
    bbox = snap_bbox(bbox, step_deg)
    _, lats, lons = grid_spec(bbox, step_deg)
    region = ee.Geometry.Rectangle(list(bbox), proj="EPSG:4326", geodesic=False)
    collection = ee.ImageCollection(collection_id).filterBounds(region).select(bands)
    template = _masked_template(ee, bands)
    out = {b: np.full((len(days), len(lats), len(lons)), np.nan, dtype="float32") for b in bands}

    for first in range(0, len(days), chunk_days):
        part = days[first : first + chunk_days]
        layers = []
        for day in part:
            start = ee.Date(day.isoformat())
            layers.append(collection.filterDate(start, start.advance(1, "day")).merge(template).mean())
        arrays, _, _ = _pixels(ee.Image.cat(layers), len(part) * n, bbox, step_deg)
        for j in range(len(part)):
            for k, band in enumerate(bands):
                out[band][first + j] = arrays[j * n + k]
    return out, lats, lons


# --- Sentinel-5P grids ----------------------------------------------------------------------------


def stream_for(product: str, day: date, today: date | None = None) -> Stream:
    """Gate G1: the near-real-time collection for days the offline collection has not reached yet."""
    sources = _sources()
    if f"{product}_nrti" not in sources["products"]:
        return "offl"
    offline = sources["collections"][sources["products"][product]["collection"]]
    age = ((today or datetime.now(UTC).date()) - day).days
    return "nrti" if age < math.ceil(offline["latency_days"]) else "offl"


def _product_key(product: str, stream: Stream) -> str:
    key = product if stream == "offl" else f"{product}_{stream}"
    if key not in _sources()["products"]:
        raise DataUnavailable(f"product '{key}' was not confirmed by the spike (config/sources.yaml)")
    return key


def _clip(ds: xr.Dataset, aoi: Bbox) -> xr.Dataset:
    west, south, east, north = aoi
    return ds.sel(lat=slice(south, north), lon=slice(west, east))


def _open_fixture(name: str) -> xr.Dataset:
    with xr.open_dataset(fixture_path(name)) as ds:
        ds = ds.load()
    ds.attrs["mode"] = "fixture"
    return ds


def _daily_product(key: str, aoi: Bbox, start: date, end: date, with_cloud: bool) -> xr.Dataset:
    spec = _sources()["products"][key]
    variable = spec["variable"]
    if data_mode() == "fixture":
        ds = _clip(_open_fixture(f"{key}.nc"), aoi).sel(time=slice(start.isoformat(), end.isoformat()))
        return ds if with_cloud else ds.drop_vars("cloud_fraction", errors="ignore")

    def fetch() -> xr.Dataset:
        bands = [spec["band"], *([spec["cloud_band"]] if with_cloud and spec["cloud_band"] else [])]
        days = days_between(start, end)
        grids, lats, lons = daily_grids(
            spec["id"], bands, aoi, days, step_deg(spec["scale_m"]), _data_cfg()["ee_chunk_days"]
        )
        variables = {variable: grids[spec["band"]]}
        if len(bands) == 2:
            variables["cloud_fraction"] = grids[bands[1]]
        ds = make_grid_dataset(
            variables, days, lats, lons, primary=variable, source="earthengine", ee_id=spec["id"], mode="live"
        )
        ds.attrs["ee_bands"] = json.dumps(dict(zip(variables, bands, strict=True)))
        return ds

    return cached("ee", [key, list(aoi), start, end, with_cloud], "nc", fetch, data_end=end)


def get_no2(aoi: Bbox, start: date, end: date, stream: Stream = "offl") -> xr.Dataset:
    """Daily tropospheric NO2: `no2` (mol/m²), `cloud_fraction`, `valid`."""
    return _daily_product(_product_key("no2", stream), aoi, start, end, with_cloud=True)


def get_so2(aoi: Bbox, start: date, end: date, stream: Stream = "offl") -> xr.Dataset:
    """Daily SO2 column: `so2` (mol/m²), `valid`."""
    return _daily_product(_product_key("so2", stream), aoi, start, end, with_cloud=False)


def get_aerosol_index(aoi: Bbox, start: date, end: date, stream: Stream = "offl") -> xr.Dataset:
    """Daily UV aerosol index: `aer_ai`, `valid`. High values flag smoke and haze days."""
    return _daily_product(_product_key("aer_ai", stream), aoi, start, end, with_cloud=False)


def _month_start(month: date | str) -> date:
    return date.fromisoformat(f"{month}-01") if isinstance(month, str) else month.replace(day=1)


def _next_month(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


def _static_dataset(name: str, array: np.ndarray, lats: np.ndarray, lons: np.ndarray, ee_id: str) -> xr.Dataset:
    ds = xr.Dataset({name: (("lat", "lon"), array)}, coords={"lat": lats, "lon": lons})
    ds.attrs.update(source="earthengine", ee_id=ee_id, fetched_at=datetime.now(UTC).isoformat(), mode="live")
    return ds


def get_ch4(aoi: Bbox, month: date | str) -> xr.Dataset:
    """Monthly mean methane mixing ratio: `ch4` (ppb), `valid`. `month` is a date in it, or "YYYY-MM".

    The time coordinate is the first day of the month.
    """
    first = _month_start(month)
    spec = _sources()["products"]["ch4"]
    if data_mode() == "fixture":
        return _clip(_open_fixture("ch4.nc"), aoi).sel(time=slice(first.isoformat(), first.isoformat()))

    def fetch() -> xr.Dataset:
        ee = _ee()
        collection = ee.ImageCollection(spec["id"]).select([spec["band"]])
        image = collection.filterDate(first.isoformat(), _next_month(first).isoformat())
        step = step_deg(spec["scale_m"])
        (grid,), lats, lons = _pixels(
            image.merge(_masked_template(ee, [spec["band"]])).mean(), 1, snap_bbox(aoi, step), step
        )
        ds = xr.Dataset(
            {"ch4": (("time", "lat", "lon"), grid[None])},
            coords={"time": pd.DatetimeIndex([pd.Timestamp(first)]), "lat": lats, "lon": lons},
        )
        ds["ch4"].attrs["units"] = "ppb"
        ds["valid"] = ds["ch4"].notnull()
        ds["time"].attrs["time_zone"] = "UTC"
        ds.attrs.update(source="earthengine", ee_id=spec["id"], fetched_at=datetime.now(UTC).isoformat(), mode="live")
        return ds

    return cached("ee", ["ch4", list(aoi), first], "nc", fetch, data_end=_next_month(first) - timedelta(days=1))


# --- land cover, vegetation, burned area, population ----------------------------------------------


def get_worldcover(aoi: Bbox) -> xr.Dataset:
    """Land-cover class per cell: `landcover` (lat, lon), sampled at `data.worldcover_scale_m`."""
    if data_mode() == "fixture":
        return _clip(_open_fixture("worldcover.nc"), aoi)
    spec = _sources()["worldcover"]
    scale_m = _data_cfg()["worldcover_scale_m"]

    def fetch() -> xr.Dataset:
        ee = _ee()
        image = ee.ImageCollection(spec["id"]).select([spec["band"]]).mosaic()
        (grid,), lats, lons = _pixels(image, 1, aoi, step_deg(scale_m))
        return _static_dataset("landcover", grid, lats, lons, spec["id"])

    return cached("ee", ["worldcover", list(aoi), scale_m], "nc", fetch)


def _ndvi(nir: Any, red: Any) -> Any:
    return (nir - red) / (nir + red)


def get_ndvi(aoi: Bbox, day: date) -> xr.Dataset:
    """Vegetation index around a date: `ndvi` (lat, lon), the median of the cloud-free Sentinel-2
    pixels within `data.ndvi_window_days`, sampled at `data.ndvi_scale_m`."""
    s2 = _sources()["s2"]
    cfg = _data_cfg()
    if data_mode() == "fixture":
        chips = _open_fixture("s2_chips.nc")
        chip = chips.isel(time=int(np.abs(chips.time.values - np.datetime64(day)).argmin()))
        bands = chip["chips"].astype("float32")
        ndvi = _ndvi(bands.sel(band=s2["nir_band"]), bands.sel(band=s2["red_band"]))
        ndvi = ndvi.where(~chip["chips"].sel(band=s2["scl_band"]).isin(SCL_CLOUD_CLASSES))
        ds = xr.Dataset(
            {"ndvi": (("lat", "lon"), ndvi.values[::-1])}, coords={"lat": chip.lat.values[::-1], "lon": chip.lon.values}
        )
        ds.attrs.update(chips.attrs)
        return _clip(ds, aoi)

    def fetch() -> xr.Dataset:
        ee = _ee()
        region = ee.Geometry.Rectangle(list(aoi), proj="EPSG:4326", geodesic=False)
        window = timedelta(days=cfg["ndvi_window_days"])
        scenes = (
            ee.ImageCollection(s2["id"])
            .filterBounds(region)
            .filterDate((day - window).isoformat(), (day + window + timedelta(days=1)).isoformat())
        )

        def one(image: Any) -> Any:
            clear = image.select(s2["scl_band"]).remap(list(SCL_CLOUD_CLASSES), [0] * len(SCL_CLOUD_CLASSES), 1)
            return (
                image.normalizedDifference([s2["nir_band"], s2["red_band"]]).rename("ndvi").toFloat().updateMask(clear)
            )

        image = scenes.map(one).merge(_masked_template(ee, ["ndvi"])).median()
        (grid,), lats, lons = _pixels(image, 1, aoi, step_deg(cfg["ndvi_scale_m"]))
        return _static_dataset("ndvi", grid, lats, lons, s2["id"])

    return cached(
        "ee", ["ndvi", list(aoi), day, cfg["ndvi_window_days"], cfg["ndvi_scale_m"]], "nc", fetch, data_end=day
    )


def get_burned_area(aoi: Bbox, start: date, end: date) -> xr.Dataset:
    """MODIS burned area per month: `burn_date` (time, lat, lon) is the day of year a cell burned, NaN
    where it did not. The time coordinate is the first day of each month from `start` to `end`."""
    if data_mode() == "fixture":
        first, last = _month_start(start), _month_start(end)
        return _clip(_open_fixture("burned_area.nc"), aoi).sel(time=slice(first.isoformat(), last.isoformat()))
    spec = _sources()["modis_burned"]

    def fetch() -> xr.Dataset:
        ee = _ee()
        months = [_month_start(start)]
        while _next_month(months[-1]) <= end:
            months.append(_next_month(months[-1]))
        # The band is a 16-bit integer; cast it so the collection stays homogeneous with the float template.
        collection = ee.ImageCollection(spec["id"]).select([spec["band"]]).map(lambda image: image.toFloat())
        template = _masked_template(ee, [spec["band"]])
        layers = [
            collection.filterDate(m.isoformat(), _next_month(m).isoformat()).merge(template).max() for m in months
        ]
        arrays, lats, lons = _pixels(ee.Image.cat(layers), len(months), aoi, step_deg(spec["scale_m"]))
        stack = np.stack(arrays)
        ds = xr.Dataset(
            {"burn_date": (("time", "lat", "lon"), np.where(stack > 0, stack, np.nan).astype("float32"))},
            coords={"time": pd.DatetimeIndex([pd.Timestamp(m) for m in months]), "lat": lats, "lon": lons},
        )
        ds["time"].attrs["time_zone"] = "UTC"
        ds.attrs.update(source="earthengine", ee_id=spec["id"], fetched_at=datetime.now(UTC).isoformat(), mode="live")
        return ds

    return cached("ee", ["burned_area", list(aoi), start, end], "nc", fetch, data_end=end)


def get_population(geom: dict[str, Any]) -> float:
    """People inside a GeoJSON geometry (WorldPop, newest year the spike saw)."""
    if data_mode() == "fixture":
        grid = _open_fixture("population.nc")["population"]
        lon, lat = np.meshgrid(grid.lon.values, grid.lat.values)
        inside = shapely.contains_xy(shapely.geometry.shape(geom), lon, lat)
        return float(np.nansum(grid.values[inside]))
    spec = _sources()["worldpop"]

    def fetch() -> dict[str, float]:
        ee = _ee()
        region = ee.Geometry(geom)
        year_start = date.fromisoformat(spec["latest"][:10])
        image = (
            ee.ImageCollection(spec["id"])
            .filterBounds(region)
            .filterDate(year_start.isoformat(), year_start.replace(year=year_start.year + 1).isoformat())
            .select([spec["band"]])
            .mosaic()
        )
        total = image.reduceRegion(ee.Reducer.sum(), region, spec["scale_m"], maxPixels=1e9).get(spec["band"])
        return {"population": float(retry(total.getInfo) or 0.0)}

    return cached("ee", ["population", geom], "json", fetch)["population"]


# --- Sentinel-2 chips and map tiles ---------------------------------------------------------------


def get_s2_chip(point: tuple[float, float], day: date, size_px: int = 128) -> xr.Dataset | None:
    """The Sentinel-2 chip around a (lon, lat) point closest in time to `day`, or None when no scene
    under `data.s2_max_cloud_pct` lies within `data.s2_search_days`.

    Variables: `chip` (band, y, x) with the six bands of sources.yaml, `scl` and `cloud_mask` (y, x).
    The acquisition time is in attrs `acquired_at` (UTC); the scene is rarely from the requested day.
    """
    s2 = _sources()["s2"]
    cfg = _data_cfg()
    lon, lat = point
    if data_mode() == "fixture":
        stored = _open_fixture("s2_chips.nc")
        offsets = np.abs(stored.time.values - np.datetime64(day)) / np.timedelta64(1, "D")
        index = int(offsets.argmin())
        raw = stored.isel(time=index)
        half_lat, half_lon = abs(float(raw.lat[1] - raw.lat[0])) / 2, abs(float(raw.lon[1] - raw.lon[0])) / 2
        inside = (raw.lat.min() - half_lat <= lat <= raw.lat.max() + half_lat) and (
            raw.lon.min() - half_lon <= lon <= raw.lon.max() + half_lon
        )
        if offsets[index] > cfg["s2_search_days"] + 1 or not inside or size_px > raw.sizes["y"]:
            return None
        y0 = int(np.clip(np.abs(raw.lat.values - lat).argmin() - size_px // 2, 0, raw.sizes["y"] - size_px))
        x0 = int(np.clip(np.abs(raw.lon.values - lon).argmin() - size_px // 2, 0, raw.sizes["x"] - size_px))
        raw = raw.isel(y=slice(y0, y0 + size_px), x=slice(x0, x0 + size_px))
        acquired = pd.Timestamp(stored.time.values[index]).tz_localize("UTC")
        return _chip_dataset(raw["chips"].values, list(raw.band.values), raw.lat.values, raw.lon.values, acquired, s2)

    def fetch() -> xr.Dataset | None:
        ee = _ee()
        where = ee.Geometry.Point([lon, lat])
        search = timedelta(days=cfg["s2_search_days"])
        scenes = (
            ee.ImageCollection(s2["id"])
            .filterBounds(where)
            .filterDate((day - search).isoformat(), (day + search + timedelta(days=1)).isoformat())
            .filter(ee.Filter.lt(s2["cloud_property"], cfg["s2_max_cloud_pct"]))
        )
        columns = ["system:index", "system:time_start", s2["cloud_property"]]
        listed = retry(lambda: scenes.reduceColumns(ee.Reducer.toList(3), columns).get("list").getInfo())
        if not listed:
            return None
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp() * 1000
        index, ms, _ = min(listed, key=lambda row: (round(abs(row[1] - noon) / 86_400_000), row[2]))

        dlat = s2["pixel_m"] / METRES_PER_DEGREE
        dlon = dlat / np.cos(np.radians(lat))
        half = size_px / 2
        grid = {
            "dimensions": {"width": size_px, "height": size_px},
            "affineTransform": {
                "scaleX": dlon,
                "shearX": 0,
                "translateX": lon - half * dlon,
                "shearY": 0,
                "scaleY": -dlat,
                "translateY": lat + half * dlat,
            },
            "crsCode": "EPSG:4326",
        }
        bands = [*s2["chip_bands"], s2["scl_band"]]
        image = ee.Image(f"{s2['id']}/{index}").select(bands).toUint16()
        request = {"expression": image, "fileFormat": "NUMPY_NDARRAY", "grid": grid}
        pixels = retry(lambda: ee.data.computePixels(request))
        lats = lat + (half - 0.5 - np.arange(size_px)) * dlat
        lons = lon + (np.arange(size_px) + 0.5 - half) * dlon
        acquired = pd.Timestamp(ms, unit="ms", tz="UTC")
        return _chip_dataset(np.stack([pixels[b] for b in pixels.dtype.names]), bands, lats, lons, acquired, s2)

    key = ["chip", lon, lat, day, size_px]
    if data_mode() == "live" and not cache_path("s2", key, "nc").exists():
        chip = fetch()
        if chip is None:  # not written to the cache: a scene may still arrive
            return None
        return cached("s2", key, "nc", lambda: chip)
    return cached("s2", key, "nc", fetch)


def _chip_dataset(
    stack: np.ndarray, bands: list[str], lats: np.ndarray, lons: np.ndarray, acquired: pd.Timestamp, s2: dict[str, Any]
) -> xr.Dataset:
    """Split a (band, y, x) stack that ends with the scene classification into the chip dataset."""
    order = [bands.index(b) for b in s2["chip_bands"]]
    scl = stack[bands.index(s2["scl_band"])].astype("uint8")
    ds = xr.Dataset(
        {
            "chip": (("band", "y", "x"), stack[order].astype("uint16")),
            "scl": (("y", "x"), scl),
            "cloud_mask": (("y", "x"), np.isin(scl, SCL_CLOUD_CLASSES)),
        },
        coords={"band": list(s2["chip_bands"]), "lat": ("y", lats), "lon": ("x", lons)},
    )
    ds.attrs.update(
        source="earthengine", ee_id=s2["id"], mode=data_mode(), acquired_at=acquired.isoformat(), pixel_m=s2["pixel_m"]
    )
    return ds


def get_tile_url(layer: str, day: date) -> str:
    """XYZ tile URL template for a gas layer on a day (CH4: the month of that day). Display range and
    palette come from `layers` in settings.yaml. Earth Engine tile URLs expire, so they are not cached."""
    layers = get_settings().config.layers
    if layer not in layers:
        raise ValueError(f"unknown layer '{layer}'; settings.yaml has {sorted(layers)}")
    mode = data_mode()
    if mode == "fixture":
        return f"fixture://tiles/{layer}/{day.isoformat()}/{{z}}/{{x}}/{{y}}.png"
    if mode != "live":
        raise DataUnavailable(f"tile URLs need DATA_MODE=live (now: {mode})")
    ee = _ee()
    monthly = layer == "ch4"
    spec = _sources()["products"][layer if monthly else _product_key(layer, stream_for(layer, day))]
    start = _month_start(day) if monthly else day
    end = _next_month(day) if monthly else day + timedelta(days=1)
    image = ee.ImageCollection(spec["id"]).select([spec["band"]]).filterDate(start.isoformat(), end.isoformat()).mean()
    style = layers[layer]
    map_id = retry(lambda: image.getMapId({"min": style["min"], "max": style["max"], "palette": style["palette"]}))
    return map_id["tile_fetcher"].url_format


# --- batched buffer time series -------------------------------------------------------------------


def quarter_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] at calendar-quarter boundaries; one Earth Engine request per chunk."""
    chunks = []
    while start <= end:
        first_month = (start.month - 1) // 3 * 3 + 1
        quarter_end = date(start.year + (first_month == 10), (first_month + 2) % 12 + 1, 1)
        last = min(end, quarter_end - timedelta(days=1))
        chunks.append((start, last))
        start = last + timedelta(days=1)
    return chunks


def buffer_stats(ds: xr.Dataset, variable: str, units: Sequence[Any], radius_km: float) -> pd.DataFrame:
    """Per unit and day: mean of `variable` inside the buffer, pixels with a value, pixels in the
    buffer and the mean cloud fraction (NaN when the grid has none). Pure; used in fixture mode."""
    lon, lat = np.meshgrid(ds.lon.values, ds.lat.values)
    dates = pd.DatetimeIndex(ds.time.values).normalize()
    values = ds[variable].values
    cloud = ds["cloud_fraction"].values if "cloud_fraction" in ds else None
    frames = []
    for unit in units:
        to_local, _ = local_aeqd(unit.lon, unit.lat)
        x, y = to_local.transform(lon, lat)
        inside = np.hypot(x, y) <= radius_km * 1000
        cells = values[:, inside]
        n_valid = np.isfinite(cells).sum(axis=1)
        frame = pd.DataFrame({"unit_id": unit.id, "date": dates, "n_valid": n_valid, "n_total": int(inside.sum())})
        frame["mean"] = np.where(n_valid > 0, np.nansum(cells, axis=1) / np.maximum(n_valid, 1), np.nan)
        frame["cloud_mean"] = np.nan
        if cloud is not None:
            seen = np.isfinite(cloud[:, inside]).sum(axis=1)
            frame["cloud_mean"] = np.where(seen > 0, np.nansum(cloud[:, inside], axis=1) / np.maximum(seen, 1), np.nan)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)[TS_COLUMNS] if frames else pd.DataFrame(columns=TS_COLUMNS)


def table_from_features(features: Sequence[dict[str, Any]], days: Sequence[date]) -> pd.DataFrame:
    """Turn the `reduceRegions` result of the stacked image (bands v<day>, c<day>, total) into rows."""
    rows = []
    for feature in features:
        p = feature["properties"]
        for day in days:
            tag = day.strftime("%Y%m%d")
            rows.append(
                {
                    "unit_id": p["unit_id"],
                    "date": pd.Timestamp(day),
                    "mean": p.get(f"v{tag}_mean"),
                    "n_valid": int(p.get(f"v{tag}_count") or 0),
                    "n_total": int(p.get("total_count") or 0),
                    "cloud_mean": p.get(f"c{tag}_mean"),
                }
            )
    frame = pd.DataFrame(rows, columns=TS_COLUMNS)
    return frame.astype({"mean": "float64", "cloud_mean": "float64"})


def _fetch_buffer_chunk(
    units: Sequence[Any], days: Sequence[date], spec: dict[str, Any], radius_km: float
) -> pd.DataFrame:
    ee = _ee()
    bands = [spec["band"], *([spec["cloud_band"]] if spec["cloud_band"] else [])]
    collection = ee.ImageCollection(spec["id"]).select(bands)
    template = _masked_template(ee, bands)
    layers = []
    for day in days:
        start = ee.Date(day.isoformat())
        tag = day.strftime("%Y%m%d")
        names = [f"v{tag}", f"c{tag}"][: len(bands)]
        layers.append(collection.filterDate(start, start.advance(1, "day")).merge(template).mean().rename(names))
    image = ee.Image.cat([*layers, ee.Image.constant(1).rename("total")])
    buffers = ee.FeatureCollection(
        [ee.Feature(ee.Geometry.Point([u.lon, u.lat]).buffer(radius_km * 1000), {"unit_id": u.id}) for u in units]
    )
    # Unweighted: a pixel counts when its centre is inside the buffer, as in `buffer_stats`. The weighted
    # default also takes the pixels the circle only touches, which lowers the mean over a plume by ~7 %.
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True).unweighted()
    table = image.reduceRegions(buffers, reducer, spec["scale_m"]).map(lambda f: f.setGeometry(None))
    return table_from_features(retry(table.getInfo)["features"], days)


def get_buffer_timeseries(units: Sequence[Any], start: date, end: date, product: str, radius_km: float) -> pd.DataFrame:
    """Daily buffer statistics per watch unit (plan §0.6): unit_id, date, mean, n_valid, n_total, cloud_mean.

    `units` have `id`, `lon` and `lat`; `product` is a key of `products` in sources.yaml. One Earth
    Engine request per calendar quarter, whatever the number of units and days, cached as parquet.
    """
    spec = _sources()["products"].get(product)
    if spec is None:
        raise DataUnavailable(f"product '{product}' was not confirmed by the spike (config/sources.yaml)")
    if any(u.id is None for u in units):
        raise ValueError("every unit needs an id")
    if not units or start > end:
        return pd.DataFrame(columns=TS_COLUMNS)
    if data_mode() == "fixture":
        ds = _open_fixture(f"{product}.nc").sel(time=slice(start.isoformat(), end.isoformat()))
        return buffer_stats(ds, spec["variable"], units, radius_km)

    unit_key = [[u.id, u.lon, u.lat] for u in units]
    frames = [
        cached(
            "buffer_ts",
            [product, f"{radius_km}km", first, last, unit_key],
            "parquet",
            lambda first=first, last=last: _fetch_buffer_chunk(units, days_between(first, last), spec, radius_km),
            data_end=last,
        )
        for first, last in quarter_chunks(start, end)
    ]
    table = pd.concat(frames, ignore_index=True).sort_values(["unit_id", "date"], ignore_index=True)[TS_COLUMNS]
    return table.astype({"date": "datetime64[ns]"})  # the same type whether fetched or read from parquet


# --- live smoke check -----------------------------------------------------------------------------


def smoke() -> None:
    """Small live requests through every kind of call. Prints what came back; a check that fails is
    reported and the others still run."""
    from app.schemas import WatchUnit

    if data_mode() != "live":
        raise SystemExit("the smoke check talks to Earth Engine: run it with DATA_MODE=live")
    settings = get_settings()
    west, south, east, north = settings.config.region.bbox
    lon, lat = (west + east) / 2, (south + north) / 2
    aoi = (lon - 0.2, lat - 0.2, lon + 0.2, lat + 0.2)
    end = datetime.now(UTC).date() - timedelta(days=20)
    start = end - timedelta(days=2)
    box = [[aoi[0], aoi[1]], [aoi[2], aoi[1]], [aoi[2], aoi[3]], [aoi[0], aoi[3]], [aoi[0], aoi[1]]]

    def grid(ds: xr.Dataset) -> str:
        return f"{dict(ds.sizes)} valid share {float(ds.valid.mean()):.2f} ({ds.attrs['ee_id']})"

    def burned() -> str:
        ds = get_burned_area(aoi, start - timedelta(days=200), start - timedelta(days=140))
        return f"{dict(ds.sizes)} burned cells {int(ds['burn_date'].notnull().sum())}"

    def ndvi() -> str:
        ds = get_ndvi((lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05), end)["ndvi"]
        return f"{dict(ds.sizes)} median {float(ds.median()):.2f}"

    def chip() -> str:
        found = get_s2_chip((lon, lat), end)
        return f"no scene near {end} (cloud)" if found is None else f"acquired {found.attrs['acquired_at']}"

    def buffers() -> str:
        rng = np.random.default_rng(0)
        units = [
            WatchUnit(
                id=i, kind="facility", name=f"smoke {i}", lon=rng.uniform(west, east), lat=rng.uniform(south, north)
            )
            for i in range(20)
        ]
        quarter_end = date(end.year, (end.month - 1) // 3 * 3 + 1, 1) - timedelta(days=1)
        (quarter,) = quarter_chunks(date(quarter_end.year, quarter_end.month - 2, 1), quarter_end)
        started = datetime.now(UTC)
        table = get_buffer_timeseries(units, *quarter, "no2", settings.config.detect["local_radius_km"])
        seconds = (datetime.now(UTC) - started).total_seconds()
        return (
            f"{len(table)} rows for {table.unit_id.nunique()} units, {quarter[0]} to {quarter[1]}, "
            f"{int((table.n_valid > 0).sum())} unit-days with data, one request, {seconds:.1f} s"
        )

    checks = {
        "no2": lambda: grid(get_no2(aoi, start, end)),
        "so2": lambda: grid(get_so2(aoi, start, end)),
        "aer_ai": lambda: grid(get_aerosol_index(aoi, start, end)),
        "ch4": lambda: grid(get_ch4(aoi, start)),
        "worldcover": lambda: f"classes {sorted(np.unique(get_worldcover(aoi)['landcover'].values).tolist())[:12]}",
        "ndvi": ndvi,
        "burned": burned,
        "population": lambda: f"{get_population({'type': 'Polygon', 'coordinates': [box]}):,.0f} in a 0.4 degree box",
        "s2 chip": chip,
        "tile url": lambda: get_tile_url("no2", end)[:80] + "...",
        "buffer ts": buffers,
    }
    failed = []
    for name, check in checks.items():
        try:
            print(f"{name:11s}{check()}")
        except Exception as exc:
            failed.append(name)
            print(f"{name:11s}FAILED: {str(exc)[:300]}")
    if failed:
        raise SystemExit(f"{len(failed)} of {len(checks)} checks failed: {', '.join(failed)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="run small live requests and print the results")
    if parser.parse_args().smoke:
        smoke()
    else:
        parser.print_help()
