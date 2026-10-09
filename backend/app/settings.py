"""Application settings: secrets from the environment / .env, everything else from config/settings.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class RegionConfig(BaseModel):
    name: str
    bbox: tuple[float, float, float, float]
    geojson: str

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        min_lon, min_lat, max_lon, max_lat = v
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError(f"invalid bbox {v}")
        return v


class AppConfig(BaseModel):
    """Typed view of settings.yaml (plan §0.10). Sections not yet used by code stay as plain dicts."""

    region: RegionConfig
    registry: dict[str, Any] = {}
    detect: dict[str, Any] = {}
    flaring: dict[str, Any] = {}
    wind: dict[str, Any] = {}
    attribute: dict[str, Any] = {}
    fusion: dict[str, Any] = {}
    score: dict[str, Any] = {}
    emission: dict[str, Any] = {}
    baseline: dict[str, Any] = {}
    impact: dict[str, Any] = {}
    thermal: dict[str, Any] = {}
    schedule: dict[str, Any] = {}
    alerts: dict[str, Any] = {}


class Settings(BaseSettings):
    """Values from the environment / .env. Phases add fields here as they need keys
    (Earth Engine, CDS and FIRMS in Phase 2, SMTP in Phase 12); .env.example lists them all."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    data_mode: Literal["live", "fixture", "replay"] = "fixture"
    database_url: str = "postgresql+psycopg://emissions:emissions@localhost:5432/emissions"
    config_path: Path = Path("config/settings.yaml")
    wording_path: Path = Path("config/wording.yaml")
    # Empty means "not configured": require_admin then refuses every request.
    admin_token: str = ""

    def resolve(self, path: str | Path) -> Path:
        """Resolve a repo-relative path from config to an absolute path."""
        p = Path(path)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def config(self) -> AppConfig:
        return load_config(self.resolve(self.config_path))


@lru_cache
def load_config(path: Path) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        return AppConfig.model_validate(yaml.safe_load(f))


@lru_cache
def get_settings() -> Settings:
    return Settings()
