"""Earth constants — the single authoritative source for this package.

Two unit systems circulate in the wider codebase (km in the demand layer,
SI in the entry decks); here everything is SI, with `_KM` variants provided
where a caller genuinely wants kilometers.  Values follow WGS-84 / IERS.
"""

# Gravitational parameter [m^3/s^2]
MU = 3.986004418e14
# Equatorial radius [m]
RE = 6378137.0
# J2 zonal harmonic [-]
J2 = 1.08262668e-3
# Earth rotation rate, IERS [rad/s]
OMEGA_E = 7.2921159e-5
# Sidereal day [s]
SIDEREAL_DAY = 86164.0905

MU_KM = MU * 1e-9  # [km^3/s^2]
RE_KM = RE * 1e-3  # [km]

# Entry interface altitude used by the drag-decay mode [m].  The usual
# convention: a 100 km circular orbit is the entry interface, not a loiter
# orbit (drag there kills the orbit in about one rev).
ENTRY_INTERFACE_ALT = 100e3
