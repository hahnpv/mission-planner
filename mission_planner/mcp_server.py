"""Mission-planner MCP server.

Exposes the orbit-planning library to an agent, plus `show_scene` /
`show_plan` which push graphics into a running web UI (`python -m
mission_planner.server`, http://127.0.0.1:3030) so results appear on the
map in front of the user.  Pattern follows config/mcp_server.py.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

from .launch_site import SITES
from .planning import orbit_from_params as _orbit
from .plugins import registry
from .scene import Scene

UI_URL = "http://127.0.0.1:3030"

mcp = FastMCP("mission-planner", dependencies=["numpy"])


def _post_scene(doc: dict) -> dict:
    req = urllib.request.Request(
        f"{UI_URL}/api/scene",
        data=json.dumps(doc).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(
            f"mission-planner UI not reachable at {UI_URL} — start it with "
            f"`python -m mission_planner.server` (error: {e})"
        ) from e


@mcp.tool()
def list_launch_sites() -> dict:
    """List the launch-site catalog (core sites plus installed data packs)."""
    return {"sites": [{"name": s.name, "lat": s.lat_deg, "lon": s.lon_deg} for s in SITES.values()]}


@mcp.tool()
def plan_orbit(
    site: str = "Cape Canaveral / KSC",
    alt_km: float = 400.0,
    inc_deg: float = 51.6,
    epoch_utc: str | None = None,
    hours: float = 24.0,
    mode: str = "kepler",
    beta: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    ascending: bool = True,
    perigee_km: float | None = None,
    apogee_km: float | None = None,
    perigee_offset_deg: float = 0.0,
    node_lon_deg: float | None = None,
    argp_deg: float = 0.0,
) -> dict:
    """Plan an orbit launched over a site and summarize its ground track.

    Args:
        site: catalog name (see list_launch_sites), a label for a custom
            site given via lat/lon, or "" (with no lat) for an
            element-anchored orbit with no launch site: the ascending node
            sits over node_lon_deg at the epoch (for GEO that is the
            station longitude) and argp_deg sets the argument of perigee —
            how to plan classics like Molniya (500x39868, 63.4, argp 270)
            or GEO (35786 circular, inc 0, node_lon = station).
        alt_km, inc_deg: circular orbit altitude and inclination.
        perigee_km/apogee_km: elliptic orbit instead of alt_km;
            perigee_offset_deg places perigee that many degrees downrange
            of the site crossing (0 = perigee overhead, 180 = antipodal).
            Note decay mode is circular-only (e <= 0.05).
        epoch_utc: ISO launch epoch (default: now).
        hours: propagation horizon.
        mode: "kepler" (two-body + J2), "decay" (averaged King-Hele drag
            decay; needs beta), or a mode provided by an installed plugin
            (an unknown mode's error lists the available ones).
        beta: ballistic coefficient m/(Cd*A) [kg/m^2] for drag modes.
    Returns orbit summary (period, revs/day, RAAN drift, launch azimuth);
    drag modes add the predicted entry epoch/subpoint and final altitude,
    and modes that fly to the ground add the impact point.
    """
    orb, ls = _orbit(
        site,
        lat,
        lon,
        alt_km,
        inc_deg,
        epoch_utc,
        ascending,
        perigee_km,
        apogee_km,
        perigee_offset_deg,
        node_lon_deg,
        argp_deg,
    )
    gt = orb.ground_track(hours * 3600.0, 60.0, mode=mode, beta=beta)
    out = {
        "summary": orb.summary(),
        "launch_azimuth_deg": None
        if ls is None
        else round(orb.launch_azimuth_deg(ls.lat_deg, ascending=ascending), 1),
    }
    if "entry" in gt.extra:
        out["entry"] = gt.extra["entry"]
    if "decay_profile" in gt.extra:
        out["final_alt_km"] = gt.extra["decay_profile"]["alt_km"][-1]
    if gt.extra.get("impact") is not None:
        out["impact"] = gt.extra["impact"]
    return out


@mcp.tool()
def find_passes(
    tgt_lat: float,
    tgt_lon: float,
    site: str = "Cape Canaveral / KSC",
    alt_km: float = 400.0,
    inc_deg: float = 51.6,
    epoch_utc: str | None = None,
    hours: float = 48.0,
    within_km: float = 500.0,
    mode: str = "kepler",
    beta: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    ascending: bool = True,
    perigee_km: float | None = None,
    apogee_km: float | None = None,
    perigee_offset_deg: float = 0.0,
    node_lon_deg: float | None = None,
    argp_deg: float = 0.0,
) -> dict:
    """Find overflight windows of a target for a planned orbit.

    Returns UTC AOS/LOS/closest-approach per pass with miss distance,
    heading, and leg direction.  perigee_km/apogee_km/perigee_offset_deg
    plan an elliptic orbit; site="" with node_lon_deg/argp_deg plans an
    element-anchored orbit (see plan_orbit).
    """
    orb, _ = _orbit(
        site,
        lat,
        lon,
        alt_km,
        inc_deg,
        epoch_utc,
        ascending,
        perigee_km,
        apogee_km,
        perigee_offset_deg,
        node_lon_deg,
        argp_deg,
    )
    gt = orb.ground_track(hours * 3600.0, 30.0, mode=mode, beta=beta)
    passes = gt.passes(tgt_lat, tgt_lon, within_km=within_km)
    return {"n": len(passes), "passes": passes}


@mcp.tool()
def show_scene(scene: dict) -> dict:
    """Push a Scene document to the running map UI for the user to see.

    Layers: track {lat[], lon[]}, marker {lat, lon, symbol}, polygon,
    windows {columns[], rows[][]}, label — all angles degrees.  See
    mission_planner.scene for the full contract.
    """
    doc = Scene.from_json(scene).to_json()  # validate
    res = _post_scene(doc)
    return {"ok": True, "url": UI_URL, "version": res.get("version")}


@mcp.tool()
def show_plan(
    site: str = "Cape Canaveral / KSC",
    alt_km: float = 400.0,
    inc_deg: float = 51.6,
    epoch_utc: str | None = None,
    hours: float = 24.0,
    mode: str = "kepler",
    beta: float | None = None,
    tgt_lat: float | None = None,
    tgt_lon: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    ascending: bool = True,
) -> dict:
    """Plan an orbit and display it graphically in the running map UI."""
    orb, ls = _orbit(site, lat, lon, alt_km, inc_deg, epoch_utc, ascending)
    gt = orb.ground_track(hours * 3600.0, 60.0, mode=mode, beta=beta)
    d = gt.to_json()
    sc = Scene(title=f"{ls.name} · {alt_km:.0f} km / {inc_deg:.1f}°")
    sc.track("ground track", d["lat"], d["lon"], color="#2a78d6")
    sc.marker(ls.name, ls.lat_deg, ls.lon_deg, symbol="site", color="#898781")
    if gt.extra.get("entry"):
        e = gt.extra["entry"]
        sc.marker("entry", e["lat_deg"], e["lon_deg"], symbol="target", color="#d03b3b")
    if tgt_lat is not None and tgt_lon is not None:
        sc.marker("target", tgt_lat, tgt_lon, symbol="target", color="#eb6834")
        passes = gt.passes(tgt_lat, tgt_lon)
        sc.windows(
            "passes",
            ["closest UTC", "km", "leg"],
            [[p["ca_utc"][5:16], p["min_dist_km"], p["direction"]] for p in passes[:12]],
        )
    res = _post_scene(sc.to_json())
    return {"ok": True, "url": UI_URL, "version": res.get("version"), "summary": orb.summary()}


# Built-in and plugin tools register after the core ones.  Plugin switches
# are read once here (MP_DISABLE_MODULES); the UI's live toggles don't reach
# this process.
for _r in registry().active_records():
    for _fn in _r.get("mcp_tools", []):
        mcp.tool()(_fn)


if __name__ == "__main__":
    mcp.run()
