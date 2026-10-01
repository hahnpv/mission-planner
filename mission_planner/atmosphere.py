"""Atmospheric density for the drag-decay mode.

Backed by the 1976 US Standard Atmosphere extended to 1000 km
(`atmosphere_1976_1000km`, our own implementation of the tables in the
public-domain US government reference document).  Queries go through the
model's precomputed lookup table, so a call costs an interp, not a table
rebuild.

Still a static atmosphere: no solar-cycle (F10.7) or diurnal variation,
so decay lifetimes are nominal, not predictions — real thermospheric
density swings by factors of a few over the solar cycle.
"""

from __future__ import annotations

import numpy as np

from .atmosphere_1976_1000km import Atmosphere1976_1000km

TABLE_TOP_M = 1000e3  # the model's table ends here; above it we extrapolate

_ATM: Atmosphere1976_1000km | None = None
_H_GRID: np.ndarray | None = None
_LOG_RHO: np.ndarray | None = None


def _model() -> Atmosphere1976_1000km:
    global _ATM
    if _ATM is None:
        _ATM = Atmosphere1976_1000km()
    return _ATM


def _grid() -> tuple[np.ndarray, np.ndarray]:
    # Density-only log-interp cache: the model's own query() costs ~70 us
    # per scalar call (interp1d overhead x 6 properties), too slow for the
    # decay RK4 loop.  Sampling the model once on a dense grid and doing
    # log-linear np.interp keeps full fidelity at ~1 us per lookup.
    global _H_GRID, _LOG_RHO
    if _H_GRID is None:
        _H_GRID = np.linspace(-1000.0, TABLE_TOP_M, 20001)
        _LOG_RHO = np.log(_model().query(_H_GRID)[2])
    return _H_GRID, _LOG_RHO


def density(alt_m):
    """US76 density [kg/m^3] at geometric altitude [m]; scalar or array.

    Clamped to sea-level density below the table; above 1000 km the last
    decade of the table is extrapolated log-linearly (a ~270 km scale height),
    so high orbits see a density that keeps falling rather than the 1000 km
    value frozen — still a rough guess, but 10-100x closer than the clamp.
    """
    h_grid, log_rho = _grid()
    alt = np.asarray(alt_m, dtype=float)
    log = np.interp(alt, h_grid, log_rho)
    top, step = log_rho[-1], h_grid[-1] - h_grid[-2]
    slope = (top - log_rho[-2]) / step
    log = np.where(alt > h_grid[-1], top + slope * (alt - h_grid[-1]), log)
    rho = np.exp(log)
    return rho if rho.shape else float(rho)


def scale_height(alt_m, half_span_m: float = 2e3):
    """Local density scale height H = -1 / (d ln rho / dh) [m] at altitude
    [m] (scalar or array), from a central difference over +-`half_span_m`:
    the H of the exponential atmosphere that matches the table there."""
    alt = np.asarray(alt_m, dtype=float)
    lo = np.log(density(alt - half_span_m))
    hi = np.log(density(alt + half_span_m))
    h = 2.0 * half_span_m / (lo - hi)
    return h if h.shape else float(h)
