"""NASA FIRMS active-fire detections (VIIRS 375 m): near-real-time products for the last weeks,
the standard-processing product for history (plan Phase 2, task 3).

Source names, their columns and the largest day range per request (5) are the ones the spike
confirmed (config/sources.yaml). The key never appears in an error message or a cache file name.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from io import StringIO

import httpx
import pandas as pd

from app.clients.base import Bbox, cached, data_mode, fixture_paths, retry
from app.settings import get_settings

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov"
PAUSE_SECONDS = 0.5  # between area requests; the key allows 5000 transactions per 10 minutes


def firms_get(path: str, map_key: str, timeout_s: int = 120) -> httpx.Response:
    """GET a FIRMS URL. `path` contains the literal text {key}; the key never appears in errors."""
    try:
        return httpx.get(f"{FIRMS_BASE}{path.format(key=map_key)}", timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise RuntimeError(str(exc).replace(map_key, "***")) from None


def _map_key() -> str:
    key = get_settings().firms_map_key
    if not key:
        raise RuntimeError("FIRMS_MAP_KEY is not set in .env")
    return key


def area_rows(source: str, bbox: Bbox, day_range: int, start: date) -> pd.DataFrame:
    """One FIRMS area request. Raises with the response text (rate-limit messages included) when
    FIRMS does not return a CSV table."""
    key = _map_key()
    area = ",".join(f"{c:.4f}" for c in bbox)
    response = firms_get(f"/api/area/csv/{{key}}/{source}/{area}/{day_range}/{start.isoformat()}", key)
    text = response.text
    if response.status_code != 200 or "latitude" not in text.splitlines()[0]:
        raise RuntimeError(f"FIRMS HTTP {response.status_code}: {text[:200]}".replace(key, "***"))
    time.sleep(PAUSE_SECONDS)
    return pd.read_csv(StringIO(text))


def _parse_range(text: str | None) -> tuple[date, date] | None:
    if not text:
        return None
    first, last = text.split(" to ")
    return date.fromisoformat(first), date.fromisoformat(last)


def availability() -> dict[str, tuple[date, date]]:
    """First and last day each source can deliver. Live: asked from FIRMS once a day (the standard
    product moves forward and the near-real-time ones are trimmed). Otherwise, and when the request
    fails, the ranges the spike recorded."""
    known = {s: _parse_range(entry.get("available")) for s, entry in get_settings().sources["firms"].items()}
    known = {s: r for s, r in known.items() if r}
    if data_mode() != "live":
        return known

    def fetch() -> dict[str, list[str]]:
        listing = firms_get("/api/data_availability/csv/{key}/all", _map_key())
        rows = [line.split(",") for line in listing.text.splitlines()[1:]]
        return {r[0]: [r[1], r[2]] for r in rows if len(r) >= 3}

    try:
        listed = cached("firms", ["availability", datetime.now(UTC).date()], "json", lambda: retry(fetch))
        return known | {s: (date.fromisoformat(a), date.fromisoformat(b)) for s, (a, b) in listed.items() if s in known}
    except Exception:
        return known


def _finish(rows: pd.DataFrame, bbox: Bbox, start: date, end: date) -> pd.DataFrame:
    """Clip to the request and add `acq_datetime` (UTC) from the date and the HHMM time."""
    west, south, east, north = bbox
    days = pd.to_datetime(rows["acq_date"]).dt.date
    keep = (
        rows["longitude"].between(west, east) & rows["latitude"].between(south, north) & (days >= start) & (days <= end)
    )
    rows = rows[keep].drop_duplicates().reset_index(drop=True)
    hhmm = rows["acq_time"].astype(int).astype(str).str.zfill(4)
    rows["acq_datetime"] = pd.to_datetime(rows["acq_date"].astype(str) + " " + hhmm, format="%Y-%m-%d %H%M", utc=True)
    return rows


def get_firms(bbox: Bbox, start: date, end: date, sources: Sequence[str] | None = None) -> pd.DataFrame:
    """Detections inside a bbox from `start` to `end` (UTC days, both included): the FIRMS columns
    as delivered, plus `source` and `acq_datetime`. `sources` defaults to every source of the spike;
    each is asked only for the days it can deliver."""
    spec = get_settings().sources["firms"]
    wanted = list(sources) if sources is not None else list(spec)
    unknown = [s for s in wanted if s not in spec]
    if unknown:
        raise ValueError(f"FIRMS sources {unknown} were not confirmed by the spike (config/sources.yaml)")
    empty = pd.DataFrame(columns=list(dict.fromkeys(c for s in wanted for c in spec[s]["columns"])) + ["source"])

    if data_mode() == "fixture":
        frames = [pd.read_csv(path) for path in fixture_paths("firms.csv")]
        rows = pd.concat([f[f["source"].isin(wanted)] for f in frames], ignore_index=True) if frames else empty
        return _finish(rows, bbox, start, end)

    ranges = availability()
    frames = []
    for source in wanted:
        if source not in ranges:
            continue
        first, last = max(start, ranges[source][0]), min(end, ranges[source][1])
        step = spec[source]["day_range"]
        while first <= last:
            n = min(step, (last - first).days + 1)
            frame = cached(
                "firms",
                [source, list(bbox), first, n],
                "parquet",
                lambda source=source, first=first, n=n: retry(lambda: area_rows(source, bbox, n, first)),
                data_end=first + timedelta(days=n - 1),
            )
            frames.append(frame.assign(source=source))
            first += timedelta(days=n)
    frames = [f for f in frames if not f.empty]
    return _finish(pd.concat(frames, ignore_index=True) if frames else empty, bbox, start, end)


def night_only(rows: pd.DataFrame) -> pd.DataFrame:
    """Night-time detections (`daynight` is N); flares and furnaces are looked for at night."""
    return rows[rows["daynight"].astype(str).str.upper().str.startswith("N")]
