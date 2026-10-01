import math
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
    # ~400 km, beta ~ 130 kg/m^2: a few km a month at this (quiet-sun) density.
    orb = Orbit.circular(400.0, 51.6, epoch=EPOCH)
    gt = orb.ground_track(30 * DAY, dt_s=600.0, mode="decay", beta=130.0)
    assert gt.extra["entry"] is None  # still up after 30 days
    fall_km = (gt.alt[0] - gt.alt[-1]) * 1e-3
    assert fall_km == pytest.approx(2.7, rel=0.3)  # pinned: a 2x density change would show
    # The plot profile is decimated to ~1500-3000 points and ends where the track does.
    p = gt.extra["decay_profile"]
    n, step = len(gt.t), max(1, len(gt.t) // 1500)
    assert len(p["t"]) <= n // step + 1 < n and p["t"][-1] == gt.t[-1]
    assert p["alt_km"][0] == pytest.approx(400.0, abs=0.01)


def test_low_orbit_decays_in_days():
    # 200 km, beta = 300: comes down within a week.
    orb = Orbit.circular(200.0, 60.0, epoch=EPOCH)
    gt = orb.ground_track(20 * DAY, dt_s=300.0, mode="decay", beta=300.0)
    entry = gt.extra["entry"]
    assert entry is not None
    assert entry["t_s"] == pytest.approx(6.9 * DAY, rel=0.3)
    assert entry["t_s"] == gt.t[-1] and abs(entry["lat_deg"]) <= 60.0  # inside the inclination
    assert entry["epoch_utc"].startswith("2026-08-27T") and -180 <= entry["lon_deg"] <= 180
    # Terminates at the 100 km interface.
    assert gt.alt[-1] * 1e-3 == pytest.approx(100.0, abs=2.0)
    # Altitude decreases monotonically.
    assert np.all(np.diff(gt.alt) < 0)


def test_decay_samples_are_the_kepler_samples():
    orb = Orbit.circular(300.0, 45.0, epoch=EPOCH)
    for duration in (105.0, 120.0, 0.0):
        k = orb.ground_track(duration, 30.0).t
        d = orb.ground_track(duration, 30.0, mode="decay", beta=100.0).t
        assert d.tolist() == k.tolist(), duration
    assert orb.ground_track(105.0, 30.0, mode="decay", beta=100.0).t.tolist() == [0, 30, 60, 90]
    assert orb.ground_track(0.0, 30.0, mode="decay", beta=100.0).t.tolist() == [0.0]


def test_lifetime_pinned_against_quadrature():
    """The RK4 lifetime must agree with a direct quadrature of the same
    da/dt, so an integrator regression shows up at the 1e-3 level."""
    from mission_planner.decay import R_FLOOR, _rates

    orb = Orbit.circular(250.0, 51.6, epoch=EPOCH)
    beta = 200.0
    gt = orb.ground_track(60 * DAY, dt_s=600.0, mode="decay", beta=beta)
    a = np.linspace(orb.a, R_FLOOR, 20001)
    dadt = np.array([_rates(x, 0.0, orb.inc, beta)[0] for x in a])
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


def test_decay_requires_beta_a_moderate_eccentricity_and_a_perigee_above_the_interface():
    orb = Orbit.circular(300.0, 45.0, epoch=EPOCH)
    with pytest.raises(ValueError, match="beta"):
        orb.ground_track(DAY, mode="decay")
    with pytest.raises(ValueError, match="positive"):
        orb.ground_track(DAY, mode="decay", beta=-1.0)
    gto = Orbit.from_elements(250.0, 35786.0, 6.0, EPOCH)
    with pytest.raises(ValueError, match=r"e <= 0\.2"):
        gto.ground_track(DAY, mode="decay", beta=300.0)
    Orbit.from_elements(300.0, 3500.0, 51.6, EPOCH).ground_track(600.0, mode="decay", beta=300.0)
    low = Orbit.from_elements(90.0, 400.0, 51.6, EPOCH)
    with pytest.raises(ValueError, match="starts above the 100 km entry interface .*90 km"):
        low.ground_track(DAY, mode="decay", beta=300.0)


def test_king_hele_series_matches_the_exact_integrals(monkeypatch):
    """In an exponential atmosphere the series is King-Hele's expansion of
    the exact per-revolution integrals: equal to O(e^4)."""
    from scipy.integrate import quad

    import mission_planner.decay as dec
    from mission_planner.constants import MU

    H, rho_p = 40e3, 1e-10
    monkeypatch.setattr(dec, "_scale_height_above", lambda alt: H)
    monkeypatch.setattr(dec, "density", lambda alt: rho_p)
    monkeypatch.setattr(dec, "OMEGA_E", 0.0)  # non-rotating: delta = 1 / beta
    beta = 100.0
    for e in (0.0, 0.05, 0.2):
        a = (6578e3) / (1 - e)
        c = a * e / H
        rho = lambda E: rho_p * math.exp(-c * (1 - math.cos(E)))  # noqa: E731
        da = (
            -(a * a / beta)
            * quad(
                lambda E: rho(E) * (1 + e * math.cos(E)) ** 1.5 / (1 - e * math.cos(E)) ** 0.5,
                0,
                2 * math.pi,
            )[0]
        )
        de = (
            -(a * (1 - e * e) / beta)
            * quad(
                lambda E: (
                    rho(E) * math.cos(E) * math.sqrt((1 + e * math.cos(E)) / (1 - e * math.cos(E)))
                ),
                0,
                2 * math.pi,
            )[0]
        )
        period = 2 * math.pi * math.sqrt(a**3 / MU)
        got_da, got_de = dec._rates(a, e, 0.9, beta)
        assert got_da * period == pytest.approx(da, rel=2e-3)
        assert got_de * period == pytest.approx(de, rel=2e-3, abs=1e-15)


@pytest.mark.parametrize(
    "hp, ha, inc, beta", [(200.0, 1200.0, 51.6, 100.0), (250.0, 3500.0, 30.0, 50.0)]
)
def test_king_hele_rates_agree_with_direct_integration(hp, ha, inc, beta):
    """Two-body + drag in the rotating US76 atmosphere, integrated directly
    for a few revolutions from apogee: the averaged rates predict the
    change in a and e to a few percent."""
    from scipy.integrate import solve_ivp

    from mission_planner.constants import MU, OMEGA_E, RE
    from mission_planner.decay import _rates

    orb = Orbit.from_elements(hp, ha, inc, EPOCH, nu0_deg=180.0)
    w = np.array([0.0, 0.0, OMEGA_E])

    def f(t, y):
        r, v = y[:3], y[3:]
        rn = np.linalg.norm(r)
        vr = v - np.cross(w, r)
        return np.r_[v, -MU * r / rn**3 - 0.5 * density(rn - RE) * np.linalg.norm(vr) * vr / beta]

    span = 5 * orb.period
    y = solve_ivp(
        f, (0, span), np.r_[orb.eci_state(0.0)], rtol=1e-10, atol=1e-6, method="DOP853"
    ).y[:, -1]
    back = Orbit.from_state(y[:3], y[3:], EPOCH)
    da, de = _rates(orb.a, orb.e, orb.inc, beta)
    assert da * span == pytest.approx(back.a - orb.a, rel=0.05)
    assert de * span == pytest.approx(back.e - orb.e, rel=0.05)


def test_elliptic_orbit_circularizes_then_enters():
    # Drag acts at perigee: the apogee comes down, the perigee barely moves.
    orb = Orbit.from_elements(160.0, 600.0, 51.6, EPOCH)
    gt = orb.ground_track(30 * DAY, dt_s=300.0, mode="decay", beta=100.0)
    p = gt.extra["decay_profile"]
    peri, apo = np.array(p["perigee_km"]), np.array(p["apogee_km"])
    assert gt.extra["entry"] is not None
    assert apo[0] - apo[-1] > 450.0  # from 600 km down to the interface
    half = len(peri) // 2
    assert abs(peri[half] - peri[0]) < 20.0  # meanwhile perigee holds
    assert (
        peri[-1] == pytest.approx(100.0, abs=1.0) and apo[-1] - peri[-1] < 20.0
    )  # circular at the end
    # The track's altitude swings between the apsides at the start.
    first_rev = gt.t < orb.period
    assert gt.alt[first_rev].min() * 1e-3 == pytest.approx(160.0, abs=5.0)
    assert gt.alt[first_rev].max() * 1e-3 == pytest.approx(600.0, abs=5.0)
