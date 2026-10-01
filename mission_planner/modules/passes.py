"""Target-pass module (built in) — overflight windows for a point on the ground.

Click a spot on the map and get the times the planned orbit's subpoint comes
within a radius of it: AOS/LOS/closest approach, miss distance, which leg,
altitude.  This is *subpoint proximity*, not line of sight — "does it fly
over my site", where the core's horizon footprint answers "is it above my
site's horizon".

The search itself is `GroundTrack.passes()` in the core library; this module
is the UI, REST and MCP skin over it (the panel, the map graphics, the
map-click handler, `/api/passes` and the `find_passes` tool).
"""

from __future__ import annotations

from ..planning import DEFAULT_SITE, default_dt, orbit_from_params, req_float, track_from_args

try:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("passes", __name__)

    @bp.route("/api/passes")
    def _passes_route():
        """Passes of every track of the plan the query args describe, in time
        order; on a multi-track plan each pass names its `track` (and `label`),
        with times on the first track's clock as the plan's are."""
        a = request.args
        if "tgt_lat" not in a or "tgt_lon" not in a:
            raise ValueError("tgt_lat and tgt_lon are required")
        _, _, gt = track_from_args(a)
        tracks = gt if isinstance(gt, (list, tuple)) else [gt]
        lat, lon = req_float(a, "tgt_lat", 0.0), req_float(a, "tgt_lon", 0.0)
        within = req_float(a, "within_km", 500.0)
        win = []
        for i, tr in enumerate(tracks):
            shift = (tr.epoch - tracks[0].epoch).total_seconds()
            for p in tr.passes(lat, lon, within_km=within):
                if len(tracks) > 1:
                    p["ca_t_s"] = round(p["ca_t_s"] + shift, 1)
                    p["track"] = tr.id or f"track{i + 1}"
                    if tr.label:
                        p["label"] = tr.label
                win.append(p)
        win.sort(key=lambda p: p["ca_t_s"])
        return jsonify({"n": len(win), "passes": win})
except ImportError:  # library use without flask
    bp = None


def find_passes(
    tgt_lat: float,
    tgt_lon: float,
    site: str = DEFAULT_SITE,
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
    heading, and leg direction.  The orbit parameters are plan_orbit's:
    perigee_km/apogee_km/perigee_offset_deg plan an elliptic orbit; site=""
    with node_lon_deg/argp_deg plans an element-anchored orbit.
    """
    orb, _ = orbit_from_params(
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
    gt = orb.ground_track(hours * 3600.0, default_dt(hours), mode=mode, beta=beta)
    passes = gt.passes(tgt_lat, tgt_lon, within_km=within_km)
    return {"n": len(passes), "passes": passes}


MODULE = {
    "api": 1,
    "name": "passes",
    "title": "target passes",
    "blueprint": bp,
    "js": "passes.js",
    "mcp_tools": [find_passes],
    # Pass search needs only a track, so it works on finished trajectories too.
    "works_with": ["orbit", "trajectory"],
}
