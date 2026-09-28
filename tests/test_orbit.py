import math
from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner import SITES, Orbit
from mission_planner.launch_site import launch_azimuth

EPOCH = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def test_period_leo():
    orb = Orbit.circular(400.0, 51.6, epoch=EPOCH)
    assert abs(orb.period - 5553.0) < 30.0  # ~92.5 min


def test_sun_synchronous_regression():
    # 98.6 deg / ~700 km should regress ~ +0.9856 deg/day (sun-synchronous).
    orb = Orbit.circular(700.0, 98.6, epoch=EPOCH)
    raan_dot, _, _ = orb.j2_rates()
    assert abs(math.degrees(raan_dot) * 86400 - 0.9856) < 0.05


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
    assert lat[1] < lat[0]  # heading south


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
    assert (rp[0] - 6378137.0) * 1e-3 == pytest.approx(200.0, abs=1.0)
    assert (ra[0] - 6378137.0) * 1e-3 == pytest.approx(800.0, abs=1.0)
    assert abs(abs(t_a - t_p) - orb.period / 2) < 0.02 * orb.period


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
    for k in ("a_km", "e", "inc_deg", "raan_deg", "argp_deg", "nu0_deg"):
        assert k in s
    assert s["e"] == pytest.approx(0.7283, abs=0.001)  # 250x35786 GTO
    assert s["nu0_deg"] == pytest.approx(-15.0, abs=0.01)


def test_circular_backward_compatible():
    site = SITES["Cape Canaveral / KSC"]
    a = Orbit.from_launch_site(site, 400.0, 28.5, epoch=EPOCH)
    b = Orbit.from_launch_site(site, inc_deg=28.5, epoch=EPOCH, perigee_km=400.0, apogee_km=400.0)
    assert a == b


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
