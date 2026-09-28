"""Drag-decay propagation for near-circular orbits.

Averaged King-Hele decay: for a circular orbit under drag,

    da/dt = -rho(h) * sqrt(mu * a) / beta,      beta = m / (Cd * A)  [kg/m^2]

integrated with RK4 alongside the argument of latitude and RAAN (J2 secular
rates re-evaluated at the shrinking semi-major axis).  Fast angles stay
analytic, so weeks-long horizons stay cheap, and the ground track tightens
and speeds up as the orbit comes down.  Density comes from the US Standard
Atmosphere 1976 extended to 1000 km (see atmosphere.py).

This is the cheap analytic backend and stops at the entry interface by
design; higher-fidelity propagators (full 3-DOF flight through reentry to
impact, say) plug in as extra modes — see plugins.py.
"""

from __future__ import annotations

import math

import numpy as np

from .atmosphere import density
from .constants import ENTRY_INTERFACE_ALT, J2, MU, OMEGA_E, RE
from .groundtrack import GroundTrack
from .orbit import Orbit, wrap_pi
from .timebase import add_seconds, gmst_rad

R_FLOOR = RE + ENTRY_INTERFACE_ALT


def _rates(a: float, inc: float, beta: float) -> tuple[float, float, float]:
    """(da/dt, du/dt, draan/dt) for a circular orbit of radius `a`."""
    n = math.sqrt(MU / a**3)
    rho = density(a - RE)
    da = -rho * math.sqrt(MU * a) / beta
    k = 1.5 * J2 * (RE / a) ** 2 * n
    ci = math.cos(inc)
    raan_dot = -k * ci
    # du/dt = n + argp_dot + dM_dot for e = 0.
    du = n + 0.5 * k * (5.0 * ci * ci - 1.0) + 0.5 * k * (3.0 * ci * ci - 1.0)
    return da, du, raan_dot


def propagate_decay(
    orbit: Orbit, beta: float, duration_s: float, dt_s: float = 30.0
) -> GroundTrack:
    """Propagate a near-circular orbit with drag decay; stops at 100 km.

    Returns a GroundTrack whose `extra` holds the decay profile and, when
    the orbit comes down inside the horizon, the entry epoch/subpoint.
    """
    if beta <= 0:
        raise ValueError("beta must be positive [kg/m^2]")
    if orbit.e > 0.05:
        raise ValueError(
            "decay mode assumes near-circular orbits (e <= 0.05)"
            " — use a full-sim plugin mode for elliptic decay"
        )

    inc = orbit.inc
    a, u, raan = orbit.a, orbit.argp + orbit.m0, orbit.raan
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
    u_arr = np.array(us)
    raan_arr = np.array(raans)

    si, ci = math.sin(inc), math.cos(inc)
    lat = np.arcsin(np.clip(si * np.sin(u_arr), -1.0, 1.0))
    lon_inertial = raan_arr + np.arctan2(ci * np.sin(u_arr), np.cos(u_arr))
    theta = gmst_rad(orbit.epoch) + OMEGA_E * t_arr
    lon = wrap_pi(lon_inertial - theta)

    # Decimated altitude-vs-time profile for plotting.
    step = max(1, len(t_arr) // 1500)
    extra = {
        "mode": "decay",
        "beta": beta,
        "decay_profile": {
            "t": t_arr[::step].round(1).tolist(),
            "alt_km": ((a_arr[::step] - RE) * 1e-3).round(2).tolist(),
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


# `Orbit.ground_track(mode="decay")` entry point.
decay_ground_track = propagate_decay
