"""Ground station — a mission-planner plugin, and the worked example of the
plugin tutorial (docs/tutorial.md).

- **Panel** (static/groundstation.js): place a station on the map (or type
  its coordinates), set an elevation mask, see who is above it now and the
  next contact windows; click a window to jump playback there.
- **Map layer**: the station, and the ring inside which the vehicle in focus
  is above the mask at its current altitude.
- **View menu**: limit the horizon footprints to the vehicles above the mask.
- **REST**: `GET /api/groundstation/contacts?<plan args>&gs_lat=&gs_lon=&min_el=`.
- **MCP**: `ground_contacts`.

The math is contacts.py.  It uses only the core's public API.
"""

from __future__ import annotations

from pathlib import Path

from mission_planner.planning import (
    DEFAULT_SITE,
    args_from_params,
    default_dt,
    opt_float,
    track_from_args,
)

from .contacts import contacts, coverage

MAX_WINDOWS = 500


def station_contacts(args, lat_deg: float, lon_deg: float, min_el_deg: float) -> dict:
    """Contact windows of every track of the plan `args` describes (query
    args, as /api/plan takes them), in time order, with the coverage summary."""
    _, meta, gt = track_from_args(args)
    tracks = gt if isinstance(gt, (list, tuple)) else [gt]
    epoch0 = tracks[0].epoch
    windows, span = [], 0.0
    for i, tr in enumerate(tracks):
        # Several tracks share the first one's clock (planning.track_set_payload).
        shift = (tr.epoch - epoch0).total_seconds()
        for w in contacts(tr, lat_deg, lon_deg, min_el_deg):
            for key in ("aos_t_s", "los_t_s", "max_el_t_s"):
                w[key] = round(w[key] + shift, 1)
            w["track"] = tr.id or f"track{i + 1}"
            if tr.label:
                w["label"] = tr.label
            windows.append(w)
        if len(tr.t):
            span = max(span, float(tr.t[-1]) + shift)
    windows.sort(key=lambda w: w["aos_t_s"])
    return {
        "station": {"lat_deg": lat_deg, "lon_deg": lon_deg, "min_el_deg": min_el_deg},
        "coverage": coverage(windows, span),
        "n": len(windows),
        "contacts": windows[:MAX_WINDOWS],
    }


try:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("groundstation", __name__, url_prefix="/api/groundstation")

    @bp.route("/contacts")
    def _contacts_route():
        a = request.args
        lat, lon = opt_float(a, "gs_lat"), opt_float(a, "gs_lon")
        if lat is None or lon is None:
            raise ValueError("gs_lat and gs_lon are required")  # the core answers 400
        return jsonify(station_contacts(a, lat, lon, opt_float(a, "min_el", 10.0)))
except ImportError:  # library use without flask
    bp = None


def ground_contacts(
    gs_lat: float,
    gs_lon: float,
    min_el_deg: float = 10.0,
    site: str = DEFAULT_SITE,
    alt_km: float = 400.0,
    inc_deg: float = 51.6,
    epoch_utc: str | None = None,
    hours: float = 24.0,
    lat: float | None = None,
    lon: float | None = None,
    ascending: bool = True,
    perigee_km: float | None = None,
    apogee_km: float | None = None,
    node_lon_deg: float | None = None,
    argp_deg: float = 0.0,
) -> dict:
    """Contact windows between a ground station and a planned orbit: every
    interval in which the vehicle is at least `min_el_deg` above the
    station's horizon (spherical Earth, no terrain).  Each window gives UTC
    AOS / LOS, duration, maximum elevation and the azimuths at AOS, maximum
    and LOS; `coverage` sums them up (count, total and mean contact time,
    fraction of the span, longest gap).  The orbit parameters are
    plan_orbit's: site or lat/lon, alt_km or perigee_km/apogee_km, inc_deg,
    epoch_utc, hours; site="" with node_lon_deg/argp_deg for an
    element-anchored orbit."""
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
        node_lon_deg=node_lon_deg,
        argp_deg=argp_deg,
    )
    # A 10 s step: contacts of a low orbit last minutes, so AOS/LOS want fine sampling.
    args.update(hours=hours, dt=default_dt(hours, 10.0))
    return station_contacts(args, gs_lat, gs_lon, min_el_deg)


MODULE = {
    "api": 1,
    "name": "groundstation",
    "title": "ground station",
    "description": "a ground station on the map: elevation mask, contact windows, coverage",
    "blueprint": bp,
    "js": "groundstation.js",
    "static_dir": Path(__file__).parent / "static",
    "mcp_tools": [ground_contacts],
    # Contacts work for any track: a planned orbit, a file, a constellation.
    "works_with": ["orbit", "trajectory"],
}
