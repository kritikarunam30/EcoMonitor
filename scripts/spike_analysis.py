"""Rough prototypes used by the Phase S spike: valid-day fractions, the null-buffer z and the SO2 window z.

Pure NumPy: arrays in, numbers out, so it is tested offline. These are measurements for
docs/SPIKE_REPORT.md, not the Phase 4 detectors, which are written and tested separately.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from app.geo.projection import local_aeqd

MAD_TO_SIGMA = 1.4826


def km_offsets(lats: np.ndarray, lons: np.ndarray, lon0: float, lat0: float) -> tuple[np.ndarray, np.ndarray]:
    """East and north offsets in km of every grid cell from (lon0, lat0), as (lat, lon) arrays."""
    to_local, _ = local_aeqd(lon0, lat0)
    lon2d, lat2d = np.meshgrid(lons, lats)
    x, y = to_local.transform(lon2d, lat2d)
    return np.asarray(x) / 1000.0, np.asarray(y) / 1000.0


def robust_sigma(values: np.ndarray) -> float:
    return float(MAD_TO_SIGMA * np.median(np.abs(values - np.median(values))))


def valid_fraction_by_month(valid: np.ndarray, days: Sequence[date], min_fraction: float) -> pd.DataFrame:
    """Per month: number of days, and how many of them have at least `min_fraction` valid pixels."""
    per_day = valid.reshape(len(days), -1).mean(axis=1)
    frame = pd.DataFrame({"month": [d.strftime("%Y-%m") for d in days], "ok": per_day >= min_fraction})
    out = frame.groupby("month")["ok"].agg(days="size", days_ok="sum").reset_index()
    out["fraction_ok"] = out["days_ok"] / out["days"]
    return out


def _buffer_mean(field: np.ndarray, mask: np.ndarray, min_valid_fraction: float) -> float | None:
    values = field[mask]
    if values.size == 0:
        return None
    ok = ~np.isnan(values)
    if ok.mean() < min_valid_fraction:
        return None
    return float(values[ok].mean())


def null_buffer_z(
    field: np.ndarray,
    x_km: np.ndarray,
    y_km: np.ndarray,
    sources_km: Sequence[tuple[float, float]],
    *,
    local_radius_km: float,
    annulus_km: tuple[float, float],
    mask_km: float,
    n_null: int,
    n_null_min_valid: int,
    min_valid_fraction: float,
    rng: np.random.Generator,
) -> dict[str, float] | None:
    """z of the mean inside the source buffers against equal-radius buffers drawn in a ring.

    `x_km`/`y_km` are offsets from the unit centroid; `sources_km` are the plants in the same frame.
    Returns None when the local buffer or too many null buffers lack valid pixels.
    """
    dist_to_source = np.min([np.hypot(x_km - sx, y_km - sy) for sx, sy in sources_km], axis=0)
    local = _buffer_mean(field, dist_to_source <= local_radius_km, min_valid_fraction)
    if local is None:
        return None

    null_means = []
    for _ in range(n_null * 10):  # some draws fall near a source or on missing data
        if len(null_means) == n_null:
            break
        radius = np.sqrt(rng.uniform(annulus_km[0] ** 2, annulus_km[1] ** 2))  # uniform over the ring's area
        angle = rng.uniform(0, 2 * np.pi)
        cx, cy = radius * np.cos(angle), radius * np.sin(angle)
        if min(np.hypot(cx - sx, cy - sy) for sx, sy in sources_km) < mask_km:
            continue
        mean = _buffer_mean(field, np.hypot(x_km - cx, y_km - cy) <= local_radius_km, min_valid_fraction)
        if mean is not None:
            null_means.append(mean)
    if len(null_means) < n_null_min_valid:
        return None

    null = np.array(null_means)
    sigma = robust_sigma(null)
    if sigma == 0:
        return None
    median = float(np.median(null))
    return {
        "local": local,
        "null_median": median,
        "null_sigma": sigma,
        "z_bg": (local - median) / sigma,
        "n_null": len(null),
    }


def downwind_enhancement(
    field: np.ndarray,
    x_km: np.ndarray,
    y_km: np.ndarray,
    u: float,
    v: float,
    *,
    along_km: float,
    across_km: float,
    min_valid_fraction: float,
) -> float | None:
    """Mean of the box 0..along_km downwind of the origin minus the mean of the mirrored upwind box."""
    speed = float(np.hypot(u, v))
    if not np.isfinite(speed) or speed == 0:
        return None
    along = (x_km * u + y_km * v) / speed
    across = (-x_km * v + y_km * u) / speed
    inside = np.abs(across) <= across_km
    down = _buffer_mean(field, inside & (along > 0) & (along <= along_km), min_valid_fraction)
    up = _buffer_mean(field, inside & (along < 0) & (along >= -along_km), min_valid_fraction)
    if down is None or up is None:
        return None
    return down - up


def so2_window_z(
    fields: np.ndarray,
    winds: Sequence[tuple[float, float]],
    x_km: np.ndarray,
    y_km: np.ndarray,
    *,
    along_km: float,
    across_km: float,
    min_valid_fraction: float,
    n_boot: int,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Bootstrap z of the wind-aligned downwind enhancement over the days of one window."""
    daily = []
    for field, (u, v) in zip(fields, winds, strict=True):
        value = downwind_enhancement(
            field, x_km, y_km, u, v, along_km=along_km, across_km=across_km, min_valid_fraction=min_valid_fraction
        )
        if value is not None:
            daily.append(value)
    result = {"n_valid_days": len(daily), "mean": float("nan"), "z": float("nan"), "p5": float("nan")}
    if len(daily) < 2:
        return result
    values = np.array(daily)
    boot = rng.choice(values, size=(n_boot, len(values)), replace=True).mean(axis=1)
    std = float(boot.std(ddof=1))
    result |= {"mean": float(values.mean()), "p5": float(np.percentile(boot, 5))}
    if std > 0:
        result["z"] = float(boot.mean() / std)
    return result
