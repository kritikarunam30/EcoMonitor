"""Shared client plumbing (plan Phase 2): sources.yaml, cache, data modes, retries, the network guard."""

import json
import os
import socket
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import make_sources
from app.clients import base
from app.clients.base import DataUnavailable, cache_path, cached, fixture_path, fixture_paths, retry
from app.settings import REPO_ROOT, get_settings

REPORT = (REPO_ROOT / "docs" / "SPIKE_REPORT.md").read_text(encoding="utf-8")
FACTS = json.loads((REPO_ROOT / "docs" / "SPIKE_FACTS.json").read_text(encoding="utf-8"))
LONG_AGO = date(2025, 1, 31)


# --- sources.yaml ---------------------------------------------------------------------------------


def test_sources_yaml_is_what_the_generator_writes_from_the_spike():
    on_disk = (REPO_ROOT / "config" / "sources.yaml").read_text(encoding="utf-8")
    assert on_disk == make_sources.render(make_sources.build_sources(FACTS)), "run `make sources`"


def _walk(node, key=None):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)
    else:
        yield key, node


def test_every_asset_id_and_band_is_in_the_spike_report():
    sources = get_settings().sources
    checked = 0
    names = ("id", "band", "cloud_band", "u_band", "v_band", "chip_bands", "scl_band", "red_band", "nir_band")
    for key, value in _walk({k: v for k, v in sources.items() if k != "firms"}):
        if key in names and value is not None:
            assert str(value) in REPORT, f"{key}: {value} is not in docs/SPIKE_REPORT.md"
            checked += 1
    assert checked > 40
    for source in sources["firms"]:
        assert source in REPORT


def test_every_wind_provider_of_the_chain_has_a_source():
    settings = get_settings()
    assert set(settings.config.wind["chain"]) <= set(settings.sources["wind"])


def test_generator_refuses_a_band_the_spike_did_not_list():
    facts = json.loads(json.dumps(FACTS))
    facts["products"]["no2"]["band"] = "NO2_made_up"
    with pytest.raises(ValueError, match="NO2_made_up"):
        make_sources.build_sources(facts)
    facts = json.loads(json.dumps(FACTS))
    facts["collections"]["era5_hourly"]["bands"].remove("u_component_of_wind_100m")
    with pytest.raises(ValueError, match="100 m"):
        make_sources.build_sources(facts)


# --- fixtures and modes ---------------------------------------------------------------------------


def test_fixture_lookup_prefers_the_recorded_slice_and_falls_back_to_synthetic():
    assert fixture_path("no2.nc").parent.name == "real_singrauli"
    assert fixture_path("ch4.nc").parent.name == "synthetic"
    assert [p.parent.name for p in fixture_paths("wind.csv")] == ["real_singrauli", "synthetic"]
    with pytest.raises(DataUnavailable, match="no fixture"):
        fixture_path("no_such_file.nc")


def test_fixture_mode_never_reaches_a_fetch():
    with pytest.raises(DataUnavailable, match="DATA_MODE=live"):
        cached("ee", ["x"], "json", lambda: pytest.fail("fetch was called in fixture mode"))


def test_replay_mode_reads_the_cache_and_never_fetches(live_cache, monkeypatch):
    cached("demo", ["a"], "json", lambda: {"value": 1})
    monkeypatch.setattr(get_settings(), "data_mode", "replay")
    assert cached("demo", ["a"], "json", lambda: pytest.fail("fetch was called in replay mode")) == {"value": 1}
    with pytest.raises(DataUnavailable, match="replay"):
        cached("demo", ["b"], "json", lambda: {"value": 2})


# --- cache ----------------------------------------------------------------------------------------


def test_cache_path_is_under_the_cache_dir_and_keyed_by_every_part(live_cache):
    a = cache_path("ee", ["no2", [82.0, 23.6, 83.4, 24.8], date(2026, 1, 1)], "nc")
    b = cache_path("ee", ["no2", [82.0, 23.6, 83.4, 24.9], date(2026, 1, 1)], "nc")
    assert a.parent == live_cache / "ee" and a.suffix == ".nc"
    assert a.name.startswith("no2_2026-01-01_")
    assert a != b
    assert a == cache_path("ee", ["no2", (82.0, 23.6, 83.4, 24.8), date(2026, 1, 1)], "nc")


def test_cache_round_trip_for_each_format(live_cache):
    calls = []

    def once(value):
        def fetch():
            calls.append(1)
            return value

        return fetch

    grid = xr.Dataset(
        {"no2": (("time", "lat", "lon"), np.array([[[1e-4, np.nan]]], dtype="float32"))},
        coords={"time": pd.DatetimeIndex(["2026-01-01T08:00"]), "lat": [24.0], "lon": [82.0, 82.01]},
        attrs={"source": "earthengine", "mode": "live"},
    )
    grid["valid"] = grid["no2"].notnull()
    table = pd.DataFrame(
        {"unit_id": [1, 2], "date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "mean": [1.5, np.nan]}
    )

    for _ in range(2):
        got_grid = cached("ee", ["grid"], "nc", once(grid), data_end=LONG_AGO)
        got_table = cached("buffer_ts", ["table"], "parquet", once(table), data_end=LONG_AGO)
        got_json = cached("osm", ["json"], "json", once([{"a": 1}]))
    assert len(calls) == 3, "the second round must come from the cache"
    xr.testing.assert_identical(got_grid, grid)
    assert got_grid["valid"].dtype == bool
    pd.testing.assert_frame_equal(got_table, table)
    assert got_json == [{"a": 1}]
    assert sorted(p.suffix for p in live_cache.rglob("*") if p.is_file()) == [".json", ".nc", ".parquet"]


def test_recent_data_is_fetched_again_until_it_has_settled(live_cache):
    calls = []

    def fetch():
        calls.append(1)
        return {"n": len(calls)}

    recent = date.today() - timedelta(days=1)
    assert cached("ee", ["recent"], "json", fetch, data_end=recent) == {"n": 1}
    assert cached("ee", ["recent"], "json", fetch, data_end=recent) == {"n": 2}, "offline NO2 arrives ~9 days late"

    path = cache_path("ee", ["recent"], "json")
    assert not base.is_settled(path, recent)
    settle_days = get_settings().config.schedule["rerun_previous_days"]
    assert base.is_settled(path, date.today() - timedelta(days=settle_days + 1))
    old = time.time() - 86400 * 2
    os.utime(path, (old, old))
    assert not base.is_settled(path, date.today() - timedelta(days=settle_days + 1))


def test_a_failed_fetch_leaves_no_cache_file(live_cache):
    def boom():
        raise RuntimeError("Earth Engine: quota exceeded")

    with pytest.raises(RuntimeError, match="quota exceeded"):
        cached("ee", ["boom"], "json", boom)
    assert not list(live_cache.rglob("*.json*"))


# --- retries and the network guard ----------------------------------------------------------------


def test_retry_backs_off_on_quota_errors_and_surfaces_the_last_text(monkeypatch):
    sleeps = []
    monkeypatch.setattr(base.time, "sleep", sleeps.append)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("HTTP 429: Too many concurrent aggregations.")
        return "ok"

    assert retry(flaky) == "ok"
    assert len(attempts) == 3 and len(sleeps) == 2
    assert 2 <= sleeps[0] <= 3 and 4 <= sleeps[1] <= 5, "exponential backoff with up to 1 s of jitter"

    def always():
        raise RuntimeError("User memory limit exceeded; quota tier: community")

    with pytest.raises(RuntimeError, match="quota tier: community"):
        retry(always, tries=3)


def test_retry_does_not_repeat_other_errors(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: pytest.fail("slept"))
    attempts = []

    def wrong():
        attempts.append(1)
        raise ValueError("Band 'NO2' not found")

    with pytest.raises(ValueError):
        retry(wrong)
    assert len(attempts) == 1


def test_tests_cannot_open_network_connections():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(RuntimeError, match="network"):
        sock.connect(("192.0.2.1", 443))
