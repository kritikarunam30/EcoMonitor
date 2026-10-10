"""The synthetic field generator of tests/synthetic.py (plan Phase 2, task 6)."""

import numpy as np
import pytest
from scipy import ndimage

import synthetic

PIXEL_KM = 2.0
SHAPE = (150, 150)  # 300 km: nothing leaves the domain in the cases below
SOURCE = (150.0, 150.0)
WEST_SOURCE = (60.0, 150.0)  # 240 km of room downwind for an east-going plume
RATE = 5.0  # kg/s
LIFETIME_H = 4.0


def _steady_wind(hours: int, u: float = 4.0, v: float = 0.0) -> np.ndarray:
    return np.tile([u, v], (hours, 1))


def _correlation_length(field: np.ndarray, pixel_km: float) -> float:
    """Distance at which the autocorrelation along x falls to 1/e."""
    spectrum = np.abs(np.fft.fft2(field - field.mean())) ** 2
    acf = np.fft.ifft2(spectrum).real
    profile = acf[0, : field.shape[1] // 2] / acf[0, 0]
    below = int(np.argmax(profile < np.exp(-1)))
    x0, x1, y0, y1 = below - 1, below, profile[below - 1], profile[below]
    return (x0 + (y0 - np.exp(-1)) / (y0 - y1) * (x1 - x0)) * pixel_km


# --- background -----------------------------------------------------------------------------------


@pytest.mark.parametrize("corr_len_km", [10.0, 20.0, 40.0])
def test_background_has_the_requested_correlation_length(corr_len_km):
    field = synthetic.make_correlated_background((256, 256), PIXEL_KM, corr_len_km, sigma=2e-5, seed=1)
    assert field.std() == pytest.approx(2e-5)
    assert abs(field.mean()) < 1e-12
    assert _correlation_length(field, PIXEL_KM) == pytest.approx(corr_len_km, rel=0.15)


def test_background_times_are_independent_and_seeded():
    a = synthetic.make_correlated_background((3, 64, 64), PIXEL_KM, 10.0, 1.0, seed=5)
    b = synthetic.make_correlated_background((3, 64, 64), PIXEL_KM, 10.0, 1.0, seed=5)
    assert np.array_equal(a, b)
    assert a.shape == (3, 64, 64) and np.allclose(a.std(axis=(1, 2)), 1.0)
    assert abs(np.corrcoef(a[0].ravel(), a[1].ravel())[0, 1]) < 0.3


# --- puff model -----------------------------------------------------------------------------------


def test_puff_mass_balance():
    """Emitted mass = mass in the column + decayed mass, within 5 % (plan Phase 2)."""
    hours = 24
    field = synthetic.inject_plume(np.zeros(SHAPE), WEST_SOURCE, RATE, _steady_wind(hours, u=2.0), LIFETIME_H, PIXEL_KM)
    column_kg = field.sum() * synthetic.NO2_MOLAR_MASS_KG * (PIXEL_KM * 1000) ** 2
    _, budget = synthetic.puff_plume(SHAPE, WEST_SOURCE, RATE, _steady_wind(hours, u=2.0), LIFETIME_H, PIXEL_KM)

    emitted = RATE * hours * 3600
    assert budget["emitted_kg"] == pytest.approx(emitted)
    assert column_kg + budget["decayed_kg"] == pytest.approx(emitted, rel=0.05)
    assert column_kg == pytest.approx(budget["airborne_kg"], rel=1e-3), "the grid holds what is still in the air"
    assert (field >= 0).all()


def test_airborne_mass_matches_first_order_decay():
    """Independent of the model's own book-keeping: m(T) = Q·τ·(1 − exp(−T/τ))."""
    tau = LIFETIME_H * 3600
    for hours in (2, 6, 48):
        field = synthetic.inject_plume(np.zeros(SHAPE), SOURCE, RATE, _steady_wind(hours, u=1.0), LIFETIME_H, PIXEL_KM)
        column_kg = field.sum() * synthetic.NO2_MOLAR_MASS_KG * (PIXEL_KM * 1000) ** 2
        expected = RATE * tau * (1 - np.exp(-hours * 3600 / tau))
        assert column_kg == pytest.approx(expected, rel=0.01)


def test_mass_that_leaves_the_domain_is_reported_not_hidden():
    _, budget = synthetic.puff_plume((20, 20), (20.0, 20.0), RATE, _steady_wind(24, u=8.0), LIFETIME_H, PIXEL_KM)
    assert budget["on_grid_kg"] < 0.5 * budget["airborne_kg"]


@pytest.mark.parametrize(
    ("u", "v", "axis", "sign"), [(4, 0, "x", 1), (-4, 0, "x", -1), (0, 4, "y", 1), (0, -4, "y", -1)]
)
def test_plume_lies_downwind_of_the_source(u, v, axis, sign):
    field = synthetic.inject_plume(np.zeros(SHAPE), SOURCE, RATE, _steady_wind(12, u, v), LIFETIME_H, PIXEL_KM)
    y, x = np.indices(SHAPE)
    centre_x = (field * (x + 0.5)).sum() / field.sum() * PIXEL_KM
    centre_y = (field * (y + 0.5)).sum() / field.sum() * PIXEL_KM
    along, across = (centre_x, centre_y) if axis == "x" else (centre_y, centre_x)
    # The centre of mass of a decaying plume sits about one e-folding distance downwind: U·τ = 57.6 km.
    assert sign * (along - 150.0) == pytest.approx(4 * LIFETIME_H * 3.6, rel=0.25)
    assert across == pytest.approx(150.0, abs=0.5)
    iy, ix = np.unravel_index(field.argmax(), SHAPE)
    assert abs(ix * PIXEL_KM - 150) <= 2 * PIXEL_KM and abs(iy * PIXEL_KM - 150) <= 2 * PIXEL_KM, "peak at the source"


def test_plume_follows_a_wind_that_turns():
    """East for the old puffs, then north for the last six hours: old mass ends up north-east."""
    wind = np.vstack([_steady_wind(6, 4, 0), _steady_wind(6, 0, 4)])
    field = synthetic.inject_plume(np.zeros(SHAPE), SOURCE, RATE, wind, 24.0, PIXEL_KM)
    north_east = field[75 + 30 :, 75 + 10 :].sum()
    south = field[:74].sum()
    assert north_east > 0.2 * field.sum() and south < 1e-3 * field.sum()


def test_plume_scales_with_the_rate_and_adds_to_the_field():
    background = synthetic.make_correlated_background(SHAPE, PIXEL_KM, 20.0, 2e-5, seed=3)
    one = synthetic.inject_plume(background, SOURCE, RATE, _steady_wind(12), LIFETIME_H, PIXEL_KM)
    two = synthetic.inject_plume(background, SOURCE, 2 * RATE, _steady_wind(12), LIFETIME_H, PIXEL_KM)
    assert np.allclose(two - background, 2 * (one - background))
    assert one is not background and np.isfinite(one).all()
    assert 1e-5 < (one - background).max() < 1e-2, "a plausible NO2 enhancement in mol/m²"


def test_plume_per_day_for_a_time_stack():
    winds = np.stack([_steady_wind(12, 4, 0), _steady_wind(12, -4, 0)])
    stack = synthetic.inject_plume(np.zeros((2, *SHAPE)), SOURCE, RATE, winds, LIFETIME_H, PIXEL_KM)
    assert stack.shape == (2, *SHAPE)
    assert stack[0][:, 80:].sum() > 10 * stack[0][:, :70].sum(), "day 1 blows east"
    assert stack[1][:, :70].sum() > 10 * stack[1][:, 80:].sum(), "day 2 blows west"
    with pytest.raises(ValueError, match="time, hours, 2"):
        synthetic.inject_plume(np.zeros((2, *SHAPE)), SOURCE, RATE, _steady_wind(12), LIFETIME_H, PIXEL_KM)


def test_only_the_puff_model_exists():
    with pytest.raises(ValueError, match="puff"):
        synthetic.inject_plume(np.zeros(SHAPE), SOURCE, RATE, _steady_wind(3), LIFETIME_H, PIXEL_KM, model="emg")


# --- footprint, gaps, neighbour -------------------------------------------------------------------


def test_footprint_blur_keeps_the_mass_and_is_wider_along_track():
    grid_km = 1.0
    field = np.zeros((101, 101))
    field[50, 50] = 1.0
    blurred = synthetic.apply_footprint(field, grid_km=grid_km)
    assert blurred.sum() == pytest.approx(1.0) and blurred.max() < 0.1
    y, x = np.indices(field.shape)
    spread_ns = np.sqrt((blurred * (y - 50) ** 2).sum())
    spread_ew = np.sqrt((blurred * (x - 50) ** 2).sum())
    along_km, across_km = synthetic.TROPOMI_FOOTPRINT_KM
    assert spread_ns == pytest.approx(along_km / np.sqrt(12), rel=0.05), "the variance of a 5.5 km box"
    assert spread_ew == pytest.approx(across_km / np.sqrt(12), rel=0.05)

    stack = synthetic.apply_footprint(np.stack([field, 2 * field]), grid_km=grid_km)
    assert np.allclose(stack[0], blurred) and np.allclose(stack[1], 2 * blurred), "days are not mixed"


def test_missing_share_and_coherence():
    field = np.ones((40, 80, 80))
    coherent = synthetic.add_missing(field, 0.4, coherent=True, seed=2)
    random = synthetic.add_missing(field, 0.4, coherent=False, seed=2)
    assert np.isnan(coherent).mean() == pytest.approx(0.4, abs=0.005)
    assert np.isnan(random).mean() == pytest.approx(0.4, abs=0.005)
    assert np.isfinite(field).all(), "the input is not changed"

    def largest_patch(gaps):
        labels, n = ndimage.label(gaps)
        return np.bincount(labels.ravel())[1:].max() if n else 0

    assert largest_patch(np.isnan(coherent[0]) | np.isnan(coherent[1])) > 20 * 1  # patches, not single pixels
    per_day_coherent = np.isnan(coherent).mean(axis=(1, 2))
    per_day_random = np.isnan(random).mean(axis=(1, 2))
    assert per_day_coherent.std() > 10 * per_day_random.std(), "cloudy days and clear days"
    assert per_day_coherent.max() > 0.8 and per_day_coherent.min() < 0.1
    neighbours_missing = np.isnan(coherent[:, :, 1:]) & np.isnan(coherent[:, :, :-1])
    assert neighbours_missing.mean() > 0.3 > (np.isnan(random[:, :, 1:]) & np.isnan(random[:, :, :-1])).mean()

    assert np.isfinite(synthetic.add_missing(field, 0.0)).all()
    single = synthetic.add_missing(np.ones((80, 80)), 0.4, seed=4)
    assert np.isnan(single).mean() == pytest.approx(0.4, abs=0.01)


def test_neighbour_source_is_placed_by_distance_and_bearing():
    field = synthetic.inject_plume(np.zeros(SHAPE), WEST_SOURCE, RATE, _steady_wind(12), LIFETIME_H, PIXEL_KM)
    both, east = synthetic.add_neighbour_source(
        field, WEST_SOURCE, 15.0, 90.0, RATE, _steady_wind(12), LIFETIME_H, PIXEL_KM
    )
    assert east == pytest.approx((75.0, 150.0))
    assert both.sum() == pytest.approx(2 * field.sum(), rel=1e-6)
    _, north = synthetic.add_neighbour_source(
        field, WEST_SOURCE, 15.0, 0.0, RATE, _steady_wind(12), LIFETIME_H, PIXEL_KM
    )
    assert north == pytest.approx((60.0, 165.0))
    added = both - field
    iy, ix = np.unravel_index(added.argmax(), SHAPE)
    assert abs(ix * PIXEL_KM - 75) <= 2 * PIXEL_KM and abs(iy * PIXEL_KM - 150) <= 2 * PIXEL_KM
