"""User-facing wording: every claim, label and disclaimer comes from config/wording.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.settings import get_settings


@lru_cache
def load_wording(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def t(key: str) -> str:
    """Return the wording for `key`. An unknown key is a bug, so it raises instead of returning a default."""
    settings = get_settings()
    wording = load_wording(settings.resolve(settings.wording_path))
    try:
        return wording[key]
    except KeyError:
        raise KeyError(f"wording key '{key}' is not defined in {settings.wording_path}") from None
