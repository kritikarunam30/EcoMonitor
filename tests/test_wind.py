"""Wind provider chain (plan §0.6 and Phase 2): fixture mode, fall-through, honesty about the level,
and the CDS provider with the download replaced. No network."""

from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.clients import cds, wind
from app.clients.base import DataUnavailable
from app.clients.wind import Provider, get_wind, match_samples, utc_index
from app.settings import REPO_ROOT, get_settings

VINDHYACHAL = (82.67408, 24.10477)
OBRA = (82.98291, 24.45204)
RECORDED = pd.read_csv(REPO_ROOT / "tests" / "fixtures" / "real_singrauli" / "wind.csv")


def _provider(name, level, answers):
    """A provider that knows the wind (u = `answers[time]`, v = 0) for some times only."""
    seen = []

    def fetch(points, times):
        seen.append(list(times))
        u = np.array([[answers.get(t, np.nan)] * len(points) for t in times], dtype=float).reshape(
            len(times), len(points)
        )
        return u, np.where(np.isnan(u), np.nan, 0.0), np.where(np.isnan(u[:, 0]), np.nan, 0.0)

    return Provider(name, level, fetch), seen


# --- fixture mode ---------------------------------------------------------------------------------


def test_recorded_era5_wind_at_100m_answers_inside_the_slice():
    result = get_wind([VINDHYACHAL, OBRA], [datetime(2025, 12, 1, 8, tzinfo=UTC), datetime(2025, 12, 2, 8, tzinfo=UTC)])
    assert result["u"].dims == ("time", "point") and result.sizes == {"time": 2, "point": 2}
    assert result.attrs["source"] == "era5_100m_ee" and result.attrs["level"] == "100m"
    assert result.attrs["uncertainty_frac"] == get_settings().config.wind["uncertainty_frac"]["era5_100m_ee"]
    assert list(result["source"].values) == ["era5_100m_ee"] * 2 and list(result["level"].values) == ["100m"] * 2
    assert (result["time_offset_h"] == 0).all()

    row = RECORDED[(RECORDED.time == "2025-12-01T08:00:00+00:00") & (RECORDED.lon.round(4) == 82.6741)].iloc[0]
    assert float(result.u[0, 0]) == pytest.approx(row.u) and float(result.v[0, 0]) == pytest.approx(row.v)
    assert float(result.speed[0, 0]) == pytest.approx(row.speed, abs=1e-6)
    assert float(result.dir_from_deg[0, 0]) == pytest.approx(row.dir_from_deg, abs=1e-6)
    assert np.allclose(result.lon, [VINDHYACHAL[0], OBRA[0]]) and result["time"].attrs["time_zone"] == "UTC"


def test_chain_falls_through_to_gfs_and_says_it_is_a_10m_wind():
    """After the recorded slice only the synthetic GFS fixture has data: 10 m, from the 06:00 analysis."""
    times = pd.date_range("2026-02-27 08:00", "2026-03-07 08:00", freq="D")
    result = get_wind([VINDHYACHAL], times)
    source = list(result["source"].values)
    assert source == ["era5_100m_ee"] * 2 + ["gfs_ee"] * 5 + [""] * 2
    assert list(result["level"].values) == ["100m"] * 2 + ["10m"] * 5 + [""] * 2
    cfg = get_settings().config.wind
    assert (
        list(result["uncertainty_frac"].values[:7])
        == [cfg["uncertainty_frac"]["era5_100m_ee"]] * 2 + [cfg["uncertainty_frac"]["gfs_ee"]] * 5
    )
    assert list(result["time_offset_h"].values[2:7]) == [2.0] * 5, "08:00 is answered by the 06:00 analysis"
    assert result.attrs["source"] == "era5_100m_ee,gfs_ee" and result.attrs["level"] == "100m,10m"
    assert result.attrs["uncertainty_frac"] == cfg["uncertainty_frac"]["gfs_ee"], "the largest one used"
    assert result.attrs["chain"] == ",".join(cfg["chain"])
    assert np.isnan(result.speed.values[7:]).all() and np.isfinite(result.speed.values[:7]).all()


def test_no_provider_gives_nan_and_no_source():
    result = get_wind([VINDHYACHAL], ["2024-01-01T08:00Z"])
    assert np.isnan(result.u.values).all() and result["source"].values[0] == ""
    assert (
        result.attrs["source"] == "none"
        and result.attrs["level"] == "none"
        and np.isnan(result.attrs["uncertainty_frac"])
    )


def test_a_point_far_from_every_recorded_point_is_not_answered():
    result = get_wind([(85.0, 24.1)], ["2025-12-01T08:00Z"])
    assert result["source"].values[0] == "" and np.isnan(result.speed.values).all()


def test_times_may_be_aware_naive_or_text_and_are_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    index = utc_index([datetime(2025, 12, 1, 13, 30, tzinfo=ist), datetime(2025, 12, 1, 8), "2025-12-01T08:00:00Z"])
    assert list(index) == [pd.Timestamp("2025-12-01 08:00")] * 3 and index.tz is None


# --- chain behaviour with stand-in providers ------------------------------------------------------


def test_each_provider_is_asked_only_for_the_times_still_open():
    t = utc_index(["2026-01-01T08:00Z", "2026-01-02T08:00Z", "2026-01-03T08:00Z"])
    first, first_seen = _provider("era5_100m_ee", "100m", {t[0]: 3.0})
    second, second_seen = _provider("gfs_ee", "10m", {t[1]: 5.0, t[0]: 99.0})
    third, third_seen = _provider("era5_land_10m_ee", "10m", {})

    result = get_wind([VINDHYACHAL], t, providers=[first, second, third])
    assert first_seen == [list(t)] and second_seen == [[t[1], t[2]]] and third_seen == [[t[2]]]
    assert list(result.u.values[:, 0][:2]) == [3.0, 5.0] and np.isnan(result.u.values[2, 0])
    assert list(result["source"].values) == ["era5_100m_ee", "gfs_ee", ""]
    assert float(result.dir_from_deg[0, 0]) == 270.0, "u > 0 blows from the west"


def test_a_failing_provider_is_skipped_and_named_in_the_notes():
    t = utc_index(["2026-01-01T08:00Z"])

    def down(points, times):
        raise RuntimeError("CDS queue: request failed")

    backup, _ = _provider("gfs_ee", "10m", {t[0]: 4.0})
    result = get_wind([VINDHYACHAL], t, providers=[Provider("cds_era5_100m", "100m", down), backup])
    assert result["source"].values[0] == "gfs_ee" and result.attrs["level"] == "10m"
    assert "cds_era5_100m: CDS queue: request failed" in result.attrs["notes"]


def test_a_time_counts_only_when_every_point_has_wind():
    t = utc_index(["2026-01-01T08:00Z"])

    def one_point_only(points, times):
        u = np.array([[3.0, np.nan]])
        return u, u * 0, np.zeros(1)

    backup, _ = _provider("gfs_ee", "10m", {t[0]: 4.0})
    result = get_wind([VINDHYACHAL, OBRA], t, providers=[Provider("era5_100m_ee", "100m", one_point_only), backup])
    assert result["source"].values[0] == "gfs_ee" and list(result.u.values[0]) == [4.0, 4.0], "levels are never mixed"


def test_unknown_provider_in_the_chain_is_an_error(monkeypatch):
    monkeypatch.setitem(get_settings().config.wind, "chain", ["made_up_provider"])
    with pytest.raises(ValueError, match="not confirmed by the spike"):
        get_wind([VINDHYACHAL], ["2025-12-01T08:00Z"])


def test_match_samples_uses_the_nearest_site_and_respects_the_time_tolerance():
    samples = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-03-01 06:00", "2026-03-01 12:00", "2026-03-01 06:00"]),
            "lon": [82.625, 82.625, 83.125],
            "lat": [24.125, 24.125, 24.375],
            "u": [1.0, 2.0, 7.0],
            "v": [0.0, 0.0, 0.0],
        }
    )
    times = utc_index(["2026-03-01T08:00Z", "2026-03-01T11:00Z", "2026-03-02T08:00Z"])
    u, _, offset = match_samples(samples, [VINDHYACHAL, OBRA], times, max_km=28, max_offset_h=3)
    assert u[0, 0] == 1.0 and u[1, 0] == 2.0 and np.isnan(u[2, 0])
    assert u[0, 1] == 7.0 and np.isnan(u[1, 1]), "the second site has no sample near 11:00"
    assert offset[0] == 2.0 and offset[1] == 1.0 and np.isnan(offset[2])

    exact, _, _ = match_samples(samples, [VINDHYACHAL], times, max_km=28, max_offset_h=0)
    assert np.isnan(exact).all(), "without a tolerance only the exact hour counts"
    near, _, _ = match_samples(samples, [VINDHYACHAL], times, max_km=2, max_offset_h=3)
    assert np.isnan(near).all(), "the nearest cell centre is farther than max_km"


# --- live code path with the service call replaced ------------------------------------------------


def _cds_file(request):
    """A file shaped like the one the spike downloaded: valid_time, descending latitude, u100, v100."""
    north, west, south, east = request["area"]
    times = pd.DatetimeIndex(
        [
            pd.Timestamp(f"{request['year'][0]}-{request['month'][0]}-{day} {hour}")
            for day in request["day"]
            for hour in request["time"]
        ]
    )
    lats = np.arange(north, south - 0.01, -0.25)
    lons = np.arange(west, east + 0.01, 0.25)
    shape = (len(times), len(lats), len(lons))
    u = np.broadcast_to(lons[None, None, :], shape) / 10  # the value tells which cell was read
    v = np.broadcast_to(lats[None, :, None], shape) / 10
    return xr.Dataset(
        {"u100": (("valid_time", "latitude", "longitude"), u), "v100": (("valid_time", "latitude", "longitude"), v)},
        coords={
            "valid_time": times,
            "latitude": lats,
            "longitude": lons,
            "number": 0,
            "expver": ("valid_time", ["1"] * len(times)),
        },
    )


def test_cds_provider_downloads_one_file_per_month_and_caches_it(live_cache, monkeypatch):
    requests = []

    def fake_download(dataset, request, target):
        requests.append((dataset, request))
        _cds_file(request).to_netcdf(target)

    monkeypatch.setattr(cds, "_download", fake_download)
    monkeypatch.setitem(get_settings().config.wind, "chain", ["cds_era5_100m"])
    times = pd.date_range("2025-01-30 08:00", "2025-02-02 08:00", freq="D")

    result = get_wind([VINDHYACHAL, OBRA], times)
    spec = get_settings().sources["wind"]["cds_era5_100m"]
    assert [(d, r["year"], r["month"], r["day"], r["time"]) for d, r in requests] == [
        (spec["dataset"], ["2025"], ["01"], ["30", "31"], ["08:00"]),
        (spec["dataset"], ["2025"], ["02"], ["01", "02"], ["08:00"]),
    ], "one request per month, not per day"
    request = requests[0][1]
    assert request["variable"] == spec["request"]["variable"] and request["data_format"] == "netcdf"
    north, west, south, east = request["area"]
    assert west <= VINDHYACHAL[0] and OBRA[0] <= east and south <= VINDHYACHAL[1] and OBRA[1] <= north

    assert result.attrs["source"] == "cds_era5_100m" and result.attrs["level"] == "100m"
    assert np.allclose(result.u.values[:, 0], 8.275) and np.allclose(result.v.values[:, 0], 2.4), "nearest ERA5 cell"
    assert np.allclose(result.u.values[:, 1], 8.3) and np.allclose(result.v.values[:, 1], 2.45)

    again = get_wind([VINDHYACHAL, OBRA], times)
    assert len(requests) == 2, "the second call reads the cached NetCDF"
    xr.testing.assert_allclose(again.u, result.u)
    assert len(list((live_cache / "cds").glob("*.nc"))) == 2


def test_cds_normalise_gives_time_lat_lon_ascending():
    raw = _cds_file(
        {"year": ["2025"], "month": ["01"], "day": ["30"], "time": ["08:00"], "area": [24.75, 82.5, 24.0, 83.0]}
    )
    ds = cds.normalise(raw, "u100", "v100")
    assert ds["u"].dims == ("time", "lat", "lon") and set(ds.coords) == {"time", "lat", "lon"}
    assert np.all(np.diff(ds.lat) > 0)


def test_live_earth_engine_provider_caches_its_samples(live_cache, monkeypatch):
    calls = []

    def fake_samples(spec, points, times, max_offset_h):
        calls.append((spec["id"], spec["u_band"], len(points), len(times), max_offset_h))
        return pd.DataFrame(
            [{"time": t, "lon": lon, "lat": lat, "u": 2.0, "v": -2.0} for t in times for lon, lat in points]
        )

    monkeypatch.setattr(wind, "_ee_samples", fake_samples)
    times = pd.date_range("2025-01-01 08:00", periods=30, freq="D")
    first = get_wind([VINDHYACHAL, OBRA], times)
    era5 = get_settings().sources["wind"]["era5_100m_ee"]
    assert calls == [(era5["id"], era5["u_band"], 2, 30, 0)], "one batched request for 30 days and 2 points"
    assert first.attrs["source"] == "era5_100m_ee" and float(first.dir_from_deg[0, 0]) == 315.0

    get_wind([VINDHYACHAL, OBRA], times)
    assert len(calls) == 1 and len(list((live_cache / "wind").glob("*.parquet"))) == 1


def test_live_chain_without_any_access_reports_every_provider(live_cache, monkeypatch):
    def no_access(*args, **kwargs):
        raise DataUnavailable("not configured")

    monkeypatch.setattr(wind, "_ee_samples", no_access)
    monkeypatch.setattr(cds, "_download", no_access)
    result = get_wind([VINDHYACHAL], ["2025-01-01T08:00Z"])
    assert result.attrs["source"] == "none"
    assert all(name in result.attrs["notes"] for name in get_settings().config.wind["chain"])
