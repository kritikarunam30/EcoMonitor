"""Live acceptance of the data clients (plan Phase 2, "Done when"). Needs the Phase 0 keys in .env.

RUN_LIVE=1 python -m pytest -m live tests/live/test_live_clients.py
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.clients import ee_client
from app.clients.wind import get_wind
from app.schemas import WatchUnit
from app.settings import get_settings

pytestmark = pytest.mark.live


def test_one_quarter_for_20_units_is_one_request(live_cache, monkeypatch):
    requests = []
    fetch = ee_client._fetch_buffer_chunk
    monkeypatch.setattr(ee_client, "_fetch_buffer_chunk", lambda *a: requests.append(1) or fetch(*a))
    west, south, east, north = get_settings().config.region.bbox
    rng = np.random.default_rng(0)
    units = [
        WatchUnit(id=i, kind="facility", name=str(i), lon=rng.uniform(west, east), lat=rng.uniform(south, north))
        for i in range(20)
    ]
    table = ee_client.get_buffer_timeseries(units, date(2026, 1, 1), date(2026, 3, 31), "no2", 5)
    assert len(requests) == 1 and len(table) == 20 * 90
    assert (table.n_total > 50).all() and (table.n_valid > 0).mean() > 0.5


def test_live_buffer_means_match_the_recorded_slice(live_cache, monkeypatch):
    """The live table (one reduceRegions) and the statistic computed from the recorded grid agree."""
    units = [
        WatchUnit(id=1, kind="cluster", name="Vindhyachal", lon=82.674, lat=24.105),
        WatchUnit(id=2, kind="facility", name="Obra", lon=82.983, lat=24.452),
    ]
    start, end = date(2025, 12, 1), date(2025, 12, 10)
    live = ee_client.get_buffer_timeseries(units, start, end, "no2", 5)
    monkeypatch.setattr(get_settings(), "data_mode", "fixture")
    recorded = ee_client.get_buffer_timeseries(units, start, end, "no2", 5)
    both = live.merge(recorded, on=["unit_id", "date"], suffixes=("_live", "_recorded")).dropna()
    assert len(both) >= 18
    assert ((both.mean_live / both.mean_recorded - 1).abs() < 0.03).all()
    assert ((both.n_total_live - both.n_total_recorded).abs() <= 3).all()


def test_live_wind_chain_answers_history_at_100m(live_cache):
    times = pd.date_range("2026-01-10 08:00", periods=5, freq="D")
    wind = get_wind([(82.674, 24.105)], times)
    assert wind.attrs["source"] == "era5_100m_ee" and wind.attrs["level"] == "100m"
    assert np.isfinite(wind.speed.values).all() and (wind.speed.values < 30).all()
