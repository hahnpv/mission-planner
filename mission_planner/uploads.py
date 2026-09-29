"""Uploaded files, kept server-side under a content hash.

A trajectory source that reads a file (a simulation output, an ephemeris)
can't take the file itself as a query arg, so the file goes up once
(`POST /api/uploads`, or `put_file` from Python) and the plan args carry its
id: `source=<id>&upload=<upload id>`.  The id is a prefix of the content's
SHA-256, so the same file always gets the same id and a plan's args stay
reproducible across server restarts.

The store is a directory: `MP_UPLOAD_DIR`, else
`$XDG_CACHE_HOME/mission-planner/uploads` (`~/.cache/...`).  Each upload is
`<id>` (the bytes) plus `<id>.json` (original name, size, upload time);
`list_uploads` is what the UI's file picker browses, and `delete` what its
remove button calls.  Nothing expires on its own.  A deleted file's id stops
resolving, so a plan that named it needs the file uploaded again (same
content, same id).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

# Ceiling on one upload (flask's MAX_CONTENT_LENGTH for the whole request).
MAX_UPLOAD_BYTES = 1 << 30
_ID_LEN = 24
_ID_RE = re.compile(rf"[0-9a-f]{{{_ID_LEN}}}")


def upload_dir() -> Path:
    d = os.environ.get("MP_UPLOAD_DIR")
    if not d:
        cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        d = os.path.join(cache, "mission-planner", "uploads")
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _check_id(uid) -> str:
    if not isinstance(uid, str) or not _ID_RE.fullmatch(uid):
        raise ValueError(f"{uid!r} is not an upload id — upload the file first")
    return uid


def put_stream(f: BinaryIO, name: str) -> dict:
    """Store the bytes read from `f` under their content id; returns `info`.
    Uploading the same content again keeps its id and refreshes its name and
    upload time."""
    d = upload_dir()
    h = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(dir=d, prefix=".part-", delete=False) as tmp:
        try:
            while chunk := f.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError(f"upload exceeds {MAX_UPLOAD_BYTES >> 20} MB")
                h.update(chunk)
                tmp.write(chunk)
        except BaseException:
            tmp.close()
            os.unlink(tmp.name)
            raise
    uid = h.hexdigest()[:_ID_LEN]
    os.replace(tmp.name, d / uid)
    meta = {
        "id": uid,
        "name": os.path.basename(name or "") or uid,
        "size": size,
        "uploaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (d / f"{uid}.json").write_text(json.dumps(meta))
    return meta


def put_file(path: str | os.PathLike) -> dict:
    """Store a local file (library / MCP-tool use); returns `info`."""
    with open(path, "rb") as f:
        return put_stream(f, os.path.basename(path))


def path(uid) -> Path:
    """Where upload `uid` lives on disk; ValueError when there's no such upload."""
    p = upload_dir() / _check_id(uid)
    if not p.is_file():
        raise ValueError(f"no upload {uid!r} on this server — upload the file again")
    return p


def info(uid) -> dict:
    """{id, name, size, uploaded_utc} for upload `uid`."""
    p = path(uid)
    try:
        return json.loads(p.with_name(f"{uid}.json").read_text())
    except (OSError, ValueError):
        return {"id": uid, "name": uid, "size": p.stat().st_size, "uploaded_utc": None}


def update_info(uid, **fields) -> dict:
    """Merge `fields` into upload `uid`'s sidecar (e.g. what kind of file it
    is, filekinds.py); returns the updated `info`."""
    item = {**info(uid), **fields}
    path(uid).with_name(f"{uid}.json").write_text(json.dumps(item))
    return item


def delete(uid) -> dict:
    """Remove upload `uid` (bytes and sidecar); returns its last `info`.
    ValueError when there's no such upload."""
    item = info(uid)
    p = path(uid)
    p.with_name(f"{uid}.json").unlink(missing_ok=True)
    p.unlink(missing_ok=True)
    return item


def list_uploads(exts=None) -> list[dict]:
    """Every stored upload's `info`, newest first; `exts` (e.g. [".h5"])
    keeps those whose original name ends in one of them (case-insensitive)."""
    want = tuple(e.lower() for e in exts or ())
    out = []
    for meta in upload_dir().glob("*.json"):
        uid = meta.stem
        if not _ID_RE.fullmatch(uid):
            continue
        try:
            item = info(uid)
        except ValueError:  # sidecar without its data
            continue
        if want and not item["name"].lower().endswith(want):
            continue
        out.append(item)
    out.sort(key=lambda x: x.get("uploaded_utc") or "", reverse=True)
    return out
