"""Drag-decay propagation: King-Hele's theory for orbits with e < 0.2.

King-Hele (*Theory of Satellite Orbits in an Atmosphere*, 1964) averages the
drag over one revolution in an atmosphere whose density falls exponentially
above perigee, rho = rho_p exp(-(r - r_p) / H).  With c = a e / H and
I_n = I_n(c) the modified Bessel functions, the changes per revolution are

    Da = -2 pi delta a^2 rho_p e^-c [I0 + 2e I1 + 3/4 e^2 (I0 + I2) + 1/4 e^3 (3 I1 + I3)]
    De = -2 pi delta a   rho_p e^-c [I1 + e/2 (I0 + I2) - e^2/8 (5 I1 - I3)
                                     - e^3/16 (5 I0 + 4 I2 - I4)]

with delta = F / beta, beta = m / (Cd A) [kg/m^2], and F = (1 - r_p omega_E
cos i / v_p)^2 for the atmosphere co-rotating with the Earth (the vehicle
sees less relative wind on a prograde orbit; ~0.92 at 400 km / 51.6 deg).
The series is King-Hele's expansion in e, good to O(e^4) — 0.1 % in Da at
e = 0.2, which is where MAX_ECCENTRICITY stops it.  At e = 0 it is the
circular law da/dt = -F rho sqrt(mu a) / beta.  The drag is concentrated
at perigee, so an elliptic orbit keeps its perigee roughly in place while
the apogee comes down, and circularizes before it decays.

rho_p comes from the US Standard Atmosphere 1976 extended to 1000 km (see
atmosphere.py).  The real scale height grows with altitude, which King-Hele
allows for by evaluating H above perigee; here H is the table's local scale
height one scale height above perigee — calibrated against a direct
integration of the equations of motion in the same atmosphere, which it
matches to ~3 % in Da and De for e up to 0.2 (tests/test_decay.py).

The mean elements (a, e, M, argp, RAAN) are integrated with RK4: Da, De per
anomalistic period, and the J2 secular rates re-evaluated as the orbit
shrinks.  Fast angles stay analytic, so weeks-long horizons stay cheap, and
the ground track tightens and speeds up as the orbit comes down.  The track
stops when perigee reaches the 100 km entry interface.

This is the cheap analytic backend and stops at the entry interface by
design; higher-fidelity propagators (full 3-DOF flight through reentry to
impact, say) plug in as extra modes — see plugins.py.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.special import ive

from .atmosphere import density, scale_height
from .constants import ENTRY_INTERFACE_ALT, MU, OMEGA_E, RE
from .groundtrack import GroundTrack
from .orbit import Orbit, j2_secular, subpoint_from_orbital, wrap_pi
from .timebase import add_seconds

R_FLOOR = RE + ENTRY_INTERFACE_ALT
MAX_ECCENTRICITY = 0.2  # King-Hele's small-eccentricity series holds below this
_ORDERS = np.arange(5)
_H_EFF: tuple[np.ndarray, np.ndarray] | None = None


def _scale_height_above(hp: float) -> float:
    """H for the series at perigee altitude `hp` [m]: the table's local scale
    height one scale height above perigee (tabulated once; see the module
    docstring for why there)."""
    global _H_EFF
    if _H_EFF is None:
        grid = np.linspace(0.0, 3000e3, 6001)
        _H_EFF = grid, scale_height(grid + scale_height(grid))
    return float(np.interp(hp, *_H_EFF))


def _rates(a: float, e: float, inc: float, beta: float) -> tuple[float, float]:
    """(da/dt, de/dt): King-Hele's changes per revolution over the period."""
    rp = a * (1.0 - e)
    vp = math.sqrt(MU * (1.0 + e) / rp)
    corot = (1.0 - OMEGA_E * rp * math.cos(inc) / vp) ** 2
    hp = rp - RE
    c = a * e / _scale_height_above(hp)
    i0, i1, i2, i3, i4 = ive(_ORDERS, c)  # e^-c I_n(c): no overflow at large c
    k = 2.0 * math.pi * corot * density(hp) / beta
    da = -k * a * a * (i0 + 2 * e * i1 + 0.75 * e * e * (i0 + i2) + 0.25 * e**3 * (3 * i1 + i3))
    de = (
        -k
        * a
        * (
            i1
            + 0.5 * e * (i0 + i2)
            - e * e / 8 * (5 * i1 - i3)
            - e**3 / 16 * (5 * i0 + 4 * i2 - i4)
        )
    )
    period = 2.0 * math.pi * math.sqrt(a**3 / MU)
    return da / period, de / period


def _derivs(y: np.ndarray, inc: float, beta: float) -> np.ndarray:
    """d/dt of the mean elements y = (a, e, M, argp, raan)."""
    a, e = y[0], max(y[1], 0.0)
    da, de = _rates(a, e, inc, beta)
    raan_dot, argp_dot, dm_dot = j2_secular(a, e, inc)
    return np.array([da, de, math.sqrt(MU / a**3) + dm_dot, argp_dot, raan_dot])


def propagate_decay(
    orbit: Orbit, beta: float, duration_s: float, dt_s: float = 30.0
) -> GroundTrack:
    """Propagate an orbit (e <= MAX_ECCENTRICITY) with drag decay; stops when
    perigee reaches 100 km.

    Returns a GroundTrack whose `extra` holds the decay profile (mean
    altitude a - RE, perigee and apogee altitudes) and, when the orbit comes
    down inside the horizon, the entry epoch/subpoint.  Starts from the same
    elements as the Kepler track, so switching modes does not jump.
    """
    if beta <= 0:
        raise ValueError("beta must be positive [kg/m^2]")
    if orbit.e > MAX_ECCENTRICITY:
        raise ValueError(
            f"decay mode's King-Hele series needs e <= {MAX_ECCENTRICITY} (this orbit: "
            f"e = {orbit.e:.3f}) — use a full-sim plugin mode for more eccentric orbits"
        )

    inc = orbit.inc
    y = np.array([orbit.a, orbit.e, orbit.m0, orbit.argp, orbit.raan])
    t = 0.0
    ts, ys = [t], [y.copy()]
    entered = False

    n_out = max(1, int(round(duration_s / dt_s)))
    for _ in range(n_out):
        t_next = t + dt_s
        while t < t_next - 1e-9:
            # Adaptive substep: fine only when decay is fast (low perigee);
            # cap the per-step change at ~3 km in a and 0.002 in e.
            k1 = _derivs(y, inc, beta)
            h = min(
                t_next - t,
                max(10.0, min(3e3 / max(abs(k1[0]), 1e-12), 2e-3 / max(abs(k1[1]), 1e-15))),
            )
            k2 = _derivs(y + 0.5 * h * k1, inc, beta)
            k3 = _derivs(y + 0.5 * h * k2, inc, beta)
            k4 = _derivs(y + h * k3, inc, beta)
            y_prev, t_prev = y, t
            y = y + h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
            y[1] = max(y[1], 0.0)
            t += h
            rp = y[0] * (1.0 - y[1])
            if rp <= R_FLOOR:
                # Interpolate back to where perigee crossed 100 km.
                rp_prev = y_prev[0] * (1.0 - y_prev[1])
                f = (rp_prev - R_FLOOR) / max(rp_prev - rp, 1e-12)
                y = y_prev + f * (y - y_prev)
                t = t_prev + f * (t - t_prev)
                entered = True
                break
        ts.append(t)
        ys.append(y.copy())
        if entered:
            break

    t_arr = np.array(ts)
    a_arr, e_arr, m_arr, argp_arr, raan_arr = np.array(ys).T
    # Position on the osculating ellipse of the mean elements (Newton on
    # Kepler's equation, vectorized over the per-sample eccentricity).
    mw = wrap_pi(m_arr)
    E = mw + e_arr * np.sin(mw)
    for _ in range(12):
        E = E - (E - e_arr * np.sin(E) - mw) / (1.0 - e_arr * np.cos(E))
    nu = (m_arr - mw) + 2.0 * np.arctan2(
        np.sqrt(1 + e_arr) * np.sin(E / 2), np.sqrt(1 - e_arr) * np.cos(E / 2)
    )
    r = a_arr * (1.0 - e_arr * np.cos(E))
    lat, lon = subpoint_from_orbital(argp_arr + nu, raan_arr, inc, orbit.epoch, t_arr)

    # Decimated profile for plotting; the last sample always makes it in, so
    # the profile ends where the track ends.
    step = max(1, len(t_arr) // 1500)
    keep = np.unique(np.r_[np.arange(0, len(t_arr), step), len(t_arr) - 1])
    km = lambda x: ((x[keep] - RE) * 1e-3).round(2).tolist()  # noqa: E731
    extra = {
        "decay_profile": {
            "t": t_arr[keep].round(1).tolist(),
            "alt_km": km(a_arr),
            "perigee_km": km(a_arr * (1.0 - e_arr)),
            "apogee_km": km(a_arr * (1.0 + e_arr)),
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

    return GroundTrack(epoch=orbit.epoch, t=t_arr, lat=lat, lon=lon, alt=r - RE, extra=extra)
