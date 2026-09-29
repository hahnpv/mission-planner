"""UTC <-> Julian date <-> GMST.

GMST uses the IAU-1982 polynomial, good to well under a second of arc over
decades around J2000 — far tighter than anything else in a planning tool
that ignores polar motion and UT1-UTC (< 1 s, i.e. < 0.005 deg of Earth
rotation).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .constants import OMEGA_E

JD_J2000 = 2451545.0
JULIAN_CENTURY = 36525.0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC (naive input is assumed UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def julian_date(dt: datetime) -> float:
    """UTC datetime -> Julian date (fractional)."""
    dt = as_utc(dt)
    y, m = dt.year, dt.month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    day_frac = (dt.hour + dt.minute / 60.0 + (dt.second + dt.microsecond * 1e-6) / 3600.0) / 24.0
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + dt.day + b - 1524.5 + day_frac
    return jd


def gmst_rad(dt: datetime) -> float:
    """Greenwich mean sidereal time [rad, 0..2pi) at a UTC datetime (IAU-82)."""
    jd = julian_date(dt)
    t = (jd - JD_J2000) / JULIAN_CENTURY
    # Seconds of sidereal time (Vallado eq. 3-47).
    gmst_s = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t
        + 0.093104 * t * t
        - 6.2e-6 * t * t * t
    )
    gmst = (gmst_s % 86400.0) / 240.0  # seconds -> degrees (360/86400)
    return math.radians(gmst % 360.0)


def earth_rotation_rad(epoch: datetime, t):
    """Earth rotation angle [rad] at seconds-past-`epoch` `t` (scalar or
    array): GMST at the epoch advanced at the IERS rate.  Subtract it from an
    inertial longitude to get the earth-fixed one."""
    return gmst_rad(epoch) + OMEGA_E * t


def add_seconds(epoch: datetime, seconds: float) -> datetime:
    return as_utc(epoch) + timedelta(seconds=float(seconds))
