import json

import pytest
from pydantic import ValidationError

from app.jobs.scheduler import build_scheduler
from app.schemas import ScoreParts
from app.settings import AppConfig, RegionConfig, get_settings


def test_fixture_mode_in_tests():
    assert get_settings().data_mode == "fixture"


def test_settings_yaml_has_every_section():
    cfg = get_settings().config
    for section in AppConfig.model_fields:
        assert getattr(cfg, section), f"settings.yaml section '{section}' is empty"


def test_score_weights_cover_the_three_parts():
    assert set(get_settings().config.score["weights"]) == set(ScoreParts.model_fields)


def test_every_wind_provider_has_an_uncertainty():
    wind = get_settings().config.wind
    assert set(wind["chain"]) == set(wind["uncertainty_frac"])


def test_region_geojson_matches_bbox():
    settings = get_settings()
    region = settings.config.region
    with open(settings.resolve(region.geojson), encoding="utf-8") as f:
        ring = json.load(f)["features"][0]["geometry"]["coordinates"][0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    assert (min(lons), min(lats), max(lons), max(lats)) == region.bbox


def test_bad_bbox_rejected():
    with pytest.raises(ValidationError):
        RegionConfig(name="x", bbox=(83, 24, 82, 25), geojson="x.geojson")


def test_scheduler_runs_in_the_configured_timezone():
    scheduler = build_scheduler()
    assert str(scheduler.timezone) == "Asia/Kolkata"
    assert scheduler.get_job("heartbeat") is not None
