import math
from datetime import datetime, timezone

from mission_planner.timebase import gmst_rad, julian_date


def test_julian_date_j2000():
    assert julian_date(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)) == 2451545.0


def test_julian_date_known():
    # Vallado ex. 3-4: 1996-10-26 14:20:00 UTC -> JD 2450383.09722222
    jd = julian_date(datetime(1996, 10, 26, 14, 20, 0, tzinfo=timezone.utc))
    assert abs(jd - 2450383.0972222222) < 1e-8


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


def test_naive_datetime_treated_as_utc():
    aware = gmst_rad(datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc))
    naive = gmst_rad(datetime(2026, 8, 21, 6, 0))
    assert aware == naive
