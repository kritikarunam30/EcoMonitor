"""Shared plumbing of the data clients: data mode, fixture files, the on-disk cache and retries.

Every client works the same way (plan Phase 2):

    fixture  read tests/fixtures/ (the recorded slice of the region first, then synthetic/); never the network
    live     read data/cache/<source>/<key>.<ext>; on a miss call the service and write the cache
    replay   read the cache only; a miss is an error (the demo replay of Phase 13 builds on this)
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
import xarray as xr

from app.settings import get_settings

T = TypeVar("T")

RETRYABLE = re.compile(r"429|500|502|503|504|quota|too many|rate limit|deadline|timed? ?out|unavailable", re.I)
Bbox = Sequence[float]  # west, south, east, north in WGS84


class DataUnavailable(RuntimeError):
    """The source has nothing for this request in the current data mode (no fixture, no cache, no access)."""


def data_mode() -> str:
    return get_settings().data_mode


def retry(fn: Callable[[], T], tries: int = 5, base_seconds: float = 2.0) -> T:
    """Call `fn`, retrying quota and server errors with exponential backoff and jitter.

    The last error is raised unchanged, so the service's own quota text reaches the caller.
    """
    for attempt in range(tries):
        try:
            return fn()
        except Exception as exc:
            if attempt == tries - 1 or not RETRYABLE.search(str(exc)):
                raise
            time.sleep(base_seconds * 2**attempt + random.uniform(0, 1))
    raise AssertionError("unreachable")


# --- fixtures -------------------------------------------------------------------------------------


def fixture_paths(name: str) -> list[Path]:
    """Every fixture file of this name: the recorded slice of the configured region first, then synthetic/."""
    settings = get_settings()
    root = settings.resolve(settings.fixture_dir)
    folders = (f"real_{settings.config.region.name}", "synthetic")
    return [root / folder / name for folder in folders if (root / folder / name).exists()]


def fixture_path(name: str) -> Path:
    """A fixture file: the recorded slice of the configured region first, then the synthetic folder."""
    paths = fixture_paths(name)
    if not paths:
        settings = get_settings()
        raise DataUnavailable(f"no fixture '{name}' under {settings.resolve(settings.fixture_dir)} (DATA_MODE=fixture)")
    return paths[0]


# --- cache ----------------------------------------------------------------------------------------


def cache_path(source: str, parts: Sequence[Any], ext: str) -> Path:
    """data/cache/<source>/<key>.<ext>. The key is readable and ends in a hash of all parts."""
    text = json.dumps([_plain(p) for p in parts], sort_keys=True)
    words = [re.sub(r"[^A-Za-z0-9.-]+", "-", str(_plain(p))).strip("-") for p in parts if isinstance(p, str | date)]
    key = "_".join([*(w for w in words if w), hashlib.sha1(text.encode()).hexdigest()[:10]])[:120]
    settings = get_settings()
    return settings.resolve(settings.cache_dir) / source / f"{key}.{ext}"


def _plain(value: Any) -> Any:
    if isinstance(value, date | datetime | pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


def is_settled(path: Path, data_end: date | None) -> bool:
    """Whether a cache file can be trusted for data up to `data_end`.

    Satellite products for the last days are still being filled in (offline NO2 arrives about nine
    days late). A file written less than `schedule.rerun_previous_days` after `data_end` is fetched again.
    """
    if not path.exists():
        return False
    if data_end is None:
        return True
    settle_days = get_settings().config.schedule["rerun_previous_days"]
    written = datetime.fromtimestamp(path.stat().st_mtime).date()
    return written > data_end + timedelta(days=settle_days)


def read_file(path: Path) -> Any:
    if path.suffix == ".nc":
        with xr.open_dataset(path) as ds:
            return ds.load()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")  # a crashed write never leaves a half file under the real name
    if path.suffix == ".nc":
        encoding = {v: {"zlib": True, "complevel": 4} for v in value.data_vars if value[v].dtype.kind in "fiub"}
        value.to_netcdf(tmp, encoding=encoding)
    elif path.suffix == ".parquet":
        value.to_parquet(tmp, index=False)
    else:
        tmp.write_text(json.dumps(value), encoding="utf-8")
    tmp.replace(path)


def cached(source: str, parts: Sequence[Any], ext: str, fetch: Callable[[], T], *, data_end: date | None = None) -> T:
    """Read data/cache/<source>/<key>.<ext> (nc → Dataset, parquet → DataFrame, json), or fetch and write it.

    In live mode a file that is not yet settled (see `is_settled`) is fetched again; if that fetch
    fails, the error is raised. In replay mode the file is read as it is and `fetch` is never called.
    """
    path = cache_path(source, parts, ext)
    mode = data_mode()
    if mode == "replay":
        if not path.exists():
            raise DataUnavailable(f"{path} is not in the cache (DATA_MODE=replay)")
        return read_file(path)
    if mode != "live":
        raise DataUnavailable(f"{source}: the network is used only with DATA_MODE=live (now: {mode})")
    if is_settled(path, data_end):
        return read_file(path)
    value = fetch()
    write_file(path, value)
    return value


def days_between(start: date, end: date) -> list[date]:
    """Calendar days from start to end, both included."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
