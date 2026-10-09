"""SQLAlchemy ORM models: the single definition of the database schema (see app.db.init_db).

Geometries are WGS84 (EPSG:4326). Every table is tagged ``info={"kind": ...}``:

* ``derived`` tables can be re-created from fixtures or live sources; ``make resetdb`` drops them.
* ``user`` tables hold what people entered (watchlists, deliveries); only ``make resetdb ALL=1`` drops them.

User tables have no database foreign keys to derived tables, so derived tables can be dropped on their own.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

FACILITY_TYPES = ("coal_power", "steel", "cement", "refinery", "smelter", "other")
UNIT_KINDS = ("facility", "cluster")
DETECTORS = ("no2", "so2", "ch4", "flare", "thermal", "smoke")
ATTRIBUTION_LEVELS = ("facility", "cluster", "ambiguous")
EVENT_STATUSES = ("open", "contested", "rejected_crop_burning", "confirmed")
SPECIES = ("NO2", "NOx", "SO2")
SEASONS = ("all", "DJF", "MAM", "SON")
ESTIMATE_STATUSES = ("ok", "insufficient_data", "contaminated")
DIRECTIONS = ("high", "low")
EXPOSURE_METHODS = ("observed", "wedge")

DERIVED = {"info": {"kind": "derived"}}
USER = {"info": {"kind": "user"}}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def point() -> Geometry:
    return Geometry("POINT", srid=4326, spatial_index=True)


def polygon() -> Geometry:
    return Geometry("POLYGON", srid=4326, spatial_index=True)


def any_geom() -> Geometry:
    return Geometry("GEOMETRY", srid=4326, spatial_index=True)


class WatchUnit(Base):
    """An isolated facility, or a cluster of facilities: the unit of detection, attribution and rates."""

    __tablename__ = "watch_units"
    __table_args__ = (CheckConstraint(_in("kind", UNIT_KINDS), name="ck_watch_units_kind"), DERIVED)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    geom: Mapped[Any] = mapped_column(point())
    member_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    capacity_mw: Mapped[float | None] = mapped_column(Float)
    region: Mapped[str | None] = mapped_column(String(64), index=True)


class Facility(Base):
    __tablename__ = "facilities"
    __table_args__ = (CheckConstraint(_in("type", FACILITY_TYPES), name="ck_facilities_type"), DERIVED)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    operator: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32), default="other")
    capacity_mw: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[Any] = mapped_column(point())
    footprint: Mapped[Any | None] = mapped_column(polygon(), nullable=True)
    watch_unit_id: Mapped[int | None] = mapped_column(ForeignKey("watch_units.id", ondelete="SET NULL"), index=True)
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Detection(Base):
    __tablename__ = "detections"
    __table_args__ = (
        CheckConstraint(_in("detector", DETECTORS), name="ck_detections_detector"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_detections_score"),
        DERIVED,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # sha1 hex from schemas.natural_key(); repositories upsert on it so re-runs never duplicate.
    natural_key: Mapped[str] = mapped_column(String(40), unique=True)
    detector: Mapped[str] = mapped_column(String(16), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    watch_unit_id: Mapped[int | None] = mapped_column(ForeignKey("watch_units.id", ondelete="SET NULL"), index=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id", ondelete="SET NULL"), index=True)
    geom: Mapped[Any] = mapped_column(point())
    footprint: Mapped[Any | None] = mapped_column(polygon(), nullable=True)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    z_bg: Mapped[float | None] = mapped_column(Float)
    z_self: Mapped[float | None] = mapped_column(Float)
    class_label: Mapped[str | None] = mapped_column(String(32))
    class_prob: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_parts: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    qa: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_stub: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_ref: Mapped[str | None] = mapped_column(Text)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(_in("status", EVENT_STATUSES), name="ck_events_status"),
        CheckConstraint(_in("attribution_level", ATTRIBUTION_LEVELS), name="ck_events_attribution_level"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_events_score"),
        DERIVED,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    geom: Mapped[Any] = mapped_column(any_geom())
    watch_unit_id: Mapped[int | None] = mapped_column(ForeignKey("watch_units.id", ondelete="SET NULL"), index=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id", ondelete="SET NULL"), index=True)
    attribution_level: Mapped[str | None] = mapped_column(String(16))
    attribution_margin: Mapped[float | None] = mapped_column(Float)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    detection_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_parts: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="open")
    anomaly_strength: Mapped[float | None] = mapped_column(Float)
    reassigned_from: Mapped[int | None] = mapped_column(ForeignKey("watch_units.id", ondelete="SET NULL"))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EmissionEstimate(Base):
    __tablename__ = "emission_estimates"
    __table_args__ = (
        CheckConstraint(_in("species", SPECIES), name="ck_emission_estimates_species"),
        CheckConstraint(_in("season", SEASONS), name="ck_emission_estimates_season"),
        CheckConstraint(_in("status", ESTIMATE_STATUSES), name="ck_emission_estimates_status"),
        DERIVED,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_unit_id: Mapped[int] = mapped_column(ForeignKey("watch_units.id", ondelete="CASCADE"), index=True)
    species: Mapped[str] = mapped_column(String(8))
    season: Mapped[str] = mapped_column(String(8), default="all")
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32))
    rate_kg_s: Mapped[float | None] = mapped_column(Float)
    stat_low: Mapped[float | None] = mapped_column(Float)
    stat_high: Mapped[float | None] = mapped_column(Float)
    # Total band: statistical band combined with the wind-uncertainty term.
    rate_low: Mapped[float | None] = mapped_column(Float)
    rate_high: Mapped[float | None] = mapped_column(Float)
    wind_sigma_frac: Mapped[float | None] = mapped_column(Float)
    lifetime_h: Mapped[float | None] = mapped_column(Float)
    n_days: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(64))
    reference_value: Mapped[float | None] = mapped_column(Float)
    reference_source: Mapped[str | None] = mapped_column(String(255))
    caveats: Mapped[list[str]] = mapped_column(JSONB, default=list)


class BaselinePrediction(Base):
    __tablename__ = "baseline_predictions"
    __table_args__ = (DERIVED,)

    watch_unit_id: Mapped[int] = mapped_column(ForeignKey("watch_units.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    observed: Mapped[float | None] = mapped_column(Float)
    expected: Mapped[float | None] = mapped_column(Float)
    residual: Mapped[float | None] = mapped_column(Float)
    residual_z: Mapped[float | None] = mapped_column(Float)
    # True when `expected` came from a model that did not see this date's year.
    is_oof: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[str | None] = mapped_column(String(64))


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (CheckConstraint(_in("direction", DIRECTIONS), name="ck_anomalies_direction"), DERIVED)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_unit_id: Mapped[int] = mapped_column(ForeignKey("watch_units.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    residual_z: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8))
    matched_known_event: Mapped[str | None] = mapped_column(Text)


class Exposure(Base):
    __tablename__ = "exposures"
    __table_args__ = (CheckConstraint(_in("method", EXPOSURE_METHODS), name="ck_exposures_method"), DERIVED)

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    plume_geom: Mapped[Any] = mapped_column(polygon())
    method: Mapped[str] = mapped_column(String(16))
    population_raw: Mapped[float | None] = mapped_column(Float)
    population_weighted: Mapped[float | None] = mapped_column(Float)
    schools: Mapped[int] = mapped_column(Integer, default=0)
    hospitals: Mapped[int] = mapped_column(Integer, default=0)
    villages: Mapped[int] = mapped_column(Integer, default=0)
    site_list: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class LayerCache(Base):
    __tablename__ = "layer_cache"
    __table_args__ = (DERIVED,)

    layer: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    ee_map_id: Mapped[str | None] = mapped_column(Text)
    tile_url: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Watchlist(Base):
    """One geofenced area watched by one email address (#33). Alerts go only to confirmed rows."""

    __tablename__ = "watchlists"
    __table_args__ = (
        CheckConstraint("min_score >= 0 AND min_score <= 1", name="ck_watchlists_min_score"),
        USER,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    geom: Mapped[Any] = mapped_column(polygon())
    species: Mapped[list[str]] = mapped_column(ARRAY(String(8)), default=list)  # empty = all species
    min_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirm_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), index=True)


class AlertDelivery(Base):
    """Log of sent alerts. `event_id` / `anomaly_id` point at derived rows and are plain integers;
    a derived-only reset clears this log because those rows no longer exist (see app.db.reset_db)."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "event_id", name="uq_alert_deliveries_watchlist_event"),
        UniqueConstraint("watchlist_id", "anomaly_id", name="uq_alert_deliveries_watchlist_anomaly"),
        USER,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int | None] = mapped_column(Integer)
    anomaly_id: Mapped[int | None] = mapped_column(Integer)
    email: Mapped[str] = mapped_column(String(320))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="sent")
    error: Mapped[str | None] = mapped_column(Text)
