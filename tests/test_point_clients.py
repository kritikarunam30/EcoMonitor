"""FIRMS, flaring sources, Nightfire and OSM clients (plan Phase 2, task 3): fixture mode, and the
live code path with the HTTP call replaced. No network."""

from datetime import date

import geopandas as gpd
import pandas as pd
import pytest

from app.clients import firms, flares, nightfire, osm
from app.settings import Settings, get_settings

REGION = (82.0, 23.6, 83.4, 24.8)
START, END = date(2025, 11, 1), date(2025, 11, 10)


# --- FIRMS ----------------------------------------------------------------------------------------


def test_firms_fixture_rows_are_clipped_to_bbox_and_days():
    rows = firms.get_firms(REGION, START, END)
    spec = get_settings().sources["firms"]["VIIRS_SNPP_SP"]
    assert set(spec["columns"]) <= set(rows.columns) and {"source", "acq_datetime"} <= set(rows.columns)
    assert len(rows) > 0 and set(rows["source"]) == {"VIIRS_SNPP_SP"}, "the slice is history: standard processing"
    assert rows["acq_date"].min() >= "2025-11-01" and rows["acq_date"].max() <= "2025-11-10"
    assert str(rows["acq_datetime"].dt.tz) == "UTC"
    first = rows.iloc[0]
    assert first["acq_datetime"] == pd.Timestamp(f"{first['acq_date']} {int(first['acq_time']):04d}", tz="UTC")

    small = firms.get_firms((82.6, 24.0, 82.8, 24.2), START, END)
    assert 0 < len(small) < len(rows)
    assert small["longitude"].between(82.6, 82.8).all() and small["latitude"].between(24.0, 24.2).all()


def test_firms_without_data_is_an_empty_table_with_the_columns():
    rows = firms.get_firms(REGION, date(2024, 1, 1), date(2024, 1, 5))
    assert rows.empty and {"latitude", "longitude", "frp", "daynight", "source", "acq_datetime"} <= set(rows.columns)
    assert firms.get_firms(REGION, START, END, sources=["VIIRS_NOAA20_NRT"]).empty
    with pytest.raises(ValueError, match="not confirmed by the spike"):
        firms.get_firms(REGION, START, END, sources=["MODIS_NRT"])


def test_night_only_keeps_night_detections():
    rows = firms.get_firms(REGION, START, END)
    night = firms.night_only(rows)
    assert 0 < len(night) < len(rows) and set(night["daynight"]) == {"N"}


def test_live_firms_asks_each_source_for_its_days_in_chunks_and_caches(live_cache, monkeypatch):
    requests = []

    def fake_area(source, bbox, day_range, start):
        requests.append((source, day_range, start))
        return pd.DataFrame(
            {
                "latitude": [24.1],
                "longitude": [82.7],
                "acq_date": [start.isoformat()],
                "acq_time": [5],  # 00:05 UTC
                "frp": [12.5],
                "daynight": ["N"],
                "version": ["2.0NRT" if source.endswith("NRT") else 2],
            }
        )

    monkeypatch.setattr(firms, "area_rows", fake_area)
    monkeypatch.setattr(
        firms,
        "availability",
        lambda: {
            "VIIRS_SNPP_SP": (date(2012, 1, 20), date(2025, 6, 30)),
            "VIIRS_SNPP_NRT": (date(2025, 7, 1), date(2025, 9, 30)),
            "VIIRS_NOAA20_NRT": (date(2025, 7, 1), date(2025, 9, 30)),
        },
    )
    rows = firms.get_firms(REGION, date(2025, 6, 24), date(2025, 7, 7))
    assert requests == [
        ("VIIRS_SNPP_NRT", 5, date(2025, 7, 1)),
        ("VIIRS_SNPP_NRT", 2, date(2025, 7, 6)),
        ("VIIRS_NOAA20_NRT", 5, date(2025, 7, 1)),
        ("VIIRS_NOAA20_NRT", 2, date(2025, 7, 6)),
        ("VIIRS_SNPP_SP", 5, date(2025, 6, 24)),
        ("VIIRS_SNPP_SP", 2, date(2025, 6, 29)),
    ], "at most 5 days per request (spike), each source only for the days it holds"
    assert len(rows) == 6 and set(rows["source"]) == {"VIIRS_SNPP_SP", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"}
    assert rows["acq_datetime"].iloc[0].hour == 0 and rows["acq_datetime"].iloc[0].minute == 5

    again = firms.get_firms(REGION, date(2025, 6, 24), date(2025, 7, 7))
    assert len(requests) == 6 and len(again) == 6, "the second call reads parquet"
    assert len(list((live_cache / "firms").glob("*.parquet"))) == 6


def test_firms_errors_carry_the_service_text_but_never_the_key(live_cache, monkeypatch):
    monkeypatch.setattr(get_settings(), "firms_map_key", "SECRETKEY123")
    monkeypatch.setattr(firms.time, "sleep", lambda s: None)

    class Response:
        status_code = 200
        text = "Invalid MAP_KEY SECRETKEY123. Exceeding allowed transaction limit."

    seen = []
    monkeypatch.setattr(firms, "firms_get", lambda path, key: seen.append(path) or Response())
    with pytest.raises(RuntimeError) as error:
        firms.area_rows("VIIRS_SNPP_NRT", REGION, 5, date(2026, 1, 1))
    assert "transaction limit" in str(error.value) and "SECRETKEY123" not in str(error.value)
    assert seen == ["/api/area/csv/{key}/VIIRS_SNPP_NRT/82.0000,23.6000,83.4000,24.8000/5/2026-01-01"]

    monkeypatch.setattr(get_settings(), "firms_map_key", "")
    with pytest.raises(RuntimeError, match="FIRMS_MAP_KEY is not set"):
        firms.area_rows("VIIRS_SNPP_NRT", REGION, 5, date(2026, 1, 1))


def test_firms_availability_outside_live_mode_is_the_spike_record():
    ranges = firms.availability()
    assert ranges["VIIRS_SNPP_SP"] == (date(2012, 1, 20), date(2026, 6, 30))
    assert ranges["VIIRS_SNPP_NRT"][0] == date(2026, 7, 1)


# --- flaring sources ------------------------------------------------------------------------------


def test_default_flaring_source_is_night_time_firms():
    assert get_settings().config.flaring["source"] == "firms_persistent"
    result = flares.get_flare_observations(REGION, START, END)
    assert (result.requested, result.source) == ("firms_persistent", "firms_persistent")
    assert list(result.rows.columns) == flares.OBS_COLUMNS
    assert len(result.rows) == len(firms.night_only(firms.get_firms(REGION, START, END))) > 0
    assert result.rows["temp_k"].isna().all(), "FIRMS has no flame temperature"
    assert result.rows["frp_mw"].notna().all() and str(result.rows["observed_at"].dt.tz) == "UTC"


def test_nightfire_is_optional_and_falls_back_without_failing():
    rows, note = nightfire.get_nightfire(REGION, START, END)
    assert rows is None and "unavailable" in note

    result = flares.get_flare_observations(REGION, START, END, source="nightfire")
    assert (result.requested, result.source) == ("nightfire", "firms_persistent")
    assert "Nightfire unavailable" in result.note and "fell back to firms_persistent" in result.note
    assert len(result.rows) > 0


def test_no_eog_variable_is_required(monkeypatch):
    monkeypatch.delenv("EOG_CLIENT_ID", raising=False)
    monkeypatch.delenv("EOG_CLIENT_SECRET", raising=False)
    settings = Settings(_env_file=None)
    assert settings.eog_client_id == "" and settings.eog_client_secret == ""
    assert not [n for n, f in Settings.model_fields.items() if n.startswith("eog") and f.is_required()]


def test_nightfire_reads_files_a_person_placed_on_disk(live_cache, monkeypatch, tmp_path):
    folder = tmp_path / "nightfire"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "nightfire_dir", folder)
    pd.DataFrame(
        {
            "Lat_GMTCO": [24.10, 24.11, 10.0, 24.12],
            "Lon_GMTCO": [82.70, 82.71, 82.7, 82.72],
            "Temp_BB": [1650, 999999, 1700, 1500],
            "Date_Mscan": ["2025-11-03 20:31:00", "2025-11-04 20:12:00", "2025-11-03 20:31:00", "2025-12-25 20:00:00"],
        }
    ).to_csv(folder / "VNF_npp_d20251103.csv", index=False)
    pd.DataFrame({"x": [1], "y": [2]}).to_csv(folder / "other_layout.csv", index=False)

    rows, note = nightfire.get_nightfire(REGION, START, END)
    assert list(rows.columns) == nightfire.COLUMNS and len(rows) == 2, "inside the region and the days"
    assert rows["observed_at"].iloc[0] == pd.Timestamp("2025-11-03 20:31", tz="UTC") and rows["temp_k"].iloc[0] == 1650
    assert "other_layout.csv" in note

    result = flares.get_flare_observations(REGION, START, END, source="nightfire")
    assert result.source == "nightfire" and list(result.rows.columns) == flares.OBS_COLUMNS
    assert result.rows["frp_mw"].isna().all() and (result.rows["source"] == "nightfire").all()


def test_nightfire_never_raises(live_cache, monkeypatch, tmp_path):
    folder = tmp_path / "nightfire"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "nightfire_dir", folder)
    (folder / "broken.csv").write_bytes(b"\x00\xff\x00 not a table \xfe")
    rows, note = nightfire.get_nightfire(REGION, START, END)
    assert rows is None and note.startswith("Nightfire unavailable")

    monkeypatch.setattr(get_settings(), "nightfire_dir", tmp_path / "missing")
    monkeypatch.setattr(get_settings(), "eog_client_id", "id")
    monkeypatch.setattr(get_settings(), "eog_client_secret", "secret")
    rows, note = nightfire.get_nightfire(REGION, START, END)
    assert rows is None and "scripted download is not implemented" in note


def test_annual_sites_in_the_fixture_region_are_empty_but_typed():
    sites = flares.get_annual_sites(REGION)
    assert isinstance(sites, gpd.GeoDataFrame) and sites.empty and sites.crs.to_epsg() == 4326
    assert list(sites.columns) == [*flares.SITE_COLUMNS, "geometry"]
    result = flares.get_flare_observations(REGION, START, END, source="annual_sites")
    assert result.source == "annual_sites" and result.rows.empty and list(result.rows.columns) == flares.OBS_COLUMNS
    with pytest.raises(ValueError, match="unknown flaring source"):
        flares.get_flare_observations(REGION, START, END, source="guess")


def test_annual_sites_are_read_from_files_once_and_kept_as_parquet(live_cache, monkeypatch, tmp_path):
    folder = tmp_path / "flares"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "flare_dir", folder)
    pd.DataFrame(
        {
            "Country": ["India", "India", "Iraq"],
            "Latitude": [24.2, 21.0, 30.5],
            "Longitude": [82.9, 72.6, 47.4],
            "bcm": [0.02, 0.4, 1.1],
            "Year": [2024, 2024, 2024],
        }
    ).to_csv(folder / "flares_2024.csv", index=False)
    (folder / "sites.kml").write_text(
        "<kml><Placemark><Point><coordinates>82.5,24.0,0</coordinates></Point></Placemark></kml>", encoding="utf-8"
    )
    parsed = []
    read = flares.read_flare_sites
    monkeypatch.setattr(flares, "read_flare_sites", lambda path: parsed.append(path.name) or read(path))

    sites = flares.get_annual_sites(REGION)
    assert len(sites) == 2 and sites.crs.to_epsg() == 4326
    with_volume = sites[sites["source_file"] == "flares_2024.csv"].iloc[0]
    assert (with_volume["lon"], with_volume["lat"], with_volume["volume_bcm"], with_volume["year"]) == (
        82.9,
        24.2,
        0.02,
        2024,
    )
    assert with_volume.geometry.x == 82.9 and with_volume.geometry.y == 24.2
    assert pd.isna(sites[sites["source_file"] == "sites.kml"].iloc[0]["volume_bcm"])

    assert len(flares.get_annual_sites((70.0, 20.0, 75.0, 22.0))) == 1
    assert sorted(parsed) == ["flares_2024.csv", "sites.kml"], "each file is parsed once"
    result = flares.get_flare_observations(REGION, START, END, source="annual_sites")
    assert len(result.rows) == 2 and result.rows["observed_at"].isna().all()


# --- OSM ------------------------------------------------------------------------------------------


def test_osm_fixture_objects_by_kind_and_bbox():
    everything = osm.get_osm(REGION)
    assert isinstance(everything, gpd.GeoDataFrame) and everything.crs.to_epsg() == 4326
    assert list(everything.columns) == osm.COLUMNS
    assert set(everything["kind"]) == set(osm.OSM_SELECTORS)
    plants = osm.get_osm(REGION, ["power_plant"])
    assert "Vindhyachal" in " ".join(plants["name"].dropna())
    vindhyachal = plants[plants["name"].fillna("").str.contains("Vindhyachal")].iloc[0]
    assert vindhyachal["tags"]["power"] == "plant" and "kind" not in vindhyachal["tags"]

    box = (82.6, 24.0, 82.8, 24.2)
    near = osm.get_osm(box, ["chimney", "school"])
    assert 0 < len(near) < len(osm.get_osm(REGION, ["chimney", "school"]))
    assert set(near["kind"]) <= {"chimney", "school"}
    assert near.geometry.representative_point().x.between(82.55, 82.85).all()
    with pytest.raises(ValueError, match="unknown OSM kinds"):
        osm.get_osm(REGION, ["volcano"])


def test_live_osm_sends_one_query_per_kind_and_caches(live_cache, monkeypatch):
    queries = []
    monkeypatch.setattr(osm.time, "sleep", lambda s: None)

    def fake_post(query, timeout_s):
        queries.append(query)
        if "chimney" in query:
            return {"elements": [{"type": "node", "id": 1, "lon": 82.7, "lat": 24.1, "tags": {"man_made": "chimney"}}]}
        ring = [{"lon": 82.70, "lat": 24.10}, {"lon": 82.71, "lat": 24.10}, {"lon": 82.71, "lat": 24.11}]
        way = {"type": "way", "id": 2, "geometry": [*ring, ring[0]], "tags": {"name": "School", "name:en": "A school"}}
        return {"elements": [way, {"type": "relation", "id": 3}]}

    monkeypatch.setattr(osm, "_post_overpass", fake_post)
    found = osm.get_osm(REGION, ["chimney", "school"])
    assert len(queries) == 2 and all("(23.6,82.0,24.8,83.4)" in q for q in queries), (
        "Overpass wants south,west,north,east"
    )
    assert 'node["man_made"="chimney"]' in queries[0]
    assert list(found["kind"]) == ["chimney", "school"] and list(found["osm_id"]) == [1, 2], "no geometry, no row"
    assert found.geometry.iloc[0].geom_type == "Point" and found.geometry.iloc[1].geom_type == "Polygon"
    assert found["name"].iloc[1] == "A school"

    osm.get_osm(REGION, ["chimney", "school"])
    assert len(queries) == 2 and len(list((live_cache / "osm").glob("*.json"))) == 2
