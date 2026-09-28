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


def test_decay_requires_beta():
    orb = Orbit.circular(300.0, 45.0, epoch=EPOCH)
    with pytest.raises(ValueError):
        orb.ground_track(DAY, mode="decay")
