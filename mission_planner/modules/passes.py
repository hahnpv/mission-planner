"""Target-pass module (built in) — overflight windows for a point on the ground.

Click a spot on the map and get the times the planned orbit's subpoint comes
within a radius of it: AOS/LOS/closest approach, miss distance, which leg,
altitude.  This is *subpoint proximity*, not line of sight — "does it fly
over my site", where the core's horizon footprint answers "is it above my
site's horizon".

The search itself is `GroundTrack.passes()` in the core library (used by the
`find_passes` MCP tool and by `show_plan` too); this module is the UI and
REST skin over it (the panel, the map graphics, the map-click handler and
`/api/passes`).
"""

from __future__ import annotations

from ..planning import track_from_args

try:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("passes", __name__)

    @bp.route("/api/passes")
    def _passes_route():
        try:
            _, _, gt = track_from_args(request.args)
            win = gt.passes(
                float(request.args["tgt_lat"]),
                float(request.args["tgt_lon"]),
                within_km=float(request.args.get("within_km", 500.0)),
            )
        except (ValueError, KeyError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"n": len(win), "passes": win})
except ImportError:  # library use without flask
    bp = None


MODULE = {
    "api": 1,
    "name": "passes",
    "title": "target passes",
    "blueprint": bp,
    "js": "passes.js",
    "mcp_tools": [],
    # Pass search needs only a track, so it works on finished trajectories too.
    "works_with": ["orbit", "trajectory"],
}
