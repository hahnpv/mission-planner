"""Orbit: classical elements at a UTC epoch, propagated with two-body + J2 secular.

Angles are radians and lengths meters internally; constructors take the
degree/kilometer units humans actually use.  Epochs are timezone-aware UTC
datetimes (naive input is assumed UTC).  The Earth is a sphere: site
latitudes are geocentric (the geodetic gap is ~0.16 deg at 30 deg).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .constants import J2, MU, RE
from .launch_site import LaunchSite, launch_azimuth
from .timebase import as_utc, earth_rotation_rad, gmst_rad, now_utc

TWO_PI = 2.0 * math.pi
E_CIRCULAR = 1e-8  # below this eccentricity the orbit is treated as circular


def wrap_pi(x):
    """Wrap angle(s) to [-pi, pi)."""
    return (x + math.pi) % TWO_PI - math.pi


# ------------------------------------------------------------ element helpers
def kepler_E(M, e: float, iterations: int = 30):
    """Eccentric anomaly from mean anomaly (Newton; scalar or array)."""
    if e < E_CIRCULAR:
        return M
    M = np.asarray(M, dtype=float)
    # Solve on the wrapped anomaly (Newton is only well-behaved near the
    # principal branch) and add the whole turns back afterwards.
    Mw = wrap_pi(M)
    turns = M - Mw
    # Start above |M| for e > 0.8: Newton from E = M can overshoot near perigee.
    E = Mw + e * np.sin(Mw) if e < 0.8 else np.where(Mw < 0, -math.pi, math.pi)
    for _ in range(iterations):
        E = E - (E - e * np.sin(E) - Mw) / (1.0 - e * np.cos(E))
    E = E + turns
    return E if E.shape else float(E)


def nu_from_E(E, e: float):
    """True anomaly from eccentric anomaly (scalar or array)."""
    return 2.0 * np.arctan2(np.sqrt(1 + e) * np.sin(E / 2), np.sqrt(1 - e) * np.cos(E / 2))


def M_from_nu(nu: float, e: float) -> float:
    """Mean anomaly from true anomaly (scalar)."""
    if e < E_CIRCULAR:
        return nu
    E = 2.0 * math.atan2(math.sqrt(1 - e) * math.sin(nu / 2), math.sqrt(1 + e) * math.cos(nu / 2))
    return E - e * math.sin(E)


def sma_ecc_from_apsides(perigee_km: float, apogee_km: float) -> tuple[float, float]:
    """(a [m], e) from apsis altitudes [km]; apogee is raised to perigee if lower."""
    apogee_km = max(apogee_km, perigee_km)
    rp, ra = RE + perigee_km * 1e3, RE + apogee_km * 1e3
    return 0.5 * (rp + ra), (ra - rp) / (ra + rp)


def j2_secular(a: float, e: float, inc: float) -> tuple[float, float, float]:
    """Secular J2 rates (raan_dot, argp_dot, dM_dot) [rad/s] for SI elements.

    dM_dot is the *correction* to the two-body mean motion (Vallado 9-37/38/41).
    """
    n = math.sqrt(MU / a**3)
    p = a * (1.0 - e * e)
    k = 1.5 * J2 * (RE / p) ** 2 * n
    ci = math.cos(inc)
    raan_dot = -k * ci
    argp_dot = 0.5 * k * (5.0 * ci * ci - 1.0)
    dm_dot = 0.5 * k * math.sqrt(1.0 - e * e) * (3.0 * ci * ci - 1.0)
    return raan_dot, argp_dot, dm_dot


def subpoint_from_orbital(u, raan, inc: float, epoch: datetime, t):
    """Earth-fixed (lat, lon) [rad] of the point at argument of latitude `u`,
    node `raan` (both inertial, scalar or array) at seconds-past-epoch `t`."""
    u, raan = np.asarray(u, dtype=float), np.asarray(raan, dtype=float)
    si, ci = math.sin(inc), math.cos(inc)
    lat = np.arcsin(np.clip(si * np.sin(u), -1.0, 1.0))
    lon_inertial = raan + np.arctan2(ci * np.sin(u), np.cos(u))
    return lat, wrap_pi(lon_inertial - earth_rotation_rad(epoch, t))


@dataclass(frozen=True)
class Orbit:
    a: float  # semi-major axis [m]
    e: float  # eccentricity [-]
    inc: float  # inclination [rad]
    raan: float  # RAAN at epoch [rad]
    argp: float  # argument of perigee [rad]
    m0: float  # mean anomaly at epoch [rad]
    epoch: datetime  # UTC

    # ------------------------------------------------------------------ build
    @classmethod
    def circular(
        cls,
        alt_km: float,
        inc_deg: float,
        raan_deg: float = 0.0,
        u0_deg: float = 0.0,
        epoch: datetime | None = None,
    ) -> Orbit:
        """Circular orbit; `u0_deg` is the argument of latitude at epoch."""
        return cls(
            a=RE + alt_km * 1e3,
            e=0.0,
            inc=math.radians(inc_deg),
            raan=math.radians(raan_deg),
            argp=0.0,
            m0=math.radians(u0_deg),
            epoch=as_utc(epoch or now_utc()),
        )

    @classmethod
    def from_launch_site(
        cls,
        site: LaunchSite,
        alt_km: float | None = None,
        inc_deg: float = 51.6,
        epoch: datetime | None = None,
        ascending: bool = True,
        perigee_km: float | None = None,
        apogee_km: float | None = None,
        perigee_offset_deg: float = 0.0,
    ) -> Orbit:
        """Orbit whose plane contains `site` at the launch epoch.

        Circular when only `alt_km` is given.  For an ellipse pass
        `perigee_km`/`apogee_km`; `perigee_offset_deg` places perigee that
        many degrees DOWNRANGE along the orbit from the site crossing
        (0 = perigee overhead at the site pass, 180 = perigee antipodal, so
        apogee is overhead) — the site subpoint at t=0 is unchanged, only
        the phasing on the ellipse, so the altitude over the site is derived.

        `ascending=True` places the site on the northeast-going leg.
        Raises ValueError when inc < |site latitude|.
        """
        epoch = as_utc(epoch or now_utc())
        if perigee_km is None:
            perigee_km = 400.0 if alt_km is None else alt_km
        if apogee_km is None:
            apogee_km = perigee_km
        a, e = sma_ecc_from_apsides(perigee_km, apogee_km)

        lat = math.radians(site.lat_deg)
        inc = math.radians(inc_deg)
        if abs(math.sin(inc)) < 1e-12:
            # Equatorial orbit: reachable only from the equator.
            s = 0.0 if abs(math.sin(lat)) < 1e-12 else 2.0
        else:
            s = math.sin(lat) / math.sin(inc)
        if abs(s) > 1.0 + 1e-9:
            raise ValueError(
                f"inclination {inc_deg:.2f} deg cannot pass over latitude "
                f"{site.lat_deg:.2f} deg (need inc >= |lat|)"
            )
        s = max(-1.0, min(1.0, s))
        u0 = math.asin(s)
        if not ascending:
            u0 = math.pi - u0
        # Inertial longitude of the subpoint = raan + atan2(cos i sin u, cos u)
        lon_inertial = math.radians(site.lon_deg) + gmst_rad(epoch)
        raan = lon_inertial - math.atan2(math.cos(inc) * math.sin(u0), math.cos(u0))
        if e < E_CIRCULAR:
            argp, m0 = 0.0, u0
        else:
            delta = math.radians(perigee_offset_deg)
            argp = wrap_pi(u0 + delta)
            m0 = M_from_nu(-delta, e)  # true anomaly at the crossing is -delta
        return cls(a=a, e=e, inc=inc, raan=wrap_pi(raan), argp=argp, m0=m0, epoch=epoch)

    @classmethod
    def from_elements(
        cls,
        perigee_km: float,
        apogee_km: float,
        inc_deg: float,
        epoch: datetime | None = None,
        node_lon_deg: float = 0.0,
        argp_deg: float = 0.0,
        nu0_deg: float | None = None,
    ) -> Orbit:
        """Orbit anchored to the Earth by node longitude, no launch site.

        The ascending node sits over longitude `node_lon_deg` at the epoch
        (RAAN = GMST + node_lon); propagation starts at the node (u = 0)
        unless `nu0_deg` is given.  For GEO (i = 0, e = 0) `node_lon_deg`
        degenerates into the station longitude — the subpoint parks there.
        """
        epoch = as_utc(epoch or now_utc())
        a, e = sma_ecc_from_apsides(perigee_km, apogee_km)
        raan = wrap_pi(gmst_rad(epoch) + math.radians(node_lon_deg))
        argp = math.radians(argp_deg)
        nu0 = math.radians(nu0_deg) if nu0_deg is not None else -argp
        return cls(
            a=a,
            e=e,
            inc=math.radians(inc_deg),
            raan=raan,
            argp=wrap_pi(argp),
            m0=M_from_nu(nu0, e),
            epoch=epoch,
        )

    # ------------------------------------------------------------- properties
    @property
    def alt_km(self) -> float:
        return (self.a - RE) * 1e-3

    @property
    def perigee_km(self) -> float:
        return (self.a * (1.0 - self.e) - RE) * 1e-3

    @property
    def apogee_km(self) -> float:
        return (self.a * (1.0 + self.e) - RE) * 1e-3

    @property
    def mean_motion(self) -> float:
        """Unperturbed mean motion [rad/s]."""
        return math.sqrt(MU / self.a**3)

    @property
    def period(self) -> float:
        """Anomalistic period [s] (perigee to perigee) with the J2
        mean-motion correction — the one `apsis_times` counts in."""
        return TWO_PI / (self.mean_motion + self.j2_rates()[2])

    @property
    def nodal_period(self) -> float:
        """Nodal (draconitic) period [s]: ascending node to ascending node,
        so J2's argument-of-perigee drift counts too.  This is the period a
        ground-track repeat is quoted in, and what `revs_per_day` uses."""
        _, argp_dot, dm_dot = self.j2_rates()
        return TWO_PI / (self.mean_motion + dm_dot + argp_dot)

    def j2_rates(self) -> tuple[float, float, float]:
        """Secular (raan_dot, argp_dot, dM_dot) from J2 [rad/s]; see `j2_secular`."""
        return j2_secular(self.a, self.e, self.inc)

    def launch_azimuth_deg(self, site_lat_deg: float, ascending: bool = True) -> float:
        """Launch azimuth into this orbit from `site_lat_deg`, with the
        rotating-Earth correction at the injection speed (the speed at the
        epoch, which `from_launch_site` places over the site)."""
        _, v = self.eci_state(0.0)
        return launch_azimuth(
            site_lat_deg,
            math.degrees(self.inc),
            ascending=ascending,
            v_orbit=float(np.linalg.norm(v)),
        )

    def nu0(self) -> float:
        """True anomaly at epoch [rad] from M0."""
        return float(nu_from_E(kepler_E(self.m0, self.e), self.e))

    def apsis_times(self) -> tuple[float, float]:
        """First (perigee, apogee) times [s] after epoch, J2-corrected."""
        n = self.mean_motion + self.j2_rates()[2]
        t_p = ((-self.m0) % TWO_PI) / n
        t_a = ((math.pi - self.m0) % TWO_PI) / n
        return t_p, t_a

    def summary(self) -> dict:
        """Elements and rates in km/deg; RAAN and argp in [0, 360), nu0 in [-180, 180)."""
        raan_dot, argp_dot, _ = self.j2_rates()
        return {
            "alt_km": round(self.alt_km, 2),
            "perigee_km": round(self.perigee_km, 1),
            "apogee_km": round(self.apogee_km, 1),
            "a_km": round(self.a * 1e-3, 2),
            "e": round(self.e, 6),
            "inc_deg": round(math.degrees(self.inc), 3),
            "raan_deg": round(math.degrees(self.raan) % 360.0, 3),
            "argp_deg": round(math.degrees(self.argp) % 360.0, 3),
            "nu0_deg": round(math.degrees(wrap_pi(self.nu0())), 3),
            "epoch_utc": self.epoch.isoformat(),
            "period_s": round(self.period, 1),
            "nodal_period_s": round(self.nodal_period, 1),
            "revs_per_day": round(86400.0 / self.nodal_period, 3),
            "raan_drift_deg_per_day": round(math.degrees(raan_dot) * 86400, 4),
            "argp_drift_deg_per_day": round(math.degrees(argp_dot) * 86400, 4),
        }

    # ------------------------------------------------------------- propagate
    def mean_anomaly(self, t):
        """Mean anomaly [rad] at seconds-past-epoch `t` (scalar or array),
        J2-corrected."""
        return self.m0 + (self.mean_motion + self.j2_rates()[2]) * np.asarray(t, dtype=float)

    def _anomalies(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(true anomaly, radius [m]) at `t`."""
        m = self.mean_anomaly(t)
        if self.e < E_CIRCULAR:
            return m, np.full_like(m, self.a)
        E = kepler_E(m, self.e, iterations=12)
        return nu_from_E(E, self.e), self.a * (1.0 - self.e * np.cos(E))

    def argument_of_latitude(self, t):
        """Argument of latitude u = argp(t) + nu(t) [rad] at seconds-past-epoch
        `t` (scalar or array) — where the vehicle is along its orbit, measured
        from the ascending node."""
        t = np.asarray(t, dtype=float)
        nu, _ = self._anomalies(t)
        return self.argp + self.j2_rates()[1] * t + nu

    def eci_positions(self, t: np.ndarray) -> np.ndarray:
        """ECI positions [m], shape (N, 3), at seconds-past-epoch `t`."""
        t = np.asarray(t, dtype=float)
        nu, r = self._anomalies(t)
        raan_dot, argp_dot, _ = self.j2_rates()
        u = self.argp + argp_dot * t + nu  # argument of latitude
        raan = self.raan + raan_dot * t
        ci, si = math.cos(self.inc), math.sin(self.inc)
        cu, su = np.cos(u), np.sin(u)
        co, so = np.cos(raan), np.sin(raan)
        x = r * (co * cu - so * su * ci)
        y = r * (so * cu + co * su * ci)
        z = r * (su * si)
        return np.stack([x, y, z], axis=-1)

    def eci_state(self, t: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """ECI position [m] and inertial velocity [m/s] at seconds-past-epoch t.

        The velocity is the two-body (osculating) velocity of the elements
        at time t: the perifocal state rotated by (raan(t), inc, argp(t)).
        It omits the tiny J2 secular drift of the frame itself (a few m/s),
        so it is exact for a two-body orbit and adequate to seed a
        higher-fidelity propagator.
        """
        t = float(t)
        nu, r = (float(x[0]) for x in self._anomalies(np.array([t])))
        p = self.a * (1.0 - self.e**2)
        h = math.sqrt(MU * p)
        # Perifocal position/velocity.
        rp = np.array([r * math.cos(nu), r * math.sin(nu), 0.0])
        vp = np.array([-MU / h * math.sin(nu), MU / h * (self.e + math.cos(nu)), 0.0])
        raan_dot, argp_dot, _ = self.j2_rates()
        raan = self.raan + raan_dot * t
        argp = self.argp + argp_dot * t
        cO, sO = math.cos(raan), math.sin(raan)
        ci, si = math.cos(self.inc), math.sin(self.inc)
        cw, sw = math.cos(argp), math.sin(argp)
        rot = np.array(
            [
                [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
                [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
                [sw * si, cw * si, ci],
            ]
        )
        return rot @ rp, rot @ vp

    def subpoints(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Sub-satellite (lat, lon) [rad, earth-fixed] and radius [m] at `t`."""
        t = np.asarray(t, dtype=float)
        pos = self.eci_positions(t)
        r = np.linalg.norm(pos, axis=-1)
        lat = np.arcsin(pos[..., 2] / r)
        lon = wrap_pi(np.arctan2(pos[..., 1], pos[..., 0]) - earth_rotation_rad(self.epoch, t))
        return lat, lon, r

    def ground_track(
        self, duration_s: float, dt_s: float = 30.0, mode: str = "kepler", beta: float | None = None
    ):
        """GroundTrack over `duration_s`.

        Core modes: "kepler" (two-body + J2) and "decay" (King-Hele drag
        decay; needs `beta` [kg/m^2]).  Any other mode is looked up among
        the active plugins' propagators (see plugins.py).
        """
        from .groundtrack import GroundTrack

        if not dt_s > 0:
            raise ValueError("dt_s must be positive")
        if duration_s < 0:
            raise ValueError("duration_s must not be negative")
        if mode == "decay":
            from .decay import propagate_decay

            if beta is None:
                raise ValueError(
                    "decay mode requires a ballistic coefficient beta = m/(Cd*A) [kg/m^2]"
                )
            return propagate_decay(self, beta, duration_s, dt_s)
        if mode != "kepler":
            from .plugins import registry

            return registry().propagator(mode)["fn"](self, beta, duration_s, dt_s)
        t = np.arange(0.0, float(duration_s) + 0.5 * dt_s, dt_s)
        lat, lon, r = self.subpoints(t)
        return GroundTrack(epoch=self.epoch, t=t, lat=lat, lon=lon, alt=r - RE)


__all__ = [
    "Orbit",
    "wrap_pi",
    "kepler_E",
    "nu_from_E",
    "M_from_nu",
    "sma_ecc_from_apsides",
    "j2_secular",
    "subpoint_from_orbital",
]
