import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app import models, schemas

OVERPASS = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _detection(**overrides) -> schemas.Detection:
    fields = {
        "detector": "no2",
        "observed_at": OVERPASS,
        "watch_unit_id": 7,
        "geom": schemas.Point(coordinates=(82.6, 24.1)),
    }
    return schemas.Detection(**(fields | overrides))


def test_detection_roundtrip():
    d = _detection(
        value=1.2e-4,
        unit="mol/m2",
        z_bg=3.1,
        z_self=2.4,
        score=0.8,
        score_parts={"signal_quality": 0.9, "attribution_certainty": 0.7, "anomaly_strength": 0.8},
    )
    again = schemas.Detection.model_validate_json(d.model_dump_json())
    assert again == d
    assert again.geom.type == "Point"
    assert again.is_stub is False


@pytest.mark.parametrize(
    "bad",
    [
        {"detector": "co2"},
        {"score": 1.5},
        {"class_prob": -0.1},
        {"geom": {"type": "Point", "coordinates": (500, 24)}},
        {"observed_at": "2026-10-01T08:00:00"},  # naive datetime
        {"score_parts": {"signal_quality": 1.2, "attribution_certainty": 0.5, "anomaly_strength": 0.5}},
    ],
)
def test_detection_rejects_invalid(bad):
    base = {
        "detector": "so2",
        "observed_at": "2026-10-01T08:00:00Z",
        "geom": {"type": "Point", "coordinates": (82.6, 24.1)},
    }
    with pytest.raises(ValidationError):
        schemas.Detection.model_validate(base | bad)


def test_natural_key_follows_the_documented_format():
    expected = hashlib.sha1(b"no2|7|2026-10-01T08|82.6000|24.1000").hexdigest()
    assert schemas.natural_key("no2", 7, OVERPASS, 82.6, 24.1) == expected
    assert _detection().natural_key == expected
    assert len(expected) == models.Detection.natural_key.type.length


def test_natural_key_without_unit_uses_a_dash():
    expected = hashlib.sha1(b"thermal|-|2026-10-01T08|82.6000|24.1000").hexdigest()
    assert schemas.natural_key("thermal", None, OVERPASS, 82.6, 24.1) == expected


def test_natural_key_is_stable_across_time_zones_and_within_the_hour():
    ist = timezone(timedelta(hours=5, minutes=30))
    same_instant = OVERPASS.astimezone(ist)
    assert _detection(observed_at=same_instant).natural_key == _detection().natural_key
    assert _detection(observed_at=OVERPASS + timedelta(minutes=40)).natural_key == _detection().natural_key


@pytest.mark.parametrize(
    "change",
    [
        {"detector": "so2"},
        {"watch_unit_id": 8},
        {"watch_unit_id": None},
        {"observed_at": OVERPASS + timedelta(hours=1)},
        {"geom": schemas.Point(coordinates=(82.6001, 24.1))},
    ],
)
def test_natural_key_changes_with_each_identity_field(change):
    assert _detection(**change).natural_key != _detection().natural_key


def test_natural_key_ignores_non_identity_fields():
    assert _detection(value=9.9, score=0.4, qa={"cloud": 0.1}).natural_key == _detection().natural_key


def test_natural_key_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        schemas.natural_key("no2", 7, datetime(2026, 10, 1, 8), 82.6, 24.1)


def test_schema_literals_match_db_constraints():
    pairs = [
        (schemas.DetectorName, models.DETECTORS),
        (schemas.UnitKind, models.UNIT_KINDS),
        (schemas.AttributionLevel, models.ATTRIBUTION_LEVELS),
        (schemas.EventStatus, models.EVENT_STATUSES),
        (schemas.Species, models.SPECIES),
        (schemas.Season, models.SEASONS),
        (schemas.EstimateStatus, models.ESTIMATE_STATUSES),
        (schemas.ExposureMethod, models.EXPOSURE_METHODS),
        (schemas.FacilityType, models.FACILITY_TYPES),
    ]
    for literal, values in pairs:
        assert set(literal.__args__) == set(values)


# (schema, table, fields only in the schema, columns only in the table)
PARITY = [
    (schemas.Facility, models.Facility, set(), set()),
    # The schema carries the centroid as lon/lat (plan §0.6); the table stores a point and the region.
    (schemas.WatchUnit, models.WatchUnit, {"lon", "lat"}, {"geom", "region"}),
    (schemas.Detection, models.Detection, set(), set()),
    (schemas.Event, models.Event, set(), {"created_at", "updated_at"}),
    (schemas.EmissionEstimate, models.EmissionEstimate, set(), set()),
    (schemas.Exposure, models.Exposure, set(), set()),
]


@pytest.mark.parametrize(("schema", "table", "schema_only", "table_only"), PARITY)
def test_schema_fields_match_table_columns(schema, table, schema_only, table_only):
    fields = set(schema.model_fields) | set(schema.model_computed_fields)
    columns = set(table.__table__.columns.keys())
    assert fields - columns == schema_only
    assert columns - fields == table_only
