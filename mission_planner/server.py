"""Mission-planner web UI — flask backend.

House pattern: local flask, no external assets, single-file frontend.

    python -m mission_planner.server        # -> http://127.0.0.1:3030

Endpoints
---------
  /api/coastline                    ne_110m coastline geojson
  /api/sites, /api/presets,         catalog: core data plus active data packs
  /api/overlays                     (see catalog.py), each item tagged with its pack
  /api/plan?site|lat,lon & alt & inc & epoch & hours & dt & mode & beta
                                    ground track + orbit summary (decay mode
                                    adds altitude profile + entry prediction)
  POST /api/plan_job?<plan args>    same, as a background job (for slow plugin modes)
  /api/plan_job/<id>                poll it; done -> same payload as /api/plan
  /api/modules                      built-ins + plugins: status, switches, what each adds
  POST /api/modules/<name>          {"enabled": bool} switch a plugin live (UI, routes,
                                    modes, data; MCP tools are fixed at MCP-server start)
  /plugins/<name>/<file>            a plugin's UI assets
  (built-ins and plugins add their own routes: /api/passes, /api/maneuvers/*, ...)
  POST /api/scene                   agent pushes a Scene (JSON) to display
  /api/scene                        current scene (GET)
  /api/events                       SSE stream: notifies the open tab when a
                                    new scene arrives
"""

from __future__ import annotations

import json
import os
import threading
import time

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import catalog, jobs
from .planning import plan_payload, track_from_args
from .plugins import CORE_MODES, registry
from .scene import Scene

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 3030

_scene_lock = threading.Lock()
_scene: dict | None = None
_scene_version = 0


def create_app() -> Flask:
    """The web app over the process-wide plugin registry (plugins.registry())."""
    app = Flask(__name__, static_folder=os.path.join(HERE, "static"))

    # Plugins: every loaded built-in/plugin gets its routes registered up front
    # (flask can't add or remove blueprints once serving); the registry's live
    # switches gate them, so a plugin's panel, map layers, routes, modes and data
    # all switch together.
    _REG = registry()
    _BP_OWNER = {}  # blueprint name -> plugin name
    for _r in _REG.records.values():
        _bp = _r.get("blueprint") if _r.status == "loaded" else None
        if _bp is not None:
            app.register_blueprint(_bp)
            _BP_OWNER[_bp.name] = _r.name

    @app.before_request
    def _gate_inactive_plugins():
        owner = _BP_OWNER.get(request.blueprint)
        if owner is not None and not _REG.active(owner):
            return jsonify({"error": f"plugin '{owner}' is not active"}), 404

    @app.after_request
    def _no_cache(resp):
        if request.path.startswith("/api/") or request.path == "/":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/api/coastline")
    def coastline():
        with open(os.path.join(HERE, "data", "ne_110m_coastline.geojson")) as f:
            return jsonify(json.load(f))

    @app.route("/api/sites")
    def sites():
        return jsonify(catalog.current()["sites"])

    @app.route("/api/presets")
    def presets():
        return jsonify(catalog.current()["presets"])

    @app.route("/api/overlays")
    def overlays():
        return jsonify(catalog.current()["overlays"])

    def _plugin_record(r):
        return {
            "name": r.name,
            "title": r.get("title", r.name),
            "description": r.get("description"),
            "builtin": r.builtin,
            "status": r.status,
            "error": r.error,
            "enabled": r.enabled,
            "active": _REG.active(r.name),
            "waiting_on": _REG.waiting_on(r.name),
            "requires": r.requires,
            "js_url": f"/plugins/{r.name}/{r.get('js')}" if r.get("js") else None,
            "routes": r.get("blueprint") is not None,
            "mcp_tools": [fn.__name__ for fn in r.get("mcp_tools", [])],
            "modes": [
                {
                    "mode": m,
                    "label": p.get("label", m),
                    "needs_beta": bool(p.get("needs_beta")),
                    "slow": bool(p.get("slow")),
                }
                for m, p in (r.get("propagators") or {}).items()
            ],
            "catalog": r.get("catalog") is not None,
        }

    @app.route("/api/modules")
    def modules():
        return jsonify([_plugin_record(r) for r in _REG.records.values()])

    @app.route("/api/modules/<name>", methods=["POST"])
    def toggle_module(name):
        enabled = (request.get_json(silent=True) or {}).get("enabled")
        if not isinstance(enabled, bool):
            return jsonify({"error": 'body must be {"enabled": true|false}'}), 400
        try:
            _REG.set_enabled(name, enabled)
        except KeyError:
            return jsonify({"error": f"no plugin '{name}'"}), 404
        except ValueError as e:
            return jsonify({"error": str(e)}), 409
        # A switch can cascade (requirements on, dependents inactive): send everything.
        return modules()

    @app.route("/plugins/<name>/<path:filename>")
    def plugin_static(name, filename):
        d = _REG.static_dir(name)
        if d is None:
            abort(404)
        return send_from_directory(d, filename)

    @app.route("/api/plan")
    def plan():
        try:
            orb, meta, gt = track_from_args(request.args)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(plan_payload(orb, meta, gt))

    @app.route("/api/plan_job", methods=["POST"])
    def plan_job_start():
        """Start a plan in the background; args as for /api/plan."""
        args = request.args.to_dict()
        mode = args.get("mode", "kepler")
        if mode not in CORE_MODES:
            try:
                _REG.propagator(mode)  # fail fast on an unknown/inactive mode
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
        return jsonify({"job_id": jobs.start(lambda: plan_payload(*track_from_args(args)))})

    @app.route("/api/plan_job/<job_id>")
    def plan_job_poll(job_id):
        out = jobs.poll(job_id)
        if out is None:
            return jsonify({"error": "unknown job"}), 404
        return jsonify(out)

    @app.route("/api/scene", methods=["GET", "POST"])
    def scene():
        global _scene, _scene_version
        if request.method == "POST":
            doc = request.get_json(force=True, silent=True)
            if doc is None:
                return jsonify({"error": "body must be JSON"}), 400
            try:
                validated = Scene.from_json(doc).to_json()
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            with _scene_lock:
                _scene = validated
                _scene_version += 1
                v = _scene_version
            return jsonify({"ok": True, "version": v})
        with _scene_lock:
            return jsonify({"version": _scene_version, "scene": _scene})

    @app.route("/api/events")
    def events():
        def stream():
            last = -1
            while True:
                with _scene_lock:
                    v = _scene_version
                if v != last:
                    last = v
                    yield f"data: {json.dumps({'version': v})}\n\n"
                time.sleep(0.5)

        return Response(
            stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app


app = create_app()


def main():
    app.run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
