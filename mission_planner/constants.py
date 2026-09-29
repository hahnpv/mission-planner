"""Earth constants — the single authoritative source for this package.

Everything is SI (metres, seconds, radians); the API edge converts to the
kilometres and degrees humans use.  Values follow WGS-84 / IERS.
"""

# Gravitational parameter [m^3/s^2]
MU = 3.986004418e14
# Equatorial radius [m]
RE = 6378137.0
# J2 zonal harmonic [-]
J2 = 1.08262668e-3
# Earth rotation rate, IERS [rad/s]
OMEGA_E = 7.2921159e-5

# Entry interface altitude used by the drag-decay mode [m].  The usual
# convention: a 100 km circular orbit is the entry interface, not a loiter
# orbit (drag there kills the orbit in about one rev).
ENTRY_INTERFACE_ALT = 100e3
