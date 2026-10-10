"""Earth Engine client (plan Phase 2): every function in fixture mode, the batched buffer time
series, and the live code path with the Earth Engine call replaced. No network."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.clients import ee_client
from app.clients.base import DataUnavailable
from app.clients.slice_format import GRID_ATTRS, GRID_UNITS, make_grid_dataset
from app.geo.projection import local_aeqd
from app.schemas import WatchUnit
from app.settings import get_settings

AOI = (82.5, 23.9, 82.9, 24.3)  # about 40 km around the Singrauli plants
START, END = date(2025, 12, 1), date(2025, 12, 10)
VINDHYACHAL = (82.67408, 24.10477)
UNITS = [
    WatchUnit(id=1, kind="cluster", name="Vindhyachal complex", lon=82.674, lat=24.105),
    WatchUnit(id=2, kind="facility", name="Obra", lon=82.983, lat=24.452),
]


def _check_grid(ds: xr.Dataset, variable: str) -> None:
    """The §0.6 grid contract."""
    assert ds[variable].dims == ("time", "lat", "lon")
    assert ds[variable].attrs["units"] == GRID_UNITS[variable]
    assert all(ds.attrs.get(a) for a in GRID_ATTRS)
    assert ds.attrs["mode"] == "fixture"
    assert np.all(np.diff(ds.lat) > 0) and np.all(np.diff(ds.lon) > 0)
    assert ds["valid"].dtype == bool
    assert np.array_equal(ds["valid"].values, ~np.isnan(ds[variable].values)), "missing data is NaN, never 0"


# --- fixture mode ---------------------------------------------------------------------------------


def test_get_no2_returns_the_real_slice_clipped_to_the_aoi_and_dates():
    ds = ee_client.get_no2(AOI, START, END)
    _check_grid(ds, "no2")
    assert ds.sizes == {"time": 10, "lat": 40, "lon": 40}
    assert pd.DatetimeIndex(ds.time.values)[0] == pd.Timestamp("2025-12-01 08:00")
    assert AOI[0] <= ds.lon.min() and ds.lon.max() <= AOI[2] and AOI[1] <= ds.lat.min() and ds.lat.max() <= AOI[3]
    assert "cloud_fraction" in ds and 0 <= float(ds.cloud_fraction.min()) <= float(ds.cloud_fraction.max()) <= 1
    assert ds.attrs["ee_id"] == get_settings().sources["products"]["no2"]["id"]
    assert 1e-5 < float(ds.no2.median()) < 1e-3, "a tropospheric NO2 column in mol/m²"


def test_get_so2_and_aerosol_index():
    so2 = ee_client.get_so2(AOI, START, END)
    _check_grid(so2, "so2")
    assert set(so2.data_vars) == {"so2", "valid"}
    aer = ee_client.get_aerosol_index(AOI, START, END)
    _check_grid(aer, "aer_ai")
    assert set(aer.data_vars) == {"aer_ai", "valid"}


def test_dates_outside_the_slice_give_an_empty_grid_not_an_error():
    assert ee_client.get_no2(AOI, date(2024, 1, 1), date(2024, 1, 5)).sizes["time"] == 0


def test_near_real_time_products_have_no_fixture():
    with pytest.raises(DataUnavailable, match="no2_nrti.nc"):
        ee_client.get_no2(AOI, START, END, stream="nrti")


def test_get_ch4_is_monthly():
    ds = ee_client.get_ch4(AOI, "2025-12")
    _check_grid(ds, "ch4")
    assert ds.sizes["time"] == 1 and pd.Timestamp(ds.time.values[0]) == pd.Timestamp("2025-12-01")
    xr.testing.assert_identical(ds, ee_client.get_ch4(AOI, date(2025, 12, 17)))
    assert 1700 < float(ds.ch4.mean()) < 2100


def test_land_cover_burned_area_and_population():
    cover = ee_client.get_worldcover(AOI)
    assert cover["landcover"].dims == ("lat", "lon") and cover.sizes["lat"] > 1
    burned = ee_client.get_burned_area(AOI, date(2025, 11, 10), date(2026, 1, 3))
    assert burned["burn_date"].dims == ("time", "lat", "lon")
    assert list(pd.DatetimeIndex(burned.time.values).month) == [11, 12, 1]
    november, december = ee_client.get_burned_area((82.0, 23.5, 83.5, 24.8), date(2025, 11, 1), END)["burn_date"].values
    assert 305 <= np.nanmin(november) <= np.nanmax(november) <= 334, "a day of year in November"
    assert np.isnan(november).any() and np.isnan(december).all(), "cells that did not burn are NaN"

    box = [[82.5, 23.9], [82.9, 23.9], [82.9, 24.3], [82.5, 24.3], [82.5, 23.9]]
    whole = ee_client.get_population({"type": "Polygon", "coordinates": [box]})
    half = [[82.5, 23.9], [82.7, 23.9], [82.7, 24.3], [82.5, 24.3], [82.5, 23.9]]
    part = ee_client.get_population({"type": "Polygon", "coordinates": [half]})
    assert 0 < part < whole
    assert part == pytest.approx(whole / 2, rel=0.3)


def test_get_ndvi_from_the_recorded_chips():
    ds = ee_client.get_ndvi((82.66, 24.09, 82.69, 24.12), date(2026, 1, 14))
    assert ds["ndvi"].dims == ("lat", "lon")
    assert np.all(np.diff(ds.lat) > 0)
    assert float(ds.ndvi.min()) >= -1 and float(ds.ndvi.max()) <= 1
    assert ds.attrs["ee_id"] == get_settings().sources["s2"]["id"]


def test_get_s2_chip_has_six_bands_a_cloud_mask_and_the_acquisition_time():
    chip = ee_client.get_s2_chip(VINDHYACHAL, date(2026, 1, 15))
    s2 = get_settings().sources["s2"]
    assert chip["chip"].shape == (6, 128, 128) and list(chip.band.values) == s2["chip_bands"]
    assert chip["scl"].shape == (128, 128) and chip["cloud_mask"].dtype == bool
    assert pd.Timestamp(chip.attrs["acquired_at"]) == pd.Timestamp("2026-01-14T05:12:10.216Z")
    assert chip.lat[0] > chip.lat[-1], "row 0 is the northern edge, as an image"

    small = ee_client.get_s2_chip(VINDHYACHAL, date(2026, 1, 15), size_px=64)
    assert small["chip"].shape == (6, 64, 64)
    assert abs(float(small.lat.mean()) - VINDHYACHAL[1]) < 0.001


def test_get_s2_chip_returns_none_without_a_scene():
    assert ee_client.get_s2_chip(VINDHYACHAL, date(2026, 2, 1)) is None, "no scene within the search window"
    assert ee_client.get_s2_chip((83.0, 24.1), date(2026, 1, 15)) is None, "the point is outside the chip"


def test_tile_url_in_fixture_mode_cannot_be_mistaken_for_a_real_one():
    url = ee_client.get_tile_url("no2", date(2026, 1, 1))
    assert url.startswith("fixture://") and url.endswith("{z}/{x}/{y}.png")
    with pytest.raises(ValueError, match="unknown layer"):
        ee_client.get_tile_url("ozone", date(2026, 1, 1))


def test_every_layer_has_a_confirmed_product():
    settings = get_settings()
    assert set(settings.config.layers) <= set(settings.sources["products"])


# --- buffer time series ---------------------------------------------------------------------------


def test_buffer_timeseries_from_the_real_slice():
    table = ee_client.get_buffer_timeseries(UNITS, START, END, "no2", radius_km=5)
    assert list(table.columns) == ee_client.TS_COLUMNS
    assert len(table) == 2 * 10 and set(table.unit_id) == {1, 2}
    assert table.date.min() == pd.Timestamp("2025-12-01") and table.date.max() == pd.Timestamp("2025-12-10")
    assert (table.n_valid <= table.n_total).all() and (table.n_total > 50).all(), "a 5 km buffer holds ~75 cells"
    assert table.cloud_mean.between(0, 1).all()
    empty = table[table.n_valid == 0]
    assert empty["mean"].isna().all(), "a day without valid pixels has no mean"
    plants, obra = table[table.unit_id == 1], table[table.unit_id == 2]
    assert plants["mean"].median() > obra["mean"].median(), "the 10 GW cluster is above the single plant"

    so2 = ee_client.get_buffer_timeseries(UNITS, START, END, "so2", radius_km=5)
    assert so2.cloud_mean.isna().all(), "the SO2 slice has no cloud band"


def test_buffer_stats_counts_and_averages_only_the_cells_inside_the_radius():
    lats = np.round(np.arange(24.0, 24.2, 0.01), 4)
    lons = np.round(np.arange(82.5, 82.7, 0.01), 4)
    days = [date(2026, 1, 1), date(2026, 1, 2)]
    unit = WatchUnit(id=7, kind="facility", name="x", lon=82.6, lat=24.1)
    lon, lat = np.meshgrid(lons, lats)
    x, y = local_aeqd(unit.lon, unit.lat)[0].transform(lon, lat)
    inside = np.hypot(x, y) <= 3000

    field = np.full((2, len(lats), len(lons)), 1.0)
    field[:, inside] = 5.0
    field[1, inside] = np.nan  # the second day is cloudy over the unit
    hole = np.argwhere(inside)[0]
    field[0, hole[0], hole[1]] = np.nan
    cloud = np.full_like(field, 0.2)
    ds = make_grid_dataset(
        {"no2": field, "cloud_fraction": cloud}, days, lats, lons, primary="no2", source="t", ee_id="t", mode="t"
    )

    table = ee_client.buffer_stats(ds, "no2", [unit], radius_km=3)
    first, second = table.iloc[0], table.iloc[1]
    assert first.unit_id == 7 and first.n_total == inside.sum() and first.n_valid == inside.sum() - 1
    assert first["mean"] == pytest.approx(5.0) and first.cloud_mean == pytest.approx(0.2)
    assert second.n_valid == 0 and np.isnan(second["mean"]) and second.n_total == inside.sum()


def test_buffer_timeseries_edge_cases():
    assert ee_client.get_buffer_timeseries([], START, END, "no2", 5).empty
    with pytest.raises(DataUnavailable, match="not confirmed by the spike"):
        ee_client.get_buffer_timeseries(UNITS, START, END, "ozone", 5)
    with pytest.raises(ValueError, match="needs an id"):
        ee_client.get_buffer_timeseries(
            [WatchUnit(kind="facility", name="new", lon=82.6, lat=24.1)], START, END, "no2", 5
        )


def test_quarter_chunks_split_at_calendar_quarters():
    chunks = ee_client.quarter_chunks(date(2025, 11, 15), date(2026, 4, 2))
    assert chunks == [
        (date(2025, 11, 15), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 3, 31)),
        (date(2026, 4, 1), date(2026, 4, 2)),
    ]
    assert ee_client.quarter_chunks(date(2026, 7, 1), date(2026, 9, 30)) == [(date(2026, 7, 1), date(2026, 9, 30))]
    assert ee_client.quarter_chunks(date(2026, 2, 1), date(2026, 1, 1)) == []


def test_table_from_features_reads_the_stacked_band_properties():
    days = [date(2026, 1, 1), date(2026, 1, 2)]
    features = [
        {
            "properties": {
                "unit_id": 1,
                "total_count": 78,
                "v20260101_mean": 2.5e-4,
                "v20260101_count": 70,
                "c20260101_mean": 0.1,
                "v20260102_mean": None,  # fully masked day: Earth Engine sends null, or leaves the key out
                "v20260102_count": 0,
            }
        }
    ]
    table = ee_client.table_from_features(features, days)
    assert list(table.columns) == ee_client.TS_COLUMNS
    assert table.iloc[0].to_dict() == {
        "unit_id": 1,
        "date": pd.Timestamp("2026-01-01"),
        "mean": 2.5e-4,
        "n_valid": 70,
        "n_total": 78,
        "cloud_mean": 0.1,
    }
    assert table.iloc[1].n_valid == 0 and np.isnan(table.iloc[1]["mean"]) and np.isnan(table.iloc[1].cloud_mean)
    assert table["mean"].dtype == float


# --- live code path with the Earth Engine call replaced -------------------------------------------


def test_live_buffer_timeseries_makes_one_request_per_quarter_and_caches_it(live_cache, monkeypatch):
    requests = []

    def fake_chunk(units, days, spec, radius_km):
        requests.append((len(units), days[0], days[-1], spec["id"], radius_km))
        return pd.DataFrame(
            [
                {
                    "unit_id": u.id,
                    "date": pd.Timestamp(d),
                    "mean": 1e-4,
                    "n_valid": 70,
                    "n_total": 78,
                    "cloud_mean": 0.1,
                }
                for u in units
                for d in days
            ]
        )

    monkeypatch.setattr(ee_client, "_fetch_buffer_chunk", fake_chunk)
    units = [WatchUnit(id=i, kind="facility", name=str(i), lon=82.2 + 0.05 * i, lat=24.0) for i in range(20)]
    start, end = date(2025, 10, 1), date(2026, 3, 31)

    table = ee_client.get_buffer_timeseries(units, start, end, "no2", 5)
    no2_id = get_settings().sources["products"]["no2"]["id"]
    assert requests == [
        (20, date(2025, 10, 1), date(2025, 12, 31), no2_id, 5),
        (20, date(2026, 1, 1), date(2026, 3, 31), no2_id, 5),
    ], "182 days x 20 units must be two requests, not 182 or 3640"
    assert len(table) == 20 * 182 and list(table.columns) == ee_client.TS_COLUMNS
    assert table.equals(table.sort_values(["unit_id", "date"], ignore_index=True))

    again = ee_client.get_buffer_timeseries(units, start, end, "no2", 5)
    assert len(requests) == 2, "the second call is served from parquet"
    pd.testing.assert_frame_equal(again, table)
    assert len(list((live_cache / "buffer_ts").glob("*.parquet"))) == 2

    ee_client.get_buffer_timeseries(units[:19], start, end, "no2", 5)
    assert len(requests) == 4, "another set of units is another cache entry"


def test_live_grid_is_built_from_one_batched_fetch_and_cached(live_cache, monkeypatch):
    calls = []

    def fake_daily_grids(collection_id, bands, bbox, days, step, chunk_days=20):
        calls.append((collection_id, tuple(bands), len(days), step, chunk_days))
        _, lats, lons = ee_client.grid_spec(bbox, step)
        rng = np.random.default_rng(0)
        grids = {b: rng.random((len(days), len(lats), len(lons))).astype("float32") * 1e-4 for b in bands}
        grids[bands[0]][0, :2] = np.nan
        return grids, lats, lons

    monkeypatch.setattr(ee_client, "daily_grids", fake_daily_grids)
    spec = get_settings().sources["products"]["no2"]
    first = ee_client.get_no2(AOI, date(2025, 1, 1), date(2025, 1, 30))
    assert calls == [
        (spec["id"], (spec["band"], spec["cloud_band"]), 30, 0.01, get_settings().config.data["ee_chunk_days"])
    ]
    assert first.attrs["mode"] == "live" and first.attrs["ee_id"] == spec["id"]
    assert first.sizes == {"time": 30, "lat": 40, "lon": 40}
    assert not first["valid"].values[0, :2].any() and np.isnan(first["no2"].values[0, :2]).all()

    second = ee_client.get_no2(AOI, date(2025, 1, 1), date(2025, 1, 30))
    assert len(calls) == 1
    xr.testing.assert_identical(second, first)


def test_grid_spec_cells_are_centred_and_latitudes_ascend():
    spec, lats, lons = ee_client.grid_spec((82.0, 24.0, 82.05, 24.03), 0.01)
    assert spec["dimensions"] == {"width": 5, "height": 3}
    assert spec["affineTransform"]["translateY"] == 24.03 and spec["affineTransform"]["scaleY"] == -0.01
    assert np.allclose(lats, [24.005, 24.015, 24.025]) and np.allclose(lons[[0, -1]], [82.005, 82.045])
    assert ee_client.step_deg(get_settings().sources["products"]["no2"]["scale_m"]) == 0.01


def test_snap_bbox_widens_to_whole_cells_of_the_product_grid():
    assert ee_client.snap_bbox((82.16551629, 23.58923, 83.34604, 24.67265), 0.01) == (82.16, 23.58, 83.35, 24.68)
    assert ee_client.snap_bbox((82.5, 23.9, 82.9, 24.3), 0.01) == (82.5, 23.9, 82.9, 24.3), "aligned boxes stay"
    _, lats, lons = ee_client.grid_spec(ee_client.snap_bbox((82.1655, 23.5892, 82.2, 23.62), 0.01), 0.01)
    assert np.allclose(lons, [82.165, 82.175, 82.185, 82.195]) and np.allclose(lats, [23.585, 23.595, 23.605, 23.615])


@pytest.mark.parametrize("name", ["no2.nc", "so2.nc", "aer_ai.nc"])
def test_recorded_grids_are_labelled_with_the_centres_of_the_product_pixels(name):
    """Sentinel-5P Level 3 has 0.01° pixels with edges on multiples of 0.01°, so centres end in 5."""
    ds = ee_client._open_fixture(name)
    for axis in ("lat", "lon"):
        assert np.allclose((ds[axis].values * 100) % 1, 0.5, atol=1e-6), f"{name}: {axis} is off the pixel centres"


def test_stream_for_follows_gate_g1():
    today = date(2026, 10, 10)
    assert ee_client.stream_for("no2", date(2026, 10, 9), today) == "nrti", "offline NO2 is about 9 days late"
    assert ee_client.stream_for("no2", date(2026, 9, 25), today) == "offl"
    assert ee_client.stream_for("so2", date(2026, 10, 6), today) == "offl", "offline SO2 is about 3 days late"
    assert ee_client.stream_for("ch4", date(2026, 10, 9), today) == "offl", "no near-real-time CH4 in the spike"


def test_live_mode_without_credentials_says_what_is_missing(live_cache, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ee_project", "")
    monkeypatch.setattr(ee_client, "_initialised", False)
    with pytest.raises(DataUnavailable, match="EE_PROJECT"):
        ee_client.get_so2(AOI, date(2025, 1, 1), date(2025, 1, 2))
