"""The "File" trajectory source: a plan from a stored file, in whatever format
an active plugin can read.

The user picks or uploads a file (the core file picker, over uploads.py); the
plugin file reader that claims it (filekinds.py; spec key `file_readers`)
describes it for the panel and turns it into a finished trajectory.  The
panel is generic — drawn from the reader's `inspect()` — so a format needs no
UI code of its own.

Request args: `source=file&upload=<id>`, optionally `epoch` (UTC of the
file's t=0) and the reader's own options (e.g. `vehicle`).
"""

from __future__ import annotations

from .. import filekinds, uploads


def file_source(a):
    """The `file` source: the upload named by `upload=`, read by its reader."""
    uid = a.get("upload")
    if not uid:
        raise ValueError("choose a file first")
    return filekinds.read(uid, a)


try:
    from flask import Blueprint, jsonify

    bp = Blueprint("files", __name__, url_prefix="/api/files")

    @bp.route("/<uid>/inspect")
    def _inspect_route(uid):
        """What the File source panel shows for a stored file (see filekinds.inspect)."""
        try:
            uploads.path(uid)
        except ValueError as e:  # no such upload: a missing resource, like /api/uploads/<id>
            return jsonify({"error": str(e)}), 404
        return jsonify(filekinds.inspect(uid))
except ImportError:  # library use without flask
    bp = None


def load_file(path: str, epoch_utc: str | None = None, options: dict | None = None) -> dict:
    """Load a finished trajectory from a local file, in any format an active
    plugin reads (e.g. a simulator's output), and store it so the web UI can
    show it (source "File", then pick the file).

    Returns the reader's summary of the run (title, epoch and where it came
    from, duration, altitude, ...), the entry-interface crossing and ground
    impact when there are any, which reader read it (`reader`), and `upload`,
    the stored file's id.  A file with several tracks (a satellite catalog, a
    multi-vehicle run) gives `tracks`: one brief entry per track.
    `epoch_utc` sets the UTC time of the file's t=0; `options` are the
    reader's own choices (e.g. {"vehicle": "..."}; the reader's inspect lists
    them).
    """
    stored = uploads.put_file(path)
    args = {k: str(v) for k, v in (options or {}).items()}
    if epoch_utc:
        args["epoch"] = epoch_utc
    gt, meta = filekinds.read(stored["id"], args)
    if isinstance(gt, (list, tuple)):  # several tracks: one line each
        return {**meta, "upload": stored["id"], "tracks": [_brief(g) for g in gt]}
    return {**meta, **_brief(gt), "upload": stored["id"]}


def _brief(gt) -> dict:
    """A track for the agent: its annotations and span, not the arrays."""
    out = {k: v for k, v in gt.extra.items() if k != "decay_profile"}
    for key in ("id", "label", "parent"):
        if getattr(gt, key) is not None:
            out[key] = getattr(gt, key)
    if len(gt.t):
        out["span_s"] = [float(gt.t[0]), float(gt.t[-1])]
        out["alt_km_range"] = [
            round(float(gt.alt.min()) * 1e-3, 1),
            round(float(gt.alt.max()) * 1e-3, 1),
        ]
    return out


MODULE = {
    "api": 1,
    "name": "files",
    "title": "file",
    "sources": {"file": {"fn": file_source, "label": "File", "kind": "trajectory"}},
    "blueprint": bp,
    "js": "file_source.js",
    "mcp_tools": [load_file],
    "works_with": ["orbit", "trajectory"],
}
