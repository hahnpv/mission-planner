"""Orbit: classical elements at a UTC epoch, propagated with two-body + J2 secular.

Angles are radians and lengths meters internally; constructors take the
degree/kilometer units humans actually use.  Epochs are timezone-aware UTC
datetimes (naive input is assumed UTC).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import numpy as np

from .constants import J2, MU, OMEGA_E, RE
from .launch_site import LaunchSite, launch_azimuth
from .timebase import as_utc, gmst_rad

TWO_PI = 2.0 * math.pi


def wrap_pi(x):
    """Wrap angle(s) to [-pi, pi)."""
    return (x + math.pi) % TWO_PI - math.pi


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
        if epoch is None:
            epoch = datetime.now(timezone.utc)
        return cls(
            a=RE + alt_km * 1e3,
            e=0.0,
            inc=math.radians(inc_deg),
            raan=math.radians(raan_deg),
            argp=0.0,
            m0=math.radians(u0_deg),
            epoch=as_utc(epoch),
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
        if epoch is None:
            epoch = datetime.now(timezone.utc)
        epoch = as_utc(epoch)
        if perigee_km is None:
            perigee_km = 400.0 if alt_km is None else alt_km
        if apogee_km is None:
            apogee_km = perigee_km
        apogee_km = max(apogee_km, perigee_km)
        rp, ra = RE + perigee_km * 1e3, RE + apogee_km * 1e3
        a = 0.5 * (rp + ra)
        e = (ra - rp) / (ra + rp)

        lat = math.radians(site.lat_deg)
        inc = math.radians(inc_deg)
        s = math.sin(lat) / math.sin(inc) if math.sin(inc) else 2.0
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
        if e < 1e-9:
            argp, m0 = 0.0, u0
        else:
            delta = math.radians(perigee_offset_deg)
            argp = wrap_pi(u0 + delta)
            nu0 = -delta  # true anomaly at the crossing
            E = 2.0 * math.atan2(
                math.sqrt(1 - e) * math.sin(nu0 / 2), math.sqrt(1 + e) * math.cos(nu0 / 2)
            )
            m0 = E - e * math.sin(E)
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
        if epoch is None:
            epoch = datetime.now(timezone.utc)
        epoch = as_utc(epoch)
        apogee_km = max(apogee_km, perigee_km)
        rp, ra = RE + perigee_km * 1e3, RE + apogee_km * 1e3
        a, e = 0.5 * (rp + ra), (ra - rp) / (ra + rp)
        raan = wrap_pi(gmst_rad(epoch) + math.radians(node_lon_deg))
        argp = math.radians(argp_deg)
        nu0 = math.radians(nu0_deg) if nu0_deg is not None else -argp
        if e < 1e-9:
            m0 = nu0
        else:
            E = 2.0 * math.atan2(
                math.sqrt(1 - e) * math.sin(nu0 / 2), math.sqrt(1 + e) * math.cos(nu0 / 2)
            )
            m0 = E - e * math.sin(E)
        return cls(
            a=a, e=e, inc=math.radians(inc_deg), raan=raan, argp=wrap_pi(argp), m0=m0, epoch=epoch
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
        """Nodal-ish period [s] including the J2 mean-anomaly correction."""
        return TWO_PI / (self.mean_motion + self.j2_rates()[2])

    def j2_rates(self) -> tuple[float, float, float]:
        """Secular (raan_dot, argp_dot, dM_dot) from J2 [rad/s].

        dM_dot is the *correction* to the two-body mean motion.
        """
        n = self.mean_motion
        p = self.a * (1.0 - self.e**2)
        k = 1.5 * J2 * (RE / p) ** 2 * n
        ci = math.cos(self.inc)
        raan_dot = -k * ci
        argp_dot = 0.5 * k * (5.0 * ci * ci - 1.0)
        dm_dot = 0.5 * k * math.sqrt(1.0 - self.e**2) * (3.0 * ci * ci - 1.0)
        return raan_dot, argp_dot, dm_dot

    def launch_azimuth_deg(self, site_lat_deg: float, ascending: bool = True) -> float:
        v = math.sqrt(MU / self.a)
        return launch_azimuth(site_lat_deg, math.degrees(self.inc), ascending=ascending, v_orbit=v)

    def _nu0(self) -> float:
        """True anomaly at epoch [rad] from M0."""
        if self.e < 1e-9:
            return self.m0
        E = self.m0
        for _ in range(30):
            E -= (E - self.e * math.sin(E) - self.m0) / (1.0 - self.e * math.cos(E))
        return 2.0 * math.atan2(
            math.sqrt(1 + self.e) * math.sin(E / 2), math.sqrt(1 - self.e) * math.cos(E / 2)
        )

    def apsis_times(self) -> tuple[float, float]:
        """First (perigee, apogee) times [s] after epoch, J2-corrected."""
        n = self.mean_motion + self.j2_rates()[2]
        t_p = ((-self.m0) % TWO_PI) / n
        t_a = ((math.pi - self.m0) % TWO_PI) / n
        return t_p, t_a

    def summary(self) -> dict:
        raan_dot, argp_dot, _ = self.j2_rates()
        return {
            "alt_km": round(self.alt_km, 2),
            "perigee_km": round(self.perigee_km, 1),
            "apogee_km": round(self.apogee_km, 1),
            "a_km": round(self.a * 1e-3, 2),
            "e": round(self.e, 6),
            "inc_deg": round(math.degrees(self.inc), 3),
            "raan_deg": round(math.degrees(self.raan), 3),
            "argp_deg": round(math.degrees(self.argp), 3),
            "nu0_deg": round(math.degrees(wrap_pi(self._nu0())), 3),
            "epoch_utc": self.epoch.isoformat(),
            "period_s": round(self.period, 1),
            "revs_per_day": round(86400.0 / self.period, 3),
            "raan_drift_deg_per_day": round(math.degrees(raan_dot) * 86400, 4),
            "argp_drift_deg_per_day": round(math.degrees(argp_dot) * 86400, 4),
        }

    # ------------------------------------------------------------- propagate
    def _mean_anomaly(self, t: np.ndarray) -> np.ndarray:
        _, _, dm = self.j2_rates()
        return self.m0 + (self.mean_motion + dm) * t

    def eci_positions(self, t: np.ndarray) -> np.ndarray:
        """ECI positions [m], shape (N, 3), at seconds-past-epoch `t`."""
        t = np.asarray(t, dtype=float)
        m = self._mean_anomaly(t)
        if self.e < 1e-8:
            nu = m
            r = np.full_like(m, self.a)
        else:
            ecc = np.full_like(m, float(self.e))
            E = m.copy()
            for _ in range(12):
                E -= (E - ecc * np.sin(E) - m) / (1.0 - ecc * np.cos(E))
            nu = 2.0 * np.arctan2(
                np.sqrt(1 + self.e) * np.sin(E / 2), np.sqrt(1 - self.e) * np.cos(E / 2)
            )
            r = self.a * (1.0 - self.e * np.cos(E))
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

        Velocity for the general elliptic case in the perifocal frame,
        rotated by (raan, inc, argp) at time t — exact for e = 0.
        """
        ta = np.asarray([float(t)])
        m = float(self._mean_anomaly(ta)[0])
        if self.e < 1e-8:
            nu, r = m, self.a
        else:
            E = m
            for _ in range(30):
                E -= (E - self.e * math.sin(E) - m) / (1.0 - self.e * math.cos(E))
            nu = 2.0 * math.atan2(
                math.sqrt(1 + self.e) * math.sin(E / 2), math.sqrt(1 - self.e) * math.cos(E / 2)
            )
            r = self.a * (1.0 - self.e * math.cos(E))
        p = self.a * (1.0 - self.e**2)
        h = math.sqrt(MU * p)
        # Perifocal position/velocity.
        rp = np.array([r * math.cos(nu), r * math.sin(nu), 0.0])
        vp = np.array([-MU / h * math.sin(nu), MU / h * (self.e + math.cos(nu)), 0.0])
        raan_dot, argp_dot, _ = self.j2_rates()
        raan = self.raan + raan_dot * float(t)
        argp = self.argp + argp_dot * float(t)
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
        theta = gmst_rad(self.epoch) + OMEGA_E * t
        lon = wrap_pi(np.arctan2(pos[..., 1], pos[..., 0]) - theta)
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

        if mode == "decay":
            from .decay import decay_ground_track

            if beta is None:
                raise ValueError(
                    "decay mode requires a ballistic coefficient beta = m/(Cd*A) [kg/m^2]"
                )
            return decay_ground_track(self, beta, duration_s, dt_s)
        if mode != "kepler":
            from .plugins import registry

            return registry().propagator(mode)["fn"](self, beta, duration_s, dt_s)
        t = np.arange(0.0, float(duration_s) + 0.5 * dt_s, dt_s)
        lat, lon, r = self.subpoints(t)
        return GroundTrack(epoch=self.epoch, t=t, lat=lat, lon=lon, alt=r - RE)

    def with_epoch(self, epoch: datetime) -> Orbit:
        return replace(self, epoch=as_utc(epoch))
