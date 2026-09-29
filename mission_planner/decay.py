"""Drag-decay propagation for near-circular orbits.

Averaged King-Hele decay: for a circular orbit under drag,

    da/dt = -F * rho(h) * sqrt(mu * a) / beta,      beta = m / (Cd * A)  [kg/m^2]

where F = (1 - omega_E * a * cos(i) / v)^2 accounts for the atmosphere
co-rotating with the Earth (the vehicle sees less relative wind on a
prograde orbit; ~0.92 at 400 km / 51.6 deg).  Integrated with RK4 alongside
the argument of latitude and RAAN (J2 secular rates re-evaluated at the
shrinking semi-major axis).  Fast angles stay analytic, so weeks-long
horizons stay cheap, and the ground track tightens and speeds up as the
orbit comes down.  Density comes from the US Standard Atmosphere 1976
extended to 1000 km (see atmosphere.py).

This is the cheap analytic backend and stops at the entry interface by
design; higher-fidelity propagators (full 3-DOF flight through reentry to
impact, say) plug in as extra modes — see plugins.py.
"""

from __future__ import annotations

import math

import numpy as np

from .atmosphere import density
from .constants import ENTRY_INTERFACE_ALT, MU, OMEGA_E, RE
from .groundtrack import GroundTrack
from .orbit import Orbit, j2_secular, subpoint_from_orbital
from .timebase import add_seconds

R_FLOOR = RE + ENTRY_INTERFACE_ALT
MAX_ECCENTRICITY = 0.05


def _rates(a: float, inc: float, beta: float) -> tuple[float, float, float]:
    """(da/dt, du/dt, draan/dt) for a circular orbit of radius `a`."""
    n = math.sqrt(MU / a**3)
    v = math.sqrt(MU / a)
    corot = (1.0 - OMEGA_E * a * math.cos(inc) / v) ** 2
    da = -corot * density(a - RE) * math.sqrt(MU * a) / beta
    raan_dot, argp_dot, dm_dot = j2_secular(a, 0.0, inc)
    return da, n + argp_dot + dm_dot, raan_dot


def propagate_decay(
    orbit: Orbit, beta: float, duration_s: float, dt_s: float = 30.0
) -> GroundTrack:
    """Propagate a near-circular orbit with drag decay; stops at 100 km.

    Returns a GroundTrack whose `extra` holds the decay profile and, when
    the orbit comes down inside the horizon, the entry epoch/subpoint.
    Starts from the same point as the Kepler track (argument of latitude
    from the true anomaly at epoch), so switching modes does not jump.
    """
    if beta <= 0:
        raise ValueError("beta must be positive [kg/m^2]")
    if orbit.e > MAX_ECCENTRICITY:
        raise ValueError(
            f"decay mode assumes near-circular orbits (e <= {MAX_ECCENTRICITY})"
            " — use a full-sim plugin mode for elliptic decay"
        )

    inc = orbit.inc
    a, u, raan = orbit.a, orbit.argp + orbit.nu0(), orbit.raan
    t = 0.0
    ts, als, us, raans = [t], [a], [u], [raan]
    entered = False

    n_out = max(1, int(round(duration_s / dt_s)))
    for _ in range(n_out):
        t_next = t + dt_s
        while t < t_next - 1e-9:
            # Adaptive substep: fine only when decay is fast (low altitude);
            # cap the per-step decay at ~3 km.
            k1 = _rates(a, inc, beta)
            h = min(t_next - t, max(10.0, 3e3 / max(abs(k1[0]), 1e-12)))
            # RK4 on (a, u, raan).
            k2 = _rates(a + 0.5 * h * k1[0], inc, beta)
            k3 = _rates(a + 0.5 * h * k2[0], inc, beta)
            k4 = _rates(a + h * k3[0], inc, beta)
            a_prev, u_prev, raan_prev, t_prev = a, u, raan, t
            a += h / 6.0 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
            u += h / 6.0 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
            raan += h / 6.0 * (k1[2] + 2 * k2[2] + 2 * k3[2] + k4[2])
            t += h
            if a <= R_FLOOR:
                # Interpolate back to the 100 km crossing.
                f = (a_prev - R_FLOOR) / max(a_prev - a, 1e-12)
                a = R_FLOOR
                u = u_prev + f * (u - u_prev)
                raan = raan_prev + f * (raan - raan_prev)
                t = t_prev + f * (t - t_prev)
                entered = True
                break
        ts.append(t)
        als.append(a)
        us.append(u)
        raans.append(raan)
        if entered:
            break

    t_arr = np.array(ts)
    a_arr = np.array(als)
    lat, lon = subpoint_from_orbital(np.array(us), np.array(raans), inc, orbit.epoch, t_arr)

    # Decimated altitude-vs-time profile for plotting; the last sample
    # always makes it in, so the profile ends where the track ends.
    step = max(1, len(t_arr) // 1500)
    keep = np.unique(np.r_[np.arange(0, len(t_arr), step), len(t_arr) - 1])
    extra = {
        "decay_profile": {
            "t": t_arr[keep].round(1).tolist(),
            "alt_km": ((a_arr[keep] - RE) * 1e-3).round(2).tolist(),
        },
        "entry": None,
    }
    if entered:
        extra["entry"] = {
            "epoch_utc": add_seconds(orbit.epoch, t_arr[-1]).isoformat(),
            "t_s": float(t_arr[-1]),
            "lat_deg": round(float(np.degrees(lat[-1])), 3),
            "lon_deg": round(float(np.degrees(lon[-1])), 3),
        }

    return GroundTrack(epoch=orbit.epoch, t=t_arr, lat=lat, lon=lon, alt=a_arr - RE, extra=extra)
