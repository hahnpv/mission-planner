"""What kind of file is this, and who reads it?

Plugins declare file readers (spec key `file_readers`, see plugins.py): each
has a cheap `detect(path)`, an `inspect(path)` for the UI and a
`read(path, args)` that makes a plan.  This module asks the active readers
about an uploaded file (uploads.py) and routes to the one that claims it —
the built-in "File" source (modules/files.py) is its main user, but anything
that takes a file can ask the same question.

Detection runs once per upload and is cached in the upload's sidecar along
with the set of readers that were asked; it is re-run only when that set
changes (a plugin installed, or switched on or off).  Exactly one reader must
claim a file: none is "unrecognised", two is reported rather than guessed.
"""

from __future__ import annotations

import sys

from . import uploads
from .plugins import call_plugin, registry


def _detect(rid: str, rp: dict, path) -> bool:
    """A reader's answer; a reader that raises is a "no" (reported on stderr)."""
    try:
        return bool(rp["detect"](path))
    except Exception as e:  # a detector must never break listing or uploading
        print(f"[mission_planner.filekinds] detect '{rid}' raised {e!r}", file=sys.stderr)
        return False


def detect(uid) -> dict:
    """`uploads.info(uid)` plus what kind of file it is:

    kind        reader id, or None
    kind_label  the reader's label (None when unrecognised)
    kind_note   why there's no kind (unrecognised / claimed by several)
    """
    item = uploads.info(uid)
    readers = registry().file_readers()
    asked = sorted(readers)
    cached = item.get("kinds")
    if not isinstance(cached, dict) or cached.get("asked") != asked:
        path = uploads.path(uid)
        claims = [rid for rid, rp in readers.items() if _detect(rid, rp, path)]
        cached = {"asked": asked, "claims": claims}
        item = uploads.update_info(uid, kinds=cached)
    claims = cached["claims"]
    out = {k: v for k, v in item.items() if k != "kinds"}
    if len(claims) == 1:
        rid = claims[0]
        return {**out, "kind": rid, "kind_label": readers[rid].get("label", rid), "kind_note": None}
    note = (
        "no active plugin reads this file"
        if not claims
        else f"claimed by several readers ({', '.join(claims)}) — report it"
    )
    return {**out, "kind": None, "kind_label": None, "kind_note": note}


def reader_for(uid) -> tuple[str, dict, dict]:
    """(reader id, reader spec, detect() result) for upload `uid`; a
    ValueError says why when no single active reader claims it."""
    d = detect(uid)
    if d["kind"] is None:
        raise ValueError(f"{d['name']}: {d['kind_note']}")
    return d["kind"], registry().file_reader(d["kind"]), d


def _call(rid: str, fn, *a):
    return call_plugin("file_readers", rid, fn, *a)


def inspect(uid) -> dict:
    """What the File source panel shows for upload `uid` (see docs/plugins.md):
    the reader's inspect() plus kind / kind_label / name."""
    rid, rp, d = reader_for(uid)
    res = _call(rid, rp["inspect"], uploads.path(uid))
    return {**res, "kind": rid, "kind_label": d["kind_label"], "name": d["name"]}


def read(uid, args):
    """(GroundTrack, meta) from upload `uid` through the reader that claims
    it; meta gains file / reader / reader_label."""
    rid, rp, d = reader_for(uid)
    gt, meta = _call(rid, rp["read"], uploads.path(uid), args)
    return gt, {**meta, "file": d["name"], "reader": rid, "reader_label": d["kind_label"]}
