import math
from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner import SITES, Orbit
from mission_planner.constants import MU
from mission_planner.launch_site import LaunchSite, launch_azimuth
from mission_planner.orbit import M_from_nu, kepler_E, nu_from_E, wrap_pi

EPOCH = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def test_period_leo():
    orb = Orbit.circular(400.0, 51.6, epoch=EPOCH)
    assert orb.period == pytest.approx(5553.6, abs=1.0)  # ~92.5 min, J2-corrected


def test_nodal_period_carries_the_perigee_drift():
    orb = Orbit.circular(700.0, 98.19, epoch=EPOCH)
    _, argp_dot, _ = orb.j2_rates()
    assert 1 / orb.nodal_period - 1 / orb.period == pytest.approx(argp_dot / (2 * math.pi))
    assert orb.summary()["revs_per_day"] == pytest.approx(86400.0 / orb.nodal_period, abs=1e-3)


def test_sun_synchronous_regression():
    # 98.19 deg at 700 km and 98.6 deg at 800 km are sun-synchronous:
    # RAAN regresses +0.9856 deg/day, the mean sun's rate.
    for alt, inc in ((700.0, 98.19), (800.0, 98.6)):
        raan_dot, _, _ = Orbit.circular(alt, inc, epoch=EPOCH).j2_rates()
        assert math.degrees(raan_dot) * 86400 == pytest.approx(0.9856, abs=1e-3)


def test_j2_rates_textbook():
    # Vallado: at the critical inclination the perigee stands still, and
    # the correction to mean motion vanishes at 54.7 deg.
    assert abs(Orbit.circular(400.0, 63.4349, epoch=EPOCH).j2_rates()[1]) < 1e-11
    assert abs(Orbit.circular(400.0, 54.7356, epoch=EPOCH).j2_rates()[2]) < 1e-11
    # Equatorial 400 km LEO: -1.5 J2 (RE/a)^2 n = -8.05 deg/day.
    raan_dot = Orbit.circular(400.0, 0.0, epoch=EPOCH).j2_rates()[0]
    assert math.degrees(raan_dot) * 86400 == pytest.approx(-8.05, abs=0.02)


def test_kepler_helpers_round_trip():
    for e in (0.0, 0.1, 0.74, 0.95):
        M = np.linspace(-9 * math.pi, 9 * math.pi, 7201)  # many turns, as t grows
        E = kepler_E(M, e)
        assert np.abs(E - e * np.sin(E) - M).max() < 1e-12
        nu = nu_from_E(E, e)
        back = np.array([M_from_nu(float(x), e) for x in nu])
        assert np.abs(wrap_pi(back - M)).max() < 1e-12


def test_wrap_pi_range():
    xs = np.array([-math.pi, math.pi, 3 * math.pi, -1e-12, 1e6 * math.pi])
    w = wrap_pi(xs)
    assert np.all(w >= -math.pi) and np.all(w < math.pi)
    assert wrap_pi(math.pi) == -math.pi and wrap_pi(0.5) == 0.5


def test_from_launch_site_starts_over_site():
    site = SITES["Cape Canaveral / KSC"]
    orb = Orbit.from_launch_site(site, 400.0, 28.5, epoch=EPOCH)
    lat, lon, _ = orb.subpoints(np.array([0.0]))
    assert abs(math.degrees(lat[0]) - site.lat_deg) < 0.01
    assert abs(math.degrees(lon[0]) - site.lon_deg) < 0.01


def test_from_launch_site_descending():
    site = SITES["Vandenberg"]
    orb = Orbit.from_launch_site(site, 500.0, 70.0, epoch=EPOCH, ascending=False)
    lat, lon, _ = orb.subpoints(np.array([0.0, 30.0]))
    assert abs(math.degrees(lat[0]) - site.lat_deg) < 0.01
    assert abs(math.degrees(lon[0]) - site.lon_deg) < 0.01
    assert lat[1] < lat[0]  # heading south


def test_from_launch_site_southern_and_retrograde():
    site = SITES["Mahia"]  # -39.3 deg
    for inc, asc in ((45.0, True), (45.0, False), (140.0, True)):
        orb = Orbit.from_launch_site(site, 500.0, inc, epoch=EPOCH, ascending=asc)
        lat, lon, _ = orb.subpoints(np.array([0.0, 30.0]))
        assert abs(math.degrees(lat[0]) - site.lat_deg) < 0.01, (inc, asc)
        assert abs(math.degrees(lon[0]) - site.lon_deg) < 0.01, (inc, asc)
        assert (lat[1] > lat[0]) == asc, (inc, asc)


def test_equatorial_site_can_launch_into_an_equatorial_orbit():
    orb = Orbit.from_launch_site(LaunchSite("eq", 0.0, 10.0), 400.0, 0.0, epoch=EPOCH)
    lat, lon, _ = orb.subpoints(np.array([0.0, 600.0]))
    assert abs(lat).max() < 1e-9 and abs(math.degrees(lon[0]) - 10.0) < 0.01
    with pytest.raises(ValueError):
        Orbit.from_launch_site(LaunchSite("x", 1.0, 0.0), 400.0, 0.0, epoch=EPOCH)


def test_from_launch_site_rejects_low_inclination():
    with pytest.raises(ValueError):
        Orbit.from_launch_site(SITES["Vandenberg"], 400.0, 20.0, epoch=EPOCH)


def test_launch_azimuth_due_east():
    # From KSC latitude to a 28.5 deg orbit: due east — and Earth rotation
    # doesn't change the direction when the north component is zero.
    assert abs(launch_azimuth(28.5, 28.5) - 90.0) < 1e-9
    assert abs(launch_azimuth(28.5, 28.5, v_orbit=7670.0) - 90.0) < 1e-9
    # For a 51.6 deg orbit from 28.5 deg the rotating-Earth correction
    # pulls the required azimuth north of the inertial value.
    az_inertial = launch_azimuth(28.5, 51.6)
    az_rotating = launch_azimuth(28.5, 51.6, v_orbit=7670.0)
    assert abs(az_inertial - 45.0) < 0.5
    assert az_rotating < az_inertial - 1.0


def test_orbit_launch_azimuth_uses_the_injection_speed():
    site = SITES["Cape Canaveral / KSC"]
    leo = Orbit.from_launch_site(site, 400.0, 51.6, epoch=EPOCH)
    assert leo.launch_azimuth_deg(site.lat_deg) == pytest.approx(
        launch_azimuth(site.lat_deg, 51.6, v_orbit=math.sqrt(MU / leo.a)), abs=1e-6
    )
    # GTO injected at perigee is faster than sqrt(mu/a): the correction shrinks.
    gto = Orbit.from_launch_site(
        site, inc_deg=51.6, epoch=EPOCH, perigee_km=200.0, apogee_km=35786.0
    )
    vp = math.sqrt(MU * (2 / (6378137.0 + 200e3) - 1 / gto.a))
    assert gto.launch_azimuth_deg(site.lat_deg) == pytest.approx(
        launch_azimuth(site.lat_deg, 51.6, v_orbit=vp), abs=1e-6
    )


def test_latitude_bounded_by_inclination():
    orb = Orbit.circular(400.0, 51.6, epoch=EPOCH)
    gt = orb.ground_track(2 * 5553.0, 30.0)
    assert np.degrees(np.abs(gt.lat).max()) == pytest.approx(51.6, abs=0.1)


def test_elliptic_from_launch_site_perigee_overhead():
    site = SITES["Cape Canaveral / KSC"]
    orb = Orbit.from_launch_site(site, inc_deg=51.6, epoch=EPOCH, perigee_km=200.0, apogee_km=800.0)
    assert orb.perigee_km == pytest.approx(200.0, abs=0.1)
    assert orb.apogee_km == pytest.approx(800.0, abs=0.1)
    lat, lon, r = orb.subpoints(np.array([0.0]))
    assert abs(math.degrees(lat[0]) - site.lat_deg) < 0.01
    assert abs(math.degrees(lon[0]) - site.lon_deg) < 0.01
    # delta = 0: perigee overhead at the site pass
    assert (r[0] - 6378137.0) * 1e-3 == pytest.approx(200.0, abs=0.5)


def test_elliptic_perigee_offset_180_puts_apogee_overhead():
    site = SITES["Cape Canaveral / KSC"]
    orb = Orbit.from_launch_site(
        site, inc_deg=51.6, epoch=EPOCH, perigee_km=200.0, apogee_km=800.0, perigee_offset_deg=180.0
    )
    lat, lon, r = orb.subpoints(np.array([0.0]))
    assert abs(math.degrees(lat[0]) - site.lat_deg) < 0.01  # still over site
    assert (r[0] - 6378137.0) * 1e-3 == pytest.approx(800.0, abs=0.5)


def test_apsis_times():
    orb = Orbit.from_launch_site(
        SITES["Vandenberg"],
        inc_deg=70.0,
        epoch=EPOCH,
        perigee_km=200.0,
        apogee_km=800.0,
        perigee_offset_deg=90.0,
    )
    t_p, t_a = orb.apsis_times()
    _, _, rp = orb.subpoints(np.array([t_p]))
    _, _, ra = orb.subpoints(np.array([t_a]))
    assert (rp[0] - 6378137.0) * 1e-3 == pytest.approx(200.0, abs=0.05)
    assert (ra[0] - 6378137.0) * 1e-3 == pytest.approx(800.0, abs=0.05)
    assert abs(t_a - t_p) == pytest.approx(orb.period / 2, abs=0.1)


def test_eci_state_is_consistent_with_positions_and_two_body_invariants():
    orb = Orbit.from_elements(500.0, 39868.0, 63.4, epoch=EPOCH, argp_deg=270.0)
    for t in (0.0, 1234.5, 0.37 * orb.period):
        r, v = orb.eci_state(t)
        assert np.linalg.norm(r - orb.eci_positions(np.array([t]))[0]) < 1e-6
        p = orb.a * (1 - orb.e**2)
        assert np.linalg.norm(np.cross(r, v)) == pytest.approx(math.sqrt(MU * p), rel=1e-12)
        vis_viva = 1.0 / (2.0 / np.linalg.norm(r) - np.dot(v, v) / MU)
        assert vis_viva == pytest.approx(orb.a, rel=1e-12)


def test_argument_of_latitude_and_mean_anomaly():
    orb = Orbit.circular(400.0, 51.6, u0_deg=30.0, epoch=EPOCH)
    assert math.degrees(orb.argument_of_latitude(0.0)) == pytest.approx(30.0)
    # Circular: u advances one full turn per nodal period.
    t = np.array([0.0, orb.nodal_period])
    du = orb.argument_of_latitude(t)[1] - orb.argument_of_latitude(t)[0]
    assert du == pytest.approx(2 * math.pi, rel=1e-9)
    assert orb.mean_anomaly(orb.period) - orb.m0 == pytest.approx(2 * math.pi, rel=1e-12)


def test_summary_has_all_six_elements():
    orb = Orbit.from_launch_site(
        SITES["Kourou"],
        inc_deg=6.0,
        epoch=EPOCH,
        perigee_km=250.0,
        apogee_km=35786.0,
        perigee_offset_deg=15.0,
    )
    s = orb.summary()
    for k in ("a_km", "e", "inc_deg", "raan_deg", "argp_deg", "nu0_deg", "nodal_period_s"):
        assert k in s
    assert s["e"] == pytest.approx(0.7283, abs=0.001)  # 250x35786 GTO
    assert s["nu0_deg"] == pytest.approx(-15.0, abs=0.01)
    assert 0.0 <= s["raan_deg"] < 360.0 and 0.0 <= s["argp_deg"] < 360.0


def test_circular_backward_compatible():
    site = SITES["Cape Canaveral / KSC"]
    a = Orbit.from_launch_site(site, 400.0, 28.5, epoch=EPOCH)
    b = Orbit.from_launch_site(site, inc_deg=28.5, epoch=EPOCH, perigee_km=400.0, apogee_km=400.0)
    assert a == b


def test_ground_track_rejects_bad_steps():
    orb = Orbit.circular(400.0, 28.5, epoch=EPOCH)
    with pytest.raises(ValueError):
        orb.ground_track(3600.0, 0.0)
    with pytest.raises(ValueError):
        orb.ground_track(-1.0, 30.0)
    assert len(orb.ground_track(0.0, 30.0).t) == 1


def test_from_elements_geo_parks_at_station_longitude():
    orb = Orbit.from_elements(35786.0, 35786.0, 0.0, epoch=EPOCH, node_lon_deg=-100.0)
    t = np.arange(0, 86400.0, 600.0)
    lat, lon, _ = orb.subpoints(t)
    assert np.max(np.abs(np.degrees(lat))) < 0.01
    dlon = np.degrees(np.angle(np.exp(1j * (lon - np.radians(-100.0)))))
    assert np.max(np.abs(dlon)) < 0.2  # parked at the station


def test_from_elements_molniya():
    orb = Orbit.from_elements(500.0, 39868.0, 63.4, epoch=EPOCH, argp_deg=270.0, node_lon_deg=65.0)
    # Semi-sidereal period (11 h 58 min).
    assert orb.period == pytest.approx(0.5 * 86164.1, rel=0.005)
    # Apogee dwells at the northernmost latitude (argp 270 => nu=180 at u=90).
    _, t_a = orb.apsis_times()
    lat, _, r = orb.subpoints(np.array([t_a]))
    assert np.degrees(lat[0]) == pytest.approx(63.4, abs=0.3)
    assert (r[0] - 6378137.0) * 1e-3 == pytest.approx(39868.0, rel=0.01)


def test_from_elements_node_anchor():
    # Starts at the ascending node, which sits over node_lon at epoch.
    orb = Orbit.from_elements(400.0, 400.0, 51.6, epoch=EPOCH, node_lon_deg=30.0)
    lat, lon, _ = orb.subpoints(np.array([0.0]))
    assert abs(np.degrees(lat[0])) < 0.01
    assert np.degrees(lon[0]) == pytest.approx(30.0, abs=0.01)
