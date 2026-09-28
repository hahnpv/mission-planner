"""Atmospheric density for the drag-decay mode.

Backed by the 1976 US Standard Atmosphere extended to 1000 km
(`atmosphere_1976_1000km`).  Queries go through the model's precomputed lookup table, so a
call costs an interp, not a table rebuild.

Still a static atmosphere: no solar-cycle (F10.7) or diurnal variation,
so decay lifetimes are nominal, not predictions — real thermospheric
density swings by factors of a few over the solar cycle.
"""

from __future__ import annotations

import numpy as np

from .atmosphere_1976_1000km import Atmosphere1976_1000km

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
        _H_GRID = np.linspace(-1000.0, 1000e3, 20001)
        _LOG_RHO = np.log(_model().query(_H_GRID)[2])
    return _H_GRID, _LOG_RHO


def density(alt_m):
    """US76 density [kg/m^3] at geometric altitude [m]; scalar or array.

    Clamped to the model's table range (-1 to 1000 km) outside it.
    """
    h_grid, log_rho = _grid()
    rho = np.exp(np.interp(alt_m, h_grid, log_rho))
    rho = np.asarray(rho)
    return rho if rho.shape else float(rho)
