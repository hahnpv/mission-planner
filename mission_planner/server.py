"""Mission-planner web UI — flask backend.

House pattern: local flask, no external assets, a static frontend
(static/index.html + static/ui/*.js + the modules' static/modules/*.js).

    python -m mission_planner.server        # -> http://127.0.0.1:3030

Endpoints
---------
  /api/coastline                    ne_110m coastline geojson
  /api/sites, /api/presets,         catalog: core data plus active data packs
  /api/overlays                     (see catalog.py), each item tagged with its pack
  /api/plan?<plan args>             ground track + orbit summary.  Args (planning.py):
                                    source=site|preset|<plugin source>; site=<name> or
                                    lat&lon; hp&ha (or alt) &inc&epoch&leg&pofs for a site,
                                    node_lon&argp for a preset; hours&dt&mode&beta
  POST /api/uploads                 multipart `file`: store a file for a source that reads
                                    one (uploads.py); -> {id, name, size, kind, ...}, pass
                                    upload=<id>.  kind: the plugin file reader that claims
                                    it (filekinds.py), or null with kind_note
  /api/uploads?ext=.h5,.hdf5        stored uploads (newest first), optionally by extension
  /api/uploads/<id>                 {id, name, size, uploaded_utc, kind, ...} of a stored upload
  DELETE /api/uploads/<id>          remove it; -> its last {id, name, ...}
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

Every /api error is JSON {"error": ...}: 400 for bad input (ValueError),
404/409 for missing or unswitchable things, 500 for a plugin's or the core's
own failure (the traceback goes to stderr).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback

from flask import Flask, Response, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import catalog, filekinds, jobs, uploads
from .planning import plan_from_args, source_of
from .plugins import CORE_MODES, CORE_SOURCES, registry
from .scene import Scene

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 3030
SSE_HEARTBEAT_S = 15.0


class SceneStore:
    """The one scene on display, versioned so SSE listeners can wake up."""

    def __init__(self):
        self._cond = threading.Condition()
        self.version = 0
        self.scene: dict | None = None

    def set(self, scene: dict) -> int:
        with self._cond:
            self.scene = scene
            self.version += 1
            self._cond.notify_all()
            return self.version

    def get(self) -> dict:
        with self._cond:
            return {"version": self.version, "scene": self.scene}

    def wait_beyond(self, version: int, timeout: float) -> int:
        """Block until the version passes `version` or `timeout` elapses."""
        with self._cond:
            self._cond.wait_for(lambda: self.version != version, timeout=timeout)
            return self.version


def create_app() -> Flask:
    """The web app over the process-wide plugin registry (plugins.registry()).
    Never raises for a plugin's sake: a blueprint that can't be registered
    marks its plugin failed."""
    app = Flask(__name__, static_folder=os.path.join(HERE, "static"))
    app.extensions["mp_scene"] = scenes = SceneStore()
    app.config["MAX_CONTENT_LENGTH"] = uploads.MAX_UPLOAD_BYTES

    # Plugins: every loaded built-in/plugin gets its routes registered up front
    # (flask can't add or remove blueprints once serving); the registry's live
    # switches gate them, so a plugin's panel, map layers, routes, modes and data
    # all switch together.
    reg = registry()
    bp_owner = {}  # blueprint name -> plugin name
    for r in reg.records.values():
        bp = r.get("blueprint") if r.status == "loaded" else None
        if bp is None:
            continue
        try:
            app.register_blueprint(bp)
        except Exception as e:
            reg.fail(r.name, f"blueprint '{bp.name}' could not be registered: {e}")
            print(f"[mission_planner.server] {r.name}: {r.error}", file=sys.stderr)
            continue
        bp_owner[bp.name] = r.name

    @app.before_request
    def _gate_inactive_plugins():
        # request.blueprints lists the chain innermost-first; the root is the
        # plugin's own blueprint, so nested blueprints are gated too.
        root = request.blueprints[-1] if request.blueprints else None
        owner = bp_owner.get(root)
        if owner is not None and not reg.active(owner):
            return jsonify({"error": f"plugin '{owner}' is not active"}), 404

    @app.after_request
    def _no_cache(resp):
        if request.path.startswith("/api/") or request.path == "/":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(Exception)
    def _json_errors(e):
        if isinstance(e, HTTPException):
            if request.path.startswith("/api/"):
                return jsonify({"error": e.description}), e.code
            return e
        if isinstance(e, ValueError):
            return jsonify({"error": str(e)}), 400
        traceback.print_exc()
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

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
            "active": reg.active(r.name),
            "waiting_on": reg.waiting_on(r.name),
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
            "sources": [
                {
                    "id": sid,
                    "label": sp.get("label", sid),
                    "kind": sp["kind"],
                    "slow": bool(sp.get("slow")),
                }
                for sid, sp in (r.get("sources") or {}).items()
            ],
            "works_with": list(r.get("works_with", ["orbit"])),
        }

    @app.route("/api/modules")
    def modules():
        return jsonify([_plugin_record(r) for r in reg.records.values()])

    @app.route("/api/modules/<name>", methods=["POST"])
    def toggle_module(name):
        body = request.get_json(silent=True)
        enabled = body.get("enabled") if isinstance(body, dict) else None
        if not isinstance(enabled, bool):
            return jsonify({"error": 'body must be {"enabled": true|false}'}), 400
        try:
            reg.set_enabled(name, enabled)
        except KeyError:
            return jsonify({"error": f"no plugin '{name}'"}), 404
        except ValueError as e:
            return jsonify({"error": str(e)}), 409
        # A switch can cascade (requirements on, dependents inactive): send everything.
        return modules()

    @app.route("/plugins/<name>/<path:filename>")
    def plugin_static(name, filename):
        d = reg.static_dir(name)
        if d is None:
            abort(404)
        return send_from_directory(d, filename)

    @app.route("/api/uploads", methods=["POST"])
    def upload():
        f = request.files.get("file")
        if f is None:
            return jsonify({"error": "no file: send multipart form data with a 'file' field"}), 400
        return jsonify(filekinds.detect(uploads.put_stream(f.stream, f.filename or "")["id"]))

    @app.route("/api/uploads")
    def upload_list():
        exts = [e.strip() for e in request.args.get("ext", "").split(",") if e.strip()]
        return jsonify([filekinds.detect(x["id"]) for x in uploads.list_uploads(exts)])

    @app.route("/api/uploads/<uid>", methods=["GET", "DELETE"])
    def upload_info(uid):
        try:
            if request.method == "DELETE":
                return jsonify(uploads.delete(uid))
            return jsonify(filekinds.detect(uid))
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/plan")
    def plan():
        return jsonify(plan_from_args(request.args))

    @app.route("/api/plan_job", methods=["POST"])
    def plan_job_start():
        """Start a plan in the background; args as for /api/plan."""
        args = request.args.to_dict()
        # Fail fast on an unknown/inactive source or mode (a trajectory
        # source has no mode).
        sid = source_of(args)
        kind = "orbit" if sid in CORE_SOURCES else reg.source(sid)["kind"]
        mode = args.get("mode") or "kepler"
        if kind == "orbit" and mode not in CORE_MODES:
            reg.propagator(mode)
        return jsonify({"job_id": jobs.start(lambda: plan_from_args(args))})

    @app.route("/api/plan_job/<job_id>")
    def plan_job_poll(job_id):
        out = jobs.poll(job_id)
        if out is None:
            return jsonify({"error": "unknown job"}), 404
        return jsonify(out)

    @app.route("/api/scene", methods=["GET", "POST"])
    def scene():
        if request.method == "POST":
            doc = request.get_json(force=True, silent=True)
            if doc is None:
                return jsonify({"error": "body must be JSON"}), 400
            validated = Scene.from_json(doc).to_json()  # ValueError -> 400
            return jsonify({"ok": True, "version": scenes.set(validated)})
        return jsonify(scenes.get())

    @app.route("/api/events")
    def events():
        def stream():
            last = -1
            while True:
                v = scenes.wait_beyond(last, SSE_HEARTBEAT_S)
                if v != last:
                    last = v
                    yield f"data: {json.dumps({'version': v})}\n\n"
                else:
                    # A comment keeps the connection warm and, more to the
                    # point, makes a closed one fail here instead of never.
                    yield ": ping\n\n"

        return Response(stream(), mimetype="text/event-stream")  # _no_cache: no-store

    return app


_APP: Flask | None = None


def __getattr__(name):
    # `server.app` for `flask --app` and existing callers, built on first use
    # rather than at import so importing this module has no side effects.
    if name == "app":
        global _APP
        if _APP is None:
            _APP = create_app()
        return _APP
    raise AttributeError(name)


def main():
    create_app().run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    main()


__all__ = ["create_app", "main", "PORT", "SceneStore"]
