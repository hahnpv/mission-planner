import math
from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner.constants import OMEGA_E
from mission_planner.timebase import earth_rotation_rad, gmst_rad, julian_date


def test_julian_date_j2000():
    assert julian_date(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)) == 2451545.0


def test_julian_date_known():
    # Vallado ex. 3-4: 1996-10-26 14:20:00 UTC -> JD 2450383.09722222
    jd = julian_date(datetime(1996, 10, 26, 14, 20, 0, tzinfo=timezone.utc))
    assert abs(jd - 2450383.0972222222) < 1e-8


def test_julian_date_across_leap_days_and_centuries():
    # Against the proleptic-Gregorian ordinal: JD = ordinal + 1721424.5.
    for d in (
        datetime(2024, 2, 29),
        datetime(2024, 3, 1),
        datetime(1900, 3, 1),
        datetime(2100, 2, 28),
    ):
        assert julian_date(d) == d.toordinal() + 1721424.5


def test_gmst_j2000():
    # GMST at J2000.0 epoch is 280.4606 deg.
    g = math.degrees(gmst_rad(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)))
    assert abs(g - 280.4606) < 1e-3


def test_gmst_advances_at_sidereal_rate():
    g0 = gmst_rad(datetime(2026, 3, 1, 0, tzinfo=timezone.utc))
    g1 = gmst_rad(datetime(2026, 3, 2, 0, tzinfo=timezone.utc))
    # One solar day advances GMST by ~0.9856 deg beyond a full turn.
    adv = math.degrees((g1 - g0) % (2 * math.pi))
    assert abs(adv - 0.9856) < 1e-3


def test_gmst_away_from_j2000():
    # Meeus, 1987-04-10 19:21:00 UT: apparent sidereal time 8h34m57.09s;
    # mean differs by the equation of the equinoxes (~ -0.23 s here).
    g = math.degrees(gmst_rad(datetime(1987, 4, 10, 19, 21, tzinfo=timezone.utc)))
    assert g == pytest.approx(128.7378734, abs=1e-4)


def test_naive_datetime_treated_as_utc():
    aware = gmst_rad(datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc))
    naive = gmst_rad(datetime(2026, 8, 21, 6, 0))
    assert aware == naive


def test_earth_rotation_is_gmst_plus_rate():
    epoch = datetime(2026, 8, 21, tzinfo=timezone.utc)
    t = np.array([0.0, 3600.0])
    theta = earth_rotation_rad(epoch, t)
    assert theta[0] == gmst_rad(epoch)
    assert theta[1] - theta[0] == pytest.approx(OMEGA_E * 3600.0, rel=1e-12)
