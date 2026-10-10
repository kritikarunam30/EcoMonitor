"""Offline tests of the Phase S analysis prototypes and the report template. No network."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import ee_common as live
import flare_sources
import spike_analysis as analysis
import spike_ee
from app.settings import get_settings
from spike_report import render

LATS = np.arange(23.4, 24.8, 0.02)
LONS = np.arange(81.9, 83.4, 0.02)
CENTRE = (82.65, 24.1)
NULL_ARGS = {
    "local_radius_km": 5,
    "annulus_km": (20, 50),
    "mask_km": 15,
    "n_null": 40,
    "n_null_min_valid": 20,
    "min_valid_fraction": 0.5,
}
SO2_ARGS = {"along_km": 30, "across_km": 10, "min_valid_fraction": 0.5, "n_boot": 200}


@pytest.fixture(scope="module")
def offsets():
    return analysis.km_offsets(LATS, LONS, *CENTRE)


def test_km_offsets_are_metric(offsets):
    x_km, y_km = offsets
    assert x_km.shape == (len(LATS), len(LONS))
    row, col = np.unravel_index(np.argmin(np.hypot(x_km, y_km)), x_km.shape)
    assert abs(LATS[row] - CENTRE[1]) < 0.02 and abs(LONS[col] - CENTRE[0]) < 0.02
    assert y_km[row + 5, col] - y_km[row, col] == pytest.approx(5 * 0.02 * 110.8, rel=0.01)  # 0.1 deg of latitude


def test_valid_fraction_by_month():
    days = [date(2026, 8, 30) + timedelta(days=i) for i in range(4)]  # two in August, two in September
    valid = np.zeros((4, 10, 10), dtype=bool)
    valid[0] = True
    valid[2, :6] = True  # 60 %
    valid[3, :4] = True  # 40 %
    months = analysis.valid_fraction_by_month(valid, days, 0.5).set_index("month")
    assert months.loc["2026-08", ["days", "days_ok"]].tolist() == [2, 1]
    assert months.loc["2026-09", ["days", "days_ok"]].tolist() == [2, 1]
    assert months.loc["2026-09", "fraction_ok"] == 0.5


def test_null_buffer_detects_a_source_and_not_noise(offsets):
    x_km, y_km = offsets
    rng = np.random.default_rng(1)
    noise = rng.normal(1e-4, 1e-5, x_km.shape)
    plume = noise + 5e-5 * np.exp(-(x_km**2 + y_km**2) / (2 * 4**2))

    hit = analysis.null_buffer_z(plume, x_km, y_km, [(0.0, 0.0)], rng=np.random.default_rng(2), **NULL_ARGS)
    assert hit["z_bg"] > 5
    assert hit["n_null"] == 40
    assert hit["local"] > hit["null_median"]

    z = [
        analysis.null_buffer_z(
            rng.normal(1e-4, 1e-5, x_km.shape), x_km, y_km, [(0.0, 0.0)], rng=np.random.default_rng(i), **NULL_ARGS
        )["z_bg"]
        for i in range(200)
    ]
    assert np.mean(np.array(z) >= 2) < 0.10


def test_null_buffer_needs_valid_local_pixels(offsets):
    x_km, y_km = offsets
    field = np.random.default_rng(3).normal(1e-4, 1e-5, x_km.shape)
    field[np.hypot(x_km, y_km) <= 5] = np.nan
    assert analysis.null_buffer_z(field, x_km, y_km, [(0.0, 0.0)], rng=np.random.default_rng(4), **NULL_ARGS) is None


def test_null_buffers_stay_away_from_every_source(offsets):
    x_km, y_km = offsets
    field = np.full(x_km.shape, 1e-4)
    field[np.hypot(x_km - 30, y_km) <= 15] = 1.0  # a second plant; a null buffer here would blow up sigma
    field += np.random.default_rng(5).normal(0, 1e-6, x_km.shape)
    result = analysis.null_buffer_z(
        field, x_km, y_km, [(0.0, 0.0), (30.0, 0.0)], rng=np.random.default_rng(6), **(NULL_ARGS | {"mask_km": 21})
    )
    assert result["null_median"] < 1e-3 and result["null_sigma"] < 1e-5


def test_downwind_enhancement_follows_the_wind(offsets):
    x_km, y_km = offsets
    field = np.full(x_km.shape, 1e-4)
    field[(x_km > 0) & (x_km <= 30) & (np.abs(y_km) <= 10)] += 1e-5  # plume towards the east
    kwargs = {"along_km": 30, "across_km": 10, "min_valid_fraction": 0.5}
    assert analysis.downwind_enhancement(field, x_km, y_km, 5.0, 0.0, **kwargs) == pytest.approx(1e-5, rel=0.05)
    assert analysis.downwind_enhancement(field, x_km, y_km, -5.0, 0.0, **kwargs) == pytest.approx(-1e-5, rel=0.05)
    assert abs(analysis.downwind_enhancement(field, x_km, y_km, 0.0, 5.0, **kwargs)) < 2e-6
    assert analysis.downwind_enhancement(field, x_km, y_km, 0.0, 0.0, **kwargs) is None


def _so2_window(rng: np.random.Generator, x_km, y_km, source: float, days: int = 28):
    fields, winds = [], []
    for _ in range(days):
        angle = rng.uniform(0, 2 * np.pi)
        u, v = 4 * np.cos(angle), 4 * np.sin(angle)
        along = (x_km * u + y_km * v) / 4
        across = (-x_km * v + y_km * u) / 4
        field = rng.normal(0, 2e-4, x_km.shape)
        field[(along > 0) & (along <= 30) & (np.abs(across) <= 10)] += source
        fields.append(field)
        winds.append((u, v))
    return np.array(fields), winds


def test_so2_window_detects_a_constant_source_and_rejects_noise(offsets):
    x_km, y_km = offsets
    rng = np.random.default_rng(7)
    fields, winds = _so2_window(rng, x_km, y_km, source=5e-5)
    hit = analysis.so2_window_z(fields, winds, x_km, y_km, rng=np.random.default_rng(8), **SO2_ARGS)
    assert hit["n_valid_days"] == 28
    assert hit["z"] > 2 and hit["p5"] > 0

    detections = 0
    for i in range(40):
        fields, winds = _so2_window(rng, x_km, y_km, source=0.0, days=14)
        result = analysis.so2_window_z(fields, winds, x_km, y_km, rng=np.random.default_rng(100 + i), **SO2_ARGS)
        detections += result["z"] >= 2 and result["p5"] > 0
    assert detections / 40 < 0.15


def test_so2_window_without_enough_days_gives_no_z(offsets):
    x_km, y_km = offsets
    fields = np.full((3, *x_km.shape), np.nan)
    result = analysis.so2_window_z(fields, [(1.0, 0.0)] * 3, x_km, y_km, rng=np.random.default_rng(9), **SO2_ARGS)
    assert result["n_valid_days"] == 0
    assert np.isnan(result["z"])


def test_empty_report_is_the_template():
    text = render({})
    assert "NOT RUN YET" in text
    for heading in ("## 2. Collections", "## 4. Wind", "## 6. Valid days per month", "## 12. Gate G1"):
        assert heading in text


def test_report_shows_the_facts_and_nothing_else():
    facts = {
        "run": {"started_at": "2026-10-10 06:00", "region": "singrauli", "days": 120},
        "collections": {"s5p_no2_offl": {"id": "SOME/ID", "ok": True, "bands": ["a", "b"], "latency_days": 5.25}},
        "errors": {"firms": "FIRMS_MAP_KEY is not set in .env"},
    }
    text = render(facts)
    assert "NOT RUN YET" not in text
    assert "| s5p_no2_offl | SOME/ID | yes |" in text
    assert "5.25" in text and "a, b" in text
    assert "FIRMS_MAP_KEY is not set" in text


def test_grid_spec_and_window_bbox_agree():
    bbox = live.window_bbox(82.65, 24.1, 60)
    west, south, east, north = bbox
    assert west < 82.65 < east and south < 24.1 < north
    assert (north - south) * 110.8 == pytest.approx(120, rel=0.01)

    spec, lats, lons = live.grid_spec(bbox, 0.01)
    assert (spec["dimensions"]["height"], spec["dimensions"]["width"]) == (len(lats), len(lons))
    assert spec["affineTransform"]["translateY"] == north and spec["affineTransform"]["scaleY"] == -0.01
    assert np.all(np.diff(lats) > 0)
    assert lats[0] == pytest.approx(south + 0.005, abs=0.006) and lons[0] == pytest.approx(west + 0.005)


def test_osm_element_geometry():
    node = {"type": "node", "id": 1, "lon": 82.6, "lat": 24.1}
    ring = [{"lon": 0, "lat": 0}, {"lon": 2, "lat": 0}, {"lon": 2, "lat": 2}, {"lon": 0, "lat": 0}]
    way = {"type": "way", "id": 2, "geometry": ring}
    relation = {"type": "relation", "id": 3, "bounds": {"minlon": 1, "maxlon": 3, "minlat": 10, "maxlat": 12}}
    assert live.element_geometry(node) == {"type": "Point", "coordinates": [82.6, 24.1]}
    assert live.element_geometry(way)["type"] == "Polygon"
    assert live.element_geometry(relation) == {"type": "Point", "coordinates": [2.0, 11.0]}
    assert live.element_geometry({"type": "relation", "id": 4}) is None
    assert live.element_centre(node) == (82.6, 24.1)


def test_wind_pairs_need_both_components():
    bands = ["u_component_of_wind_10m", "v_component_of_wind_10m", "u_component_of_wind_100m", "temperature_2m"]
    assert spike_ee.wind_pairs(bands) == {10: ("u_component_of_wind_10m", "v_component_of_wind_10m")}
    assert spike_ee.wind_pairs(["speed"]) == {}
    assert spike_ee.forecast_filter(["creation_time", "forecast_hours"]) == {"forecast_hours": 0}
    assert spike_ee.forecast_filter(["hour"]) is None


def test_bands_are_picked_from_what_the_collection_reports():
    assert spike_ee.pick_band(["a_column", "cloud_fraction"], r"^cloud_fraction$") == "cloud_fraction"
    assert spike_ee.pick_band(["a_column"], r"^cloud_fraction$") is None
    assert spike_ee.pick_band(["a_column"], None) is None


def test_decisions_follow_the_measured_numbers():
    cfg = get_settings().config
    facts = {
        "collections": {"s5p_no2_offl": {"latency_days": 5.0}, "s5p_no2_nrti": {"latency_days": 0.2}},
        "valid_days": {
            "no2": {
                "months": [
                    {"month": "2026-08", "days": 31, "days_ok": 2},
                    {"month": "2026-10", "days": 10, "days_ok": 3},
                ]
            }
        },
        "so2_window": [{"z": 1.2, "p5": -1e-6}, {"z": float("nan"), "p5": float("nan")}, {"z": None}],
    }
    decisions = {d["decision"]: d for d in spike_ee.suggest_decisions(facts, cfg)}
    assert "30%" in decisions["valid_fraction_min and windows"]["basis"]  # October only: 3 of 10
    assert "widen" in decisions["valid_fraction_min and windows"]["suggestion"]
    assert "regional layer" in decisions["SO2 scope (gate G1)"]["suggestion"]
    assert "0 of 1" in decisions["SO2 scope (gate G1)"]["basis"]
    assert spike_ee.suggest_decisions({}, cfg) == []


def test_best_wind_key_prefers_coverage_then_height():
    wind = {
        "collections": {
            "a": {"heights": [10], "days_covered": 120},
            "b": {"heights": [10, 100], "days_covered": 120},
            "c": {"heights": [10, 100], "days_covered": 30},
            "d": {"heights": []},
        }
    }
    assert spike_ee.best_wind_key({"wind": wind}) == ("b", 100)
    assert spike_ee.best_wind_key({}) is None


PLANT = {"name": "plant A", "lon": 82.65, "lat": 24.1}


def _firms_rows() -> pd.DataFrame:
    near, far = (24.105, 82.655), (24.5, 83.0)  # about 0.75 km and 55 km from the plant
    rows = [
        (*near, "2026-09-01", "N", 12.0),
        (*near, "2026-09-01", "N", 8.0),  # same night, second pixel
        (*near, "2026-09-10", "N", 2.0),  # weak
        (*near, "2026-09-20", "N", 9.0),
        (*near, "2026-09-21", "D", 50.0),  # daytime: not a flare night
        (*near, "2026-11-30", "N", 20.0),  # outside the 30-day window of the others
        (*far, "2026-09-02", "N", 30.0),
    ]
    return pd.DataFrame(rows, columns=["latitude", "longitude", "acq_date", "daynight", "frp"])


def test_night_counts_near_a_plant_follow_the_persistence_window():
    (row,) = flare_sources.night_counts_near(_firms_rows(), [PLANT], radius_km=2, window_days=30, min_frp_mw=5)
    assert row["plant"] == "plant A"
    assert row["detections"] == 5 and row["nights"] == 4
    assert row["max_nights_in_window"] == 3  # 1, 10 and 20 September
    assert row["max_nights_in_window_min_frp"] == 2  # the 10 September pixel is below 5 MW
    assert row["median_frp_mw"] == 9.0


def test_night_counts_without_detections_and_without_columns():
    empty = _firms_rows().iloc[0:0]
    (row,) = flare_sources.night_counts_near(empty, [PLANT], radius_km=2, window_days=30, min_frp_mw=5)
    assert row["detections"] == 0 and row["max_nights_in_window"] == 0
    with pytest.raises(ValueError, match="daynight"):
        flare_sources.night_counts_near(_firms_rows().drop(columns="daynight"), [PLANT], 2, 30, 5)


def test_max_dates_in_window_is_exclusive_at_the_window_length():
    dates = pd.Series(["2026-01-01", "2026-01-15", "2026-01-30", "2026-01-31", "2026-01-31"])
    assert flare_sources.max_dates_in_window(dates, 30) == 3  # 1-30 January, or 15-31 January
    assert flare_sources.max_dates_in_window(dates, 31) == 4
    assert flare_sources.max_dates_in_window(dates.iloc[0:0], 30) == 0


def test_annual_flare_files_are_read_and_clipped(tmp_path, monkeypatch):
    monkeypatch.setattr(flare_sources, "REPO_ROOT", tmp_path)
    bbox = (82.0, 23.6, 83.4, 24.8)
    pd.DataFrame({"Latitude": [24.0, 30.0, None], "Longitude": [82.5, 70.0, 82.5], "BCM 2025": [0.1, 0.2, 0.3]}).to_csv(
        tmp_path / "sites.csv", index=False
    )
    with pd.ExcelWriter(tmp_path / "gfmr.xlsx") as writer:
        pd.DataFrame({"note": ["no coordinates on this sheet"]}).to_excel(writer, sheet_name="readme", index=False)
        pd.DataFrame({"lat": [24.2, 24.3], "lon": [82.6, 82.7]}).to_excel(writer, sheet_name="2025", index=False)
    (tmp_path / "eog.kml").write_text(
        "<kml><Placemark><Point><coordinates>82.9,24.4,0</coordinates></Point></Placemark>"
        "<Placemark><Point><coordinates> 10.0,50.0 </coordinates></Point></Placemark></kml>"
    )
    (tmp_path / "notes.txt").write_text("not a flare file")

    summary = flare_sources.flare_sites_summary(tmp_path, bbox)
    by_file = {f["file"]: f for f in summary["files"]}
    assert (by_file["sites.csv"]["sites"], by_file["sites.csv"]["sites_in_region"]) == (2, 1)
    assert (by_file["gfmr.xlsx"]["sites"], by_file["gfmr.xlsx"]["sites_in_region"]) == (2, 2)
    assert (by_file["eog.kml"]["sites"], by_file["eog.kml"]["sites_in_region"]) == (2, 1)
    assert "unsupported" in by_file["notes.txt"]["error"]
    assert summary["sites_in_region"] == 4
    assert flare_sources.read_flare_sites(tmp_path / "gfmr.xlsx")["sheet"].unique().tolist() == ["2025"]


def test_missing_flare_folder_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(flare_sources, "REPO_ROOT", tmp_path)
    summary = flare_sources.flare_sites_summary(tmp_path / "flares", (82.0, 23.6, 83.4, 24.8))
    assert summary["files"] == [] and summary["sites_in_region"] == 0


def test_flaring_decision_uses_sites_and_persistent_plants():
    cfg = get_settings().config
    near = [
        {"plant": "plant A", "max_nights_in_window_min_frp": 4},
        {"plant": "plant B", "max_nights_in_window_min_frp": 1},
    ]
    facts = {
        "firms": {"sources": {"VIIRS_SNPP_NRT": {"near_plants": near}}},
        "flares": {"sites_in_region": 0, "nightfire_files_on_disk": 0},
    }
    decision = {d["decision"]: d for d in spike_ee.suggest_decisions(facts, cfg)}["Flaring source (`flaring.source`)"]
    assert decision["suggestion"] == "firms_persistent."
    assert decision["basis"].endswith("window: plant A")
    assert "0 annual flare sites" in decision["basis"]


def test_nightfire_is_never_required():
    assert "nightfire" not in spike_ee.SECTIONS
    assert not [name for name in live.LiveEnv.model_fields if name.startswith("eog")]
    text = render({"flares": {"directory": "data/registry/raw/flares", "files": [], "nightfire_files_on_disk": 0}})
    assert "not tested by the script" in text
    assert "Flaring source (`flaring.source`)" in text
