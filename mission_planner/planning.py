"""Request parameters -> Orbit / GroundTrack / map payload.

Shared by the web server, the MCP server and plugins, so every surface reads
an orbit from its parameters the same way.  No flask here: plugins import it
at module scope.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .constants import RE
from .launch_site import SITES, LaunchSite
from .orbit import Orbit

DEFAULT_SITE = "Cape Canaveral / KSC"


def parse_epoch(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def orbit_from_args(a) -> tuple[Orbit, dict]:
    """Orbit from the web UI's query args (hp/ha/inc/epoch/site|lat,lon|anchor=elements…)."""
    hp = float(a.get("hp", a.get("alt", 400.0)))
    ha = float(a["ha"]) if a.get("ha") not in (None, "") else hp
    pofs = float(a.get("pofs", 0.0))
    inc = float(a.get("inc", 51.6))
    epoch = parse_epoch(a.get("epoch"))
    if a.get("anchor") == "elements":
        # No launch site: anchored by ascending-node (or GEO station) longitude.
        node_lon = float(a.get("node_lon", 0.0))
        orb = Orbit.from_elements(
            hp, ha, inc, epoch, node_lon_deg=node_lon, argp_deg=float(a.get("argp", 0.0))
        )
        return orb, {
            "site": "— (elements)",
            "site_lat": None,
            "site_lon": None,
            "launch_azimuth_deg": None,
            "node_lon_deg": node_lon,
        }
    ascending = a.get("leg", "ascending") != "descending"
    site_name = a.get("site", "")
    sites = dict(SITES)
    if site_name and site_name in sites:
        site = sites[site_name]
    elif "lat" in a:
        site = LaunchSite("custom", float(a["lat"]), float(a.get("lon", 0.0)))
    else:
        site = sites[DEFAULT_SITE]
    orb = Orbit.from_launch_site(
        site,
        inc_deg=inc,
        epoch=epoch,
        ascending=ascending,
        perigee_km=hp,
        apogee_km=ha,
        perigee_offset_deg=pofs,
    )
    meta = {
        "site": site.name,
        "site_lat": site.lat_deg,
        "site_lon": site.lon_deg,
        "launch_azimuth_deg": round(orb.launch_azimuth_deg(site.lat_deg, ascending=ascending), 1),
    }
    return orb, meta


def track_from_args(a):
    orb, meta = orbit_from_args(a)
    hours = float(a.get("hours", 24.0))
    dt = float(a.get("dt", 30.0))
    mode = a.get("mode", "kepler")
    beta = float(a["beta"]) if a.get("beta") else None
    gt = orb.ground_track(hours * 3600.0, dt, mode=mode, beta=beta)
    return orb, meta, gt


def plan_payload(orb, meta, gt) -> dict:
    """The /api/plan JSON: orbit summary + track (+ first-rev apsides if elliptic)."""
    track = gt.to_json()
    if orb.e > 1e-4:
        apsides = []
        for kind, ts in zip("PA", orb.apsis_times()):
            la, lo, r = orb.subpoints(np.array([ts]))
            apsides.append(
                {
                    "kind": kind,
                    "t_s": round(float(ts), 1),
                    "lat_deg": round(float(np.degrees(la[0])), 3),
                    "lon_deg": round(float(np.degrees(lo[0])), 3),
                    "alt_km": round(float(r[0] - RE) * 1e-3, 1),
                }
            )
        track["apsides"] = apsides
    return {"summary": {**orb.summary(), **meta}, "track": track}


def orbit_from_params(
    site: str,
    lat: float | None,
    lon: float | None,
    alt_km: float,
    inc_deg: float,
    epoch_utc: str | None,
    ascending: bool,
    perigee_km: float | None = None,
    apogee_km: float | None = None,
    perigee_offset_deg: float = 0.0,
    node_lon_deg: float | None = None,
    argp_deg: float = 0.0,
) -> tuple[Orbit, LaunchSite | None]:
    """Orbit from MCP-tool style keyword parameters (see mcp_server.plan_orbit)."""
    epoch = parse_epoch(epoch_utc)
    if not site and lat is None:
        # Element-anchored (no launch site): RAAN from node/station longitude.
        hp = perigee_km if perigee_km is not None else alt_km
        ha = apogee_km if apogee_km is not None else hp
        return Orbit.from_elements(
            hp, ha, inc_deg, epoch, node_lon_deg=node_lon_deg or 0.0, argp_deg=argp_deg
        ), None
    sites = dict(SITES)
    if site in sites:
        ls = sites[site]
    elif lat is not None:
        ls = LaunchSite(site or "custom", lat, lon or 0.0)
    else:
        raise ValueError(f"unknown site {site!r}; pass lat/lon or one of {list(sites)}")
    return Orbit.from_launch_site(
        ls,
        alt_km,
        inc_deg,
        epoch,
        ascending=ascending,
        perigee_km=perigee_km,
        apogee_km=apogee_km,
        perigee_offset_deg=perigee_offset_deg,
    ), ls
