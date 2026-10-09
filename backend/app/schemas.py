"""Pydantic schemas shared by detectors, the pipeline and the API (plan §0.6).

Every detector returns ``list[Detection]``; layer-only products (CH4) return a ``LayerProduct``.
Geometries are GeoJSON in WGS84 (EPSG:4326). All datetimes are UTC and timezone-aware.
A score is an uncalibrated number in [0, 1], not a probability.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field, field_validator

DetectorName = Literal["no2", "so2", "ch4", "flare", "thermal", "smoke"]
UnitKind = Literal["facility", "cluster"]
AttributionLevel = Literal["facility", "cluster", "ambiguous"]
EventStatus = Literal["open", "contested", "rejected_crop_burning", "confirmed"]
Species = Literal["NO2", "NOx", "SO2"]
Season = Literal["all", "DJF", "MAM", "SON"]
EstimateStatus = Literal["ok", "insufficient_data", "contaminated"]
ExposureMethod = Literal["observed", "wedge"]
FacilityType = Literal["coal_power", "steel", "cement", "refinery", "smelter", "other"]


def natural_key(detector: str, watch_unit_id: int | None, observed_at: datetime, lon: float, lat: float) -> str:
    """Stable identity of a detection; repositories upsert on it so re-running a date never duplicates.

    ``sha1("{detector}|{watch_unit_id or '-'}|{observed_at:%Y-%m-%dT%H}|{lon:.4f}|{lat:.4f}")`` with
    `observed_at` taken in UTC.
    """
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    hour = observed_at.astimezone(UTC).strftime("%Y-%m-%dT%H")
    raw = f"{detector}|{watch_unit_id or '-'}|{hour}|{lon:.4f}|{lat:.4f}"
    return hashlib.sha1(raw.encode()).hexdigest()


class GeoJSONGeometry(BaseModel):
    """Minimal GeoJSON geometry. Coordinates are [lon, lat]."""

    type: Literal["Point", "Polygon", "MultiPolygon", "LineString"]
    coordinates: Any


class Point(GeoJSONGeometry):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def _wgs84(cls, v: tuple[float, float]) -> tuple[float, float]:
        lon, lat = v
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"not a WGS84 lon/lat: {v}")
        return v


class Polygon(GeoJSONGeometry):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]


class ScoreParts(BaseModel):
    """The three questions behind a score, each in [0, 1]."""

    signal_quality: float = Field(ge=0, le=1)
    attribution_certainty: float = Field(ge=0, le=1)
    anomaly_strength: float = Field(ge=0, le=1)


class _Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Facility(_Schema):
    id: int | None = None
    name: str
    operator: str | None = None
    type: FacilityType = "other"
    capacity_mw: float | None = None
    geom: Point
    footprint: Polygon | None = None
    watch_unit_id: int | None = None
    sources: list[str] = Field(default_factory=list)
    source_ids: dict[str, Any] = Field(default_factory=dict)


class WatchUnit(_Schema):
    """An isolated facility, or a cluster of facilities within `registry.cluster_radius_km`."""

    id: int | None = None
    kind: UnitKind
    name: str
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    member_ids: list[int] = Field(default_factory=list)
    capacity_mw: float | None = None


class Detection(_Schema):
    id: int | None = None
    detector: DetectorName
    observed_at: AwareDatetime
    watch_unit_id: int | None = None  # thermal points have none
    facility_id: int | None = None  # set only when attribution allows
    geom: Point
    footprint: Polygon | None = None
    value: float | None = None
    unit: str | None = None
    z_bg: float | None = None  # z against the null-buffer distribution
    z_self: float | None = None  # z against the unit's own history
    class_label: str | None = None
    class_prob: float | None = Field(default=None, ge=0, le=1)
    score: float = Field(default=0.0, ge=0, le=1)
    score_parts: ScoreParts | None = None
    qa: dict[str, Any] = Field(default_factory=dict)
    is_stub: bool = False  # produced by a stub or fallback; excluded from fusion, bonuses and reports
    raw_ref: str | None = None

    @computed_field
    @property
    def natural_key(self) -> str:
        lon, lat = self.geom.coordinates
        return natural_key(self.detector, self.watch_unit_id, self.observed_at, lon, lat)


class LayerProduct(_Schema):
    """Output of a layer-only detector (CH4): a map layer, never a detection."""

    layer: str
    date: date
    data_ref: str
    legend: dict[str, Any] = Field(default_factory=dict)


class Event(_Schema):
    id: int | None = None
    start_at: AwareDatetime
    end_at: AwareDatetime
    geom: GeoJSONGeometry
    watch_unit_id: int | None = None
    facility_id: int | None = None
    attribution_level: AttributionLevel | None = None
    attribution_margin: float | None = Field(default=None, ge=0, le=1)
    candidates: list[dict[str, Any]] = Field(default_factory=list)  # ranked, best first
    detection_ids: list[int] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0, le=1)
    score_parts: ScoreParts | None = None
    status: EventStatus = "open"
    anomaly_strength: float | None = None
    reassigned_from: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class EmissionEstimate(_Schema):
    id: int | None = None
    watch_unit_id: int
    species: Species
    season: Season = "all"
    period_start: date
    period_end: date
    status: EstimateStatus
    rate_kg_s: float | None = None
    stat_low: float | None = None
    stat_high: float | None = None
    rate_low: float | None = None  # total band: statistical band plus the wind term
    rate_high: float | None = None
    wind_sigma_frac: float | None = None
    lifetime_h: float | None = None
    n_days: int | None = None
    method: str
    reference_value: float | None = None
    reference_source: str | None = None
    caveats: list[str] = Field(default_factory=list)


class Exposure(_Schema):
    event_id: int
    plume_geom: Polygon
    method: ExposureMethod
    population_raw: float | None = None
    population_weighted: float | None = None
    schools: int = 0
    hospitals: int = 0
    villages: int = 0
    site_list: list[dict[str, Any]] = Field(default_factory=list)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    data_mode: str
    region: str
    database: Literal["ok", "unavailable", "skipped"]


class Region(BaseModel):
    name: str
    bbox: tuple[float, float, float, float]
