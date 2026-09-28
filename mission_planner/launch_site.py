"""Launch sites and launch-azimuth geometry."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from .constants import OMEGA_E, RE


@dataclass(frozen=True)
class LaunchSite:
    name: str
    lat_deg: float
    lon_deg: float

    def min_inclination(self) -> float:
        """Lowest direct-injection inclination reachable from this site [deg]."""
        return abs(self.lat_deg)


class _SiteCatalog(Mapping):
    """Live name -> LaunchSite view of the catalog: core sites plus active
    data packs (see catalog.py).  Custom sites are just LaunchSite(name, lat, lon)."""

    def _sites(self) -> dict[str, LaunchSite]:
        from .catalog import current

        return {s["name"]: LaunchSite(s["name"], s["lat"], s["lon"]) for s in current()["sites"]}

    def __getitem__(self, name: str) -> LaunchSite:
        return self._sites()[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._sites())

    def __len__(self) -> int:
        return len(self._sites())


SITES: Mapping[str, LaunchSite] = _SiteCatalog()


def launch_azimuth(
    lat_deg: float, inc_deg: float, ascending: bool = True, v_orbit: float | None = None
) -> float:
    """Launch azimuth [deg, 0..360) to reach inclination `inc_deg` from `lat_deg`.

    Inertial spherical-trig azimuth (sin az = cos i / cos lat), corrected for
    Earth-rotation velocity when `v_orbit` [m/s] is given.  `ascending` picks
    the northeast-going solution; False gives the southeast-going one.
    Raises ValueError when the inclination is unreachable (inc < |lat|).
    """
    lat = math.radians(lat_deg)
    inc = math.radians(inc_deg)
    s = math.cos(inc) / math.cos(lat)
    if abs(s) > 1.0:
        raise ValueError(
            f"inclination {inc_deg:.2f} deg unreachable from latitude "
            f"{lat_deg:.2f} deg (need inc >= |lat|)"
        )
    az_inertial = math.asin(s)  # northeast branch, -pi/2..pi/2
    if not ascending:
        az_inertial = math.pi - az_inertial  # southeast branch
    if v_orbit is None:
        return math.degrees(az_inertial) % 360.0
    # Rotating-Earth correction: subtract the eastward pad velocity.
    v_east_pad = OMEGA_E * RE * math.cos(lat)
    vn = v_orbit * math.cos(az_inertial)
    ve = v_orbit * math.sin(az_inertial) - v_east_pad
    return math.degrees(math.atan2(ve, vn)) % 360.0
