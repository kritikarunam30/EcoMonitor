"""Synthetic fields for tests: correlated background, puff-model plumes, footprint blur, gaps.

The plume generator is a Lagrangian puff model. It shares nothing with the closed-form model that
Phase 5B fits to the data, so a rate recovered from these fields is not a circular result.

Conventions: fields are (ny, nx) or (time, ny, nx) arrays in mol/m², row 0 is the southern edge
(latitudes ascending, as in the plan §0.6 grids), x points east and y north. Positions are in km
from the lower-left corner of the field.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy import ndimage, special

NO2_MOLAR_MASS_KG = 0.046  # kg/mol; converts the emitted mass to a column in mol/m²
TROPOMI_FOOTPRINT_KM = (5.5, 3.5)  # along track (north-south), across track (east-west) at nadir


def _pixel_xy(pixel_km: float | Sequence[float]) -> tuple[float, float]:
    """(dx, dy) in km from a scalar or an (x, y) pair."""
    if np.isscalar(pixel_km):
        return float(pixel_km), float(pixel_km)
    dx, dy = pixel_km
    return float(dx), float(dy)


def _rng(seed: int | np.random.Generator | None) -> np.random.Generator:
    return seed if isinstance(seed, np.random.Generator) else np.random.default_rng(seed)


def make_correlated_background(
    shape: Sequence[int],
    pixel_km: float,
    corr_len_km: float,
    sigma: float,
    seed: int | np.random.Generator | None = 0,
) -> np.ndarray:
    """Gaussian random field with standard deviation `sigma` whose autocorrelation falls to 1/e at
    `corr_len_km`. A (time, ny, nx) shape gives independent fields per time. The field is periodic."""
    rng = _rng(seed)
    *lead, ny, nx = shape
    # White noise smoothed with a Gaussian kernel of width s has the autocorrelation exp(-r² / 4s²).
    s_px = corr_len_km / pixel_km / 2
    ky, kx = np.meshgrid(np.fft.fftfreq(ny), np.fft.fftfreq(nx), indexing="ij")
    kernel = np.exp(-2 * (np.pi * s_px) ** 2 * (kx**2 + ky**2))
    noise = rng.standard_normal((*lead, ny, nx))
    field = np.fft.ifft2(np.fft.fft2(noise) * kernel).real
    field -= field.mean(axis=(-2, -1), keepdims=True)
    return field / field.std(axis=(-2, -1), keepdims=True) * sigma


def puff_plume(
    shape: Sequence[int],
    src_xy: Sequence[float],
    rate_kg_s: float,
    wind_series: np.ndarray,
    lifetime_h: float,
    pixel_km: float | Sequence[float],
    *,
    release_minutes: float = 10.0,
    diffusivity_m2_s: float = 200.0,
    sigma0_km: float = 0.5,
) -> tuple[np.ndarray, dict[str, float]]:
    """Column of one source at the end of an hourly wind series, in kg/m², with a mass budget.

    `wind_series` is (hours, 2): u (east) and v (north) in m/s for each hour before the observation,
    oldest first. Puffs are released every `release_minutes`, carried by the wind of each hour until
    the observation, spread as Gaussians with sigma² = sigma0² + 2·K·age, and lose mass with the
    e-folding time `lifetime_h`. Each puff is integrated over the pixels, so mass on the grid is exact.

    The budget has `emitted_kg`, `decayed_kg`, `airborne_kg` (what should be in the air) and
    `on_grid_kg` (what the returned field holds; less than airborne when puffs left the domain).
    """
    ny, nx = shape
    dx, dy = (v * 1000 for v in _pixel_xy(pixel_km))
    wind = np.asarray(wind_series, dtype=float).reshape(-1, 2)
    total_s = len(wind) * 3600.0
    dt = release_minutes * 60.0
    release = np.arange(dt / 2, total_s, dt)  # each puff stands for the emission of one interval
    ages = total_s - release

    # Displacement from a release time to the observation: the integral of the hourly wind.
    hour_edges = np.arange(len(wind) + 1) * 3600.0
    path = np.vstack([[0.0, 0.0], np.cumsum(wind * 3600.0, axis=0)])
    travelled = np.column_stack([np.interp(release, hour_edges, path[:, k]) for k in range(2)])
    centre = np.asarray(src_xy, dtype=float) * 1000 + (path[-1] - travelled)

    emitted = rate_kg_s * dt * np.ones_like(release)
    mass = emitted * np.exp(-ages / (lifetime_h * 3600.0))
    sigma = np.sqrt((sigma0_km * 1000) ** 2 + 2 * diffusivity_m2_s * ages)

    x_edges = np.arange(nx + 1) * dx
    y_edges = np.arange(ny + 1) * dy
    # Share of each puff that falls in each column and row of pixels (the Gaussian is separable).
    share_x = np.diff(special.erf((x_edges[None, :] - centre[:, :1]) / (np.sqrt(2) * sigma[:, None])), axis=1) / 2
    share_y = np.diff(special.erf((y_edges[None, :] - centre[:, 1:]) / (np.sqrt(2) * sigma[:, None])), axis=1) / 2
    grid_kg = np.einsum("p,py,px->yx", mass, share_y, share_x)

    budget = {
        "emitted_kg": float(emitted.sum()),
        "decayed_kg": float((emitted - mass).sum()),
        "airborne_kg": float(mass.sum()),
        "on_grid_kg": float(grid_kg.sum()),
    }
    return grid_kg / (dx * dy), budget


def inject_plume(
    field: np.ndarray,
    src_xy: Sequence[float],
    rate_kg_s: float,
    wind_series: np.ndarray,
    lifetime_h: float,
    pixel_km: float | Sequence[float],
    model: str = "puff",
    *,
    molar_mass_kg: float = NO2_MOLAR_MASS_KG,
    **puff_options: float,
) -> np.ndarray:
    """Add the plume of one source to a field in mol/m² and return the new field.

    For a (ny, nx) field `wind_series` is (hours, 2). For a (time, ny, nx) field it is
    (time, hours, 2): the hours before each observation. See `puff_plume` for the model.
    """
    if model != "puff":
        raise ValueError("only the puff model is implemented; the closed-form model belongs to the fit")
    field = np.asarray(field, dtype=float)
    wind = np.asarray(wind_series, dtype=float)
    if field.ndim == 2:
        column, _ = puff_plume(field.shape, src_xy, rate_kg_s, wind, lifetime_h, pixel_km, **puff_options)
        return field + column / molar_mass_kg
    if wind.ndim != 3 or len(wind) != len(field):
        raise ValueError("a (time, ny, nx) field needs a (time, hours, 2) wind series")
    out = field.copy()
    for t in range(len(field)):
        column, _ = puff_plume(field.shape[1:], src_xy, rate_kg_s, wind[t], lifetime_h, pixel_km, **puff_options)
        out[t] += column / molar_mass_kg
    return out


def apply_footprint(
    field: np.ndarray, pixel_km: Sequence[float] = TROPOMI_FOOTPRINT_KM, *, grid_km: float | Sequence[float] = 1.0
) -> np.ndarray:
    """Blur a field to the TROPOMI footprint. `pixel_km` is the footprint (north-south, east-west);
    `grid_km` is the pixel size of the field. The box average over a footprint is approximated by a
    Gaussian of the same variance, which also works when the footprint is not a whole number of pixels.
    Apply before `add_missing`: the field must not contain NaN."""
    along_km, across_km = pixel_km
    dx, dy = _pixel_xy(grid_km)
    sigma = (along_km / dy / np.sqrt(12), across_km / dx / np.sqrt(12))
    field = np.asarray(field, dtype=float)
    return ndimage.gaussian_filter(field, sigma=(*([0] * (field.ndim - 2)), *sigma), mode="nearest")


def add_missing(
    field: np.ndarray,
    frac: float,
    coherent: bool = True,
    *,
    corr_len_px: float = 8.0,
    seed: int | np.random.Generator | None = 0,
) -> np.ndarray:
    """Set a share `frac` of the pixels to NaN.

    `coherent=True` gives cloud-like gaps: connected patches about `corr_len_px` wide, and for a
    (time, ny, nx) field days that are mostly cloudy next to days that are mostly clear.
    `coherent=False` removes single pixels at random.
    """
    rng = _rng(seed)
    out = np.array(field, dtype=float)
    if frac <= 0:
        return out
    if coherent:
        cloud = make_correlated_background(out.shape, 1.0, corr_len_px, 1.0, rng)
        if out.ndim == 3:
            cloud += rng.standard_normal((len(out), 1, 1))  # some days are cloudier than others
    else:
        cloud = rng.random(out.shape)
    out[cloud < np.quantile(cloud, frac)] = np.nan
    return out


def add_neighbour_source(
    field: np.ndarray,
    src_xy: Sequence[float],
    distance_km: float,
    bearing_deg: float,
    rate_kg_s: float,
    wind_series: np.ndarray,
    lifetime_h: float,
    pixel_km: float | Sequence[float],
    **options: float,
) -> tuple[np.ndarray, tuple[float, float]]:
    """Add a second source `distance_km` from `src_xy` at a compass bearing (0 = north, 90 = east).
    Returns the new field and the neighbour's position."""
    bearing = np.radians(bearing_deg)
    neighbour = (src_xy[0] + distance_km * np.sin(bearing), src_xy[1] + distance_km * np.cos(bearing))
    return inject_plume(field, neighbour, rate_kg_s, wind_series, lifetime_h, pixel_km, **options), neighbour
