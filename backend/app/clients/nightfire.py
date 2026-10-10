"""VIIRS Nightfire (Earth Observation Group): optional, licence-gated (plan v2.1).

Reads the nightly CSV files a person placed in data/raw/nightfire/. Nothing here may stop the
pipeline: without files the client reports "unavailable" and the caller falls back to another
flaring source. `EOG_*` variables are never required.

Not verified by the spike (Phase S did not test Nightfire):
  - the column names of the nightly files. Columns are found by pattern (latitude, longitude,
    black-body temperature, scan time); a file without them is skipped and named in the note.
  - TODO(needs Phase S): the scripted download with EOG_CLIENT_ID / EOG_CLIENT_SECRET. Its endpoints
    were never probed, so no download is attempted; with credentials set and no files on disk the
    note says so.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from app.clients.base import Bbox, data_mode, fixture_paths
from app.settings import get_settings

COLUMNS = ["lon", "lat", "observed_at", "temp_k", "source_file"]
PATTERNS = {"lat": r"^lat", "lon": r"^lon", "temp_k": r"^temp_bb", "observed_at": r"^date_mscan"}


def _find(columns: pd.Index, pattern: str) -> str | None:
    return next((c for c in columns if re.match(pattern, str(c), re.I)), None)


def get_nightfire(bbox: Bbox, start: date, end: date) -> tuple[pd.DataFrame | None, str]:
    """Nightfire detections in a bbox and UTC day range as (rows, note). `rows` is None when
    Nightfire is unavailable; the note then says why. Never raises."""
    try:
        settings = get_settings()
        if data_mode() == "fixture":
            paths = fixture_paths("nightfire.csv")
        else:
            folder = settings.resolve(settings.nightfire_dir)
            paths = sorted(folder.glob("*.csv*")) if folder.exists() else []
        if not paths:
            has_credentials = bool(settings.eog_client_id and settings.eog_client_secret)
            return None, (
                "Nightfire unavailable: no nightly files on disk"
                + ("; EOG credentials are set, but scripted download is not implemented" if has_credentials else "")
            )

        west, south, east, north = bbox
        frames, skipped = [], []
        for path in paths:
            raw = pd.read_csv(path)
            names = {key: _find(raw.columns, pattern) for key, pattern in PATTERNS.items()}
            if None in (names["lat"], names["lon"], names["observed_at"]):
                skipped.append(path.name)
                continue
            frame = pd.DataFrame(
                {
                    "lon": pd.to_numeric(raw[names["lon"]], errors="coerce"),
                    "lat": pd.to_numeric(raw[names["lat"]], errors="coerce"),
                    "observed_at": pd.to_datetime(raw[names["observed_at"]], errors="coerce", utc=True),
                    "temp_k": pd.to_numeric(raw[names["temp_k"]], errors="coerce") if names["temp_k"] else float("nan"),
                    "source_file": path.name,
                }
            )
            days = frame["observed_at"].dt.date
            inside = frame["lon"].between(west, east) & frame["lat"].between(south, north)
            frames.append(frame[inside & (days >= start) & (days <= end)])
        if not frames:
            return None, f"Nightfire unavailable: no usable file (columns not recognised in {skipped})"
        note = f"{len(frames)} Nightfire files read" + (f"; skipped {skipped}" if skipped else "")
        return pd.concat(frames, ignore_index=True)[COLUMNS], note
    except Exception as exc:
        return None, f"Nightfire unavailable: {str(exc)[:200]}"
