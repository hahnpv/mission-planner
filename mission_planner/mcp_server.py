"""Mission-planner MCP server.

Exposes the orbit-planning library to an agent, plus `show_scene` /
`show_plan` which push graphics into a running web UI (`python -m
mission_planner.server`, http://127.0.0.1:3030) so results appear on the
map in front of the user.

Core tools: plan_orbit, list_launch_sites, show_scene, show_plan
(plugins.CORE_MCP_TOOLS).  Built-in modules and active plugins add theirs
(`mcp_tools` in their spec) when this process starts; the UI's live plugin
switches don't reach it — MP_DISABLE_MODULES does.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

from . import catalog
from .planning import (
    DEFAULT_SITE,
    args_from_params,
    default_dt,
    orbit_from_params,
    plan_payload,
    track_from_args,
)
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
    except urllib.error.HTTPError as e:  # the UI answered, and said no
        try:
            why = json.loads(e.read()).get("error", e.reason)
        except Exception:
            why = e.reason
        raise RuntimeError(f"mission-planner UI rejected the scene ({e.code}): {why}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(
            f"mission-planner UI not reachable at {UI_URL} — start it with "
            f"`python -m mission_planner.server` (error: {e})"
        ) from e


@mcp.tool()
def list_launch_sites() -> dict:
    """List the launch-site catalog: the core's sites plus those of every data
    pack active when this server started, each tagged with its pack."""
    return {
        "sites": [
            {"name": s["name"], "lat": s["lat"], "lon": s["lon"], "pack": s["pack"]}
            for s in catalog.current()["sites"]
        ]
    }


@mcp.tool()
def plan_orbit(
    site: str = DEFAULT_SITE,
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
        hours: propagation horizon (the sample step coarsens with it).
        mode: "kepler" (two-body + J2), "decay" (averaged King-Hele drag
            decay; needs beta), or a mode provided by an installed plugin
            (an unknown mode's error lists the available ones).
        beta: ballistic coefficient m/(Cd*A) [kg/m^2] for drag modes.
    Returns orbit summary (period, revs/day, RAAN drift, launch azimuth);
    drag modes add the predicted entry epoch/subpoint and final altitude,
    and modes that fly to the ground add the impact point.
    """
    orb, ls = orbit_from_params(
        site=site,
        lat=lat,
        lon=lon,
        alt_km=alt_km,
        inc_deg=inc_deg,
        epoch_utc=epoch_utc,
        ascending=ascending,
        perigee_km=perigee_km,
        apogee_km=apogee_km,
        perigee_offset_deg=perigee_offset_deg,
        node_lon_deg=node_lon_deg,
        argp_deg=argp_deg,
    )
    gt = orb.ground_track(hours * 3600.0, default_dt(hours, 60.0), mode=mode, beta=beta)
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
    site: str = DEFAULT_SITE,
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
    perigee_km: float | None = None,
    apogee_km: float | None = None,
    perigee_offset_deg: float = 0.0,
    node_lon_deg: float | None = None,
    argp_deg: float = 0.0,
) -> dict:
    """Plan an orbit (same parameters as plan_orbit) and show it in the
    running map UI as its plan: the timed track with playback, the display
    window and the side panels, as if the user had planned it there.  With
    tgt_lat/tgt_lon the target is marked and the passes over it listed."""
    args = args_from_params(
        site=site,
        lat=lat,
        lon=lon,
        alt_km=alt_km,
        inc_deg=inc_deg,
        epoch_utc=epoch_utc,
        ascending=ascending,
        perigee_km=perigee_km,
        apogee_km=apogee_km,
        perigee_offset_deg=perigee_offset_deg,
        node_lon_deg=node_lon_deg,
        argp_deg=argp_deg,
    )
    args.update(hours=hours, dt=default_dt(hours, 60.0), mode=mode)
    if beta is not None:
        args["beta"] = beta
    orb, meta, gt = track_from_args(args)
    plan = plan_payload(orb, meta, gt)
    s = plan["summary"]
    shape = f"{s['perigee_km']:.0f}x{s['apogee_km']:.0f} km" if orb.e > 1e-4 else f"{alt_km:.0f} km"
    where = s["site"] if s["site_lat"] is not None else f"node {node_lon_deg or 0:.0f}°E"
    sc = Scene(title=f"{where} · {shape} / {inc_deg:.1f}°", plan=plan)
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


def _register_plugin_tools():
    """Built-in and plugin tools, after the core ones.  Names are unique by
    construction: the registry fails a plugin whose tool name is taken."""
    for r in registry().active_records():
        for fn in r.get("mcp_tools", []):
            mcp.tool()(fn)


_register_plugin_tools()


if __name__ == "__main__":
    mcp.run()
