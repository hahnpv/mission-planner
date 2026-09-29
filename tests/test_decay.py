from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner import Orbit
from mission_planner.atmosphere import density

EPOCH = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
DAY = 86400.0


def test_density_matches_us76_reference_values():
    # Official US Standard Atmosphere 1976 table values (kg/m^3).
    assert density(0.0) == pytest.approx(1.225, rel=1e-3)
    assert density(200e3) == pytest.approx(2.541e-10, rel=1e-2)
    assert density(400e3) == pytest.approx(2.803e-12, rel=1e-2)
    assert density(1000e3) == pytest.approx(3.561e-15, rel=1e-2)
    # Monotone decreasing through the LEO band.
    h = np.linspace(100e3, 1000e3, 500)
    rho = density(h)
    assert np.all(np.diff(rho) < 0)


def test_density_keeps_falling_above_the_table():
    # Extrapolated, not clamped: a 2000 km orbit must not see 1000 km air.
    high = density(np.array([1000e3, 1500e3, 2000e3]))
    assert np.all(np.diff(high) < 0) and high[-1] < 0.05 * high[0]
    assert density(1500e3) == density(np.array([1500e3]))[0]  # scalar and array agree


def test_iss_class_decays_slowly():
    # ~400 km, beta ~ 130 kg/m^2: nominal lifetime is months-to-a-year+.
    orb = Orbit.circular(400.0, 51.6, epoch=EPOCH)
    gt = orb.ground_track(30 * DAY, dt_s=600.0, mode="decay", beta=130.0)
    assert gt.extra["entry"] is None  # still up after 30 days
    fall_km = (gt.alt[0] - gt.alt[-1]) * 1e-3
    assert 1.0 < fall_km < 60.0  # a few km/month nominal


def test_low_orbit_decays_in_days():
    # 200 km, beta = 300: comes down within days.
    orb = Orbit.circular(200.0, 60.0, epoch=EPOCH)
    gt = orb.ground_track(20 * DAY, dt_s=300.0, mode="decay", beta=300.0)
    entry = gt.extra["entry"]
    assert entry is not None
    assert 0.2 * DAY < entry["t_s"] < 15 * DAY
    # Terminates at the 100 km interface.
    assert gt.alt[-1] * 1e-3 == pytest.approx(100.0, abs=2.0)
    # Altitude decreases monotonically.
    assert np.all(np.diff(gt.alt) < 0)


def test_lifetime_pinned_against_quadrature():
    """The RK4 lifetime must agree with a direct quadrature of the same
    da/dt, so an integrator regression shows up at the 1e-3 level."""
    from mission_planner.decay import R_FLOOR, _rates

    orb = Orbit.circular(250.0, 51.6, epoch=EPOCH)
    beta = 200.0
    gt = orb.ground_track(60 * DAY, dt_s=600.0, mode="decay", beta=beta)
    a = np.linspace(orb.a, R_FLOOR, 20001)
    dadt = np.array([_rates(x, orb.inc, beta)[0] for x in a])
    t_quad = np.trapezoid(1.0 / dadt, a)  # dt = da / (da/dt), both negative
    assert gt.extra["entry"]["t_s"] == pytest.approx(t_quad, rel=2e-3)


def test_retrograde_orbits_decay_faster():
    # The co-rotating atmosphere gives a prograde orbit less relative wind.
    pro = Orbit.circular(300.0, 30.0, epoch=EPOCH).ground_track(
        3 * DAY, 600.0, mode="decay", beta=100.0
    )
    retro = Orbit.circular(300.0, 150.0, epoch=EPOCH).ground_track(
        3 * DAY, 600.0, mode="decay", beta=100.0
    )
    assert (retro.alt[0] - retro.alt[-1]) > 1.1 * (pro.alt[0] - pro.alt[-1])


def test_decay_starts_where_kepler_starts():
    # Same subpoint at t = 0 as the Kepler track (true anomaly, not mean),
    # so switching modes in the UI does not jump.
    orb = Orbit.from_elements(300.0, 900.0, 51.6, EPOCH, argp_deg=90.0)  # e ~ 0.043
    k = orb.ground_track(600.0, 60.0)
    d = orb.ground_track(600.0, 60.0, mode="decay", beta=100.0)
    assert (
        np.degrees(abs(k.lat[0] - d.lat[0])) < 1e-6 and np.degrees(abs(k.lon[0] - d.lon[0])) < 1e-6
    )


def test_decay_requires_beta_and_a_near_circular_orbit():
    orb = Orbit.circular(300.0, 45.0, epoch=EPOCH)
    with pytest.raises(ValueError, match="beta"):
        orb.ground_track(DAY, mode="decay")
    with pytest.raises(ValueError, match="positive"):
        orb.ground_track(DAY, mode="decay", beta=-1.0)
    gto = Orbit.from_elements(250.0, 35786.0, 6.0, EPOCH)
    with pytest.raises(ValueError, match="near-circular"):
        gto.ground_track(DAY, mode="decay", beta=300.0)
    assert Orbit.from_elements(300.0, 900.0, 51.6, EPOCH).e < 0.05  # just inside the gate
