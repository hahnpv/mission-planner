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
    the stored file's id.  `epoch_utc` sets the UTC time of the file's t=0;
    `options` are the reader's own choices (e.g. {"vehicle": "..."}; the
    reader's inspect lists them).
    """
    stored = uploads.put_file(path)
    args = {k: str(v) for k, v in (options or {}).items()}
    if epoch_utc:
        args["epoch"] = epoch_utc
    gt, meta = filekinds.read(stored["id"], args)
    # Small annotations only: the arrays are for the map, not the agent.
    extra = {k: v for k, v in gt.extra.items() if k != "decay_profile"}
    return {**meta, **extra, "upload": stored["id"]}


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
