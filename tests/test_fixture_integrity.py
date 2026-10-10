"""Integrity of recorded fixture slices (plan Phase S, task 4).

The real Singrauli slice is checked as soon as it has been recorded and committed. Until then the
checker itself is tested on a small slice written with the same helpers that make_fixtures.py uses.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.clients.slice_format import (
    GRID_UNITS,
    WIND_COLUMNS,
    check_slice,
    make_grid_dataset,
    overpass_times,
    wind_dir_from_deg,
)
from app.settings import REPO_ROOT

REAL_SLICE = REPO_ROOT / "tests" / "fixtures" / "real_singrauli"
DAYS = [date(2026, 9, 1) + timedelta(days=i) for i in range(6)]
LATS = np.round(np.arange(24.0, 24.2, 0.01), 4)
LONS = np.round(np.arange(82.5, 82.7, 0.01), 4)
BBOX = [82.5, 24.0, 82.7, 24.2]


def _field(rng: np.random.Generator, missing: float = 0.3) -> np.ndarray:
    field = rng.normal(1e-4, 2e-5, (len(DAYS), len(LATS), len(LONS)))
    field[rng.random(field.shape) < missing] = np.nan
    return field


def write_slice(directory: Path, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    grids = {
        "no2": {"no2": _field(rng), "cloud_fraction": rng.uniform(0, 1, (len(DAYS), len(LATS), len(LONS)))},
        "so2": {"so2": _field(rng)},
        "aer_ai": {"aer_ai": _field(rng)},
    }
    for name, variables in grids.items():
        ds = make_grid_dataset(
            variables, DAYS, LATS, LONS, primary=name, source="test", ee_id="TEST/ID", mode="synthetic"
        )
        ds.to_netcdf(directory / f"{name}.nc")

    u, v = rng.normal(2, 1, len(DAYS)), rng.normal(-1, 1, len(DAYS))
    wind = pd.DataFrame(
        {
            "time": [t.strftime("%Y-%m-%dT%H:%M:%S+00:00") for t in overpass_times(DAYS)],
            "lon": 82.6,
            "lat": 24.1,
            "u": u,
            "v": v,
            "speed": np.hypot(u, v),
            "dir_from_deg": wind_dir_from_deg(u, v),
            "source": "test",
            "level": "100m",
        }
    )
    wind[list(WIND_COLUMNS)].to_csv(directory / "wind.csv", index=False)

    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [82.6, 24.1]},
        "properties": {"kind": "power_plant"},
    }
    (directory / "osm.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
    pd.DataFrame({"latitude": [24.1], "longitude": [82.6]}).to_csv(directory / "firms.csv", index=False)

    manifest = {
        "unit": "test",
        "created_at": "2026-10-09T00:00:00+00:00",
        "start": DAYS[0].isoformat(),
        "end": DAYS[-1].isoformat(),
        "bbox": BBOX,
        "sources": {"no2": "TEST/ID"},
        "files": sorted(p.name for p in directory.iterdir()),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory


def _rewrite(path: Path, change) -> None:
    with xr.open_dataset(path) as ds:
        ds.load()
    change(ds).to_netcdf(path)


def test_slice_written_with_the_recording_helpers_passes(tmp_path):
    assert check_slice(write_slice(tmp_path)) == []


def test_grid_follows_the_contract(tmp_path):
    write_slice(tmp_path)
    with xr.open_dataset(tmp_path / "no2.nc") as ds:
        assert ds["no2"].dims == ("time", "lat", "lon")
        assert ds["no2"].attrs["units"] == GRID_UNITS["no2"] == "mol/m^2"
        assert ds["valid"].dtype == bool
        assert bool(ds["no2"].isnull().any()), "missing data stays NaN"
        assert np.array_equal(ds["valid"].values, ~np.isnan(ds["no2"].values))
        assert (pd.DatetimeIndex(ds.time.values).hour == 8).all()
        assert ds.time.attrs["time_zone"] == "UTC"
        assert {"source", "ee_id", "fetched_at", "mode"} <= set(ds.attrs)


def test_missing_data_stored_as_zero_is_reported(tmp_path):
    write_slice(tmp_path)
    _rewrite(tmp_path / "no2.nc", lambda ds: ds.assign(no2=ds["no2"].fillna(0)))
    assert any("missing data must be NaN" in p for p in check_slice(tmp_path))


def test_wrong_units_are_reported(tmp_path):
    write_slice(tmp_path)

    def change(ds):
        ds["so2"].attrs["units"] = "DU"
        return ds

    _rewrite(tmp_path / "so2.nc", change)
    assert any("so2 units" in p for p in check_slice(tmp_path))


def test_times_off_the_overpass_hour_are_reported(tmp_path):
    write_slice(tmp_path)
    _rewrite(tmp_path / "no2.nc", lambda ds: ds.assign_coords(time=ds.time + np.timedelta64(5, "h")))
    problems = check_slice(tmp_path)
    assert any("08:00 UTC" in p for p in problems)


def test_wind_without_time_zone_or_with_wrong_direction_is_reported(tmp_path):
    write_slice(tmp_path)
    wind = pd.read_csv(tmp_path / "wind.csv")
    wind["time"] = wind["time"].str.replace("+00:00", "", regex=False)
    wind["dir_from_deg"] = (wind["dir_from_deg"] + 180) % 360  # "towards" instead of "from"
    wind.to_csv(tmp_path / "wind.csv", index=False)
    problems = check_slice(tmp_path)
    assert any("UTC offset" in p for p in problems)
    assert any("dir_from_deg" in p for p in problems)


def test_missing_required_file_and_bad_osm_kind_are_reported(tmp_path):
    write_slice(tmp_path)
    (tmp_path / "so2.nc").unlink()
    (tmp_path / "osm.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"kind": "pub"}}]})
    )
    problems = check_slice(tmp_path)
    assert "so2.nc is missing" in problems
    assert any("unknown kinds" in p for p in problems)


def test_wind_direction_convention():
    assert wind_dir_from_deg(0.0, -5.0) == pytest.approx(0.0)  # blowing south: from the north
    assert wind_dir_from_deg(5.0, 0.0) == pytest.approx(270.0)  # blowing east: from the west
    assert wind_dir_from_deg(0.0, 5.0) == pytest.approx(180.0)


@pytest.mark.skipif(
    not (REAL_SLICE / "manifest.json").exists(),
    reason="the real Singrauli slice has not been recorded yet (run `make fixtures` with credentials)",
)
def test_real_singrauli_slice_is_intact():
    assert check_slice(REAL_SLICE) == []
    manifest = json.loads((REAL_SLICE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["unit"] == "singrauli"
    assert manifest["days"] >= 100
