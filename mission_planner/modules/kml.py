"""The KML file reader: Google Earth tracks and paths as a plan.

A reader for the built-in "File" source (modules/files.py; spec key
`file_readers`), so a trajectory made elsewhere can be shown without any
plugin: most tools export KML.  Reads `.kml` and `.kmz` (a zip holding the
KML).  Every Placemark with a `<gx:Track>` (timed: `<when>` + `<gx:coord>`),
a `<gx:MultiTrack>` (its tracks joined end to end) or a `<LineString>` (a
path, untimed) becomes one track named after the Placemark; points,
polygons, styles and overlays are ignored.  When a file holds both, the
timed tracks are the plan and the paths are taken as decoration.

Time: a timed file's t=0 is its earliest `<when>`; an untimed path is
sampled every `step` seconds (an option of the panel) from the file's first
TimeStamp / TimeSpan begin, else J2000.  `epoch` in the request moves t=0
to that instant instead.  Altitude is metres, as KML has it (clampToGround
puts a track on the ground).  Long tracks are thinned evenly to
`planning.TARGET_POINTS` samples.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..groundtrack import GroundTrack
from ..orbit import wrap_pi
from ..planning import TARGET_POINTS, opt_float, parse_epoch
from ..timebase import as_utc

J2000 = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
STEPS = ("1", "10", "30", "60", "300")  # the panel's sample steps for an untimed path [s]
DEFAULT_STEP = "60"
KML_MARKS = (b"<kml", b"opengis.net/kml", b"earth.google.com/kml")


# ---------------------------------------------------------------- the document
def _local(el) -> str:
    """An element's tag without its namespace (kml, gx or none at all)."""
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _kml_entry(zf: zipfile.ZipFile) -> str | None:
    names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
    if not names:
        return None
    return next((n for n in names if n.lower() == "doc.kml"), names[0])


def _load(path) -> ET.Element:
    """The document root of a .kml or .kmz file."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            name = _kml_entry(zf)
            if name is None:
                raise ValueError("the KMZ archive holds no .kml document")
            data = zf.read(name)
    else:
        data = Path(path).read_bytes()
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"not well-formed KML: {e}") from None


def detect(path) -> bool:
    """A KML document (the `<kml>` root or its namespace near the top) or a
    KMZ archive with a .kml inside."""
    try:
        with open(path, "rb") as f:
            head = f.read(2048)
    except OSError:
        return False
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(path) as zf:
                return _kml_entry(zf) is not None
        except zipfile.BadZipFile:
            return False
    if b"\0" in head:
        return False
    return any(mark in head for mark in KML_MARKS)


# ---------------------------------------------------------------- placemarks
@dataclass
class _Mark:
    """One Placemark's geometry: the segments of a timed gx:Track /
    gx:MultiTrack (`when` filled) or of an untimed LineString path."""

    name: str
    coords: np.ndarray  # (n, 3): lon, lat [deg], alt [m]
    when: list[datetime] | None  # one per row, or None for a path

    @property
    def timed(self) -> bool:
        return self.when is not None


def _when(s: str, where: str) -> datetime:
    """A KML dateTime: ISO 8601, down to a bare year or month."""
    s = s.strip()
    full = s + {4: "-01-01", 7: "-01"}.get(len(s), "")
    try:
        return as_utc(datetime.fromisoformat(full.replace("Z", "+00:00")))
    except ValueError:
        raise ValueError(f"{where}: <when> {s!r} is not an ISO 8601 date-time") from None


def _floats(text: str, where: str, n_min: int) -> list[float]:
    try:
        vals = [float(x) for x in text.replace(",", " ").split()]
    except ValueError:
        raise ValueError(f"{where}: coordinates {text.strip()[:40]!r} are not numbers") from None
    if len(vals) < n_min:
        raise ValueError(f"{where}: coordinates {text.strip()[:40]!r} need longitude and latitude")
    return vals


def _clamped(geom) -> bool:
    for el in geom:
        if _local(el) == "altitudeMode" and (el.text or "").strip() == "clampToGround":
            return True
    return False


def _track_segment(track, where: str) -> tuple[list[datetime], list[list[float]]]:
    whens, coords = [], []
    for el in track:
        tag = _local(el)
        if tag == "when":
            whens.append(_when(el.text or "", where))
        elif tag == "coord":
            v = _floats(el.text or "", where, 2)
            coords.append([v[0], v[1], v[2] if len(v) > 2 else 0.0])
    if len(whens) != len(coords):
        raise ValueError(
            f"{where}: {len(whens)} <when> for {len(coords)} <gx:coord> — a gx:Track needs one each"
        )
    return whens, coords


def _path_segment(line, where: str) -> list[list[float]]:
    coords = []
    for el in line:
        if _local(el) == "coordinates":
            for tup in (el.text or "").split():
                v = _floats(tup, where, 2)
                coords.append([v[0], v[1], v[2] if len(v) > 2 else 0.0])
    return coords


def _placemarks(root) -> list[_Mark]:
    out = []
    for i, pm in enumerate(el for el in root.iter() if _local(el) == "Placemark"):
        name = next((el.text or "" for el in pm if _local(el) == "name"), "").strip()
        where = f"placemark {name!r}" if name else f"placemark {i + 1}"
        whens, timed, paths = [], [], []
        for geom in pm.iter():
            tag = _local(geom)
            if tag == "Track":
                w, c = _track_segment(geom, where)
                whens += w
                timed += [[x, y, 0.0 if _clamped(geom) else z] for x, y, z in c]
            elif tag == "LineString":
                c = _path_segment(geom, where)
                paths += [[x, y, 0.0 if _clamped(geom) else z] for x, y, z in c]
        if timed:
            out.append(_Mark(name, np.array(timed, dtype=float), whens))
        elif paths:
            out.append(_Mark(name, np.array(paths, dtype=float), None))
    return out


def _doc_time(root) -> datetime | None:
    """The first TimeStamp / TimeSpan begin anywhere in the document."""
    for el in root.iter():
        tag = _local(el)
        if tag in ("TimeStamp", "TimeSpan"):
            for sub in el:
                if _local(sub) in ("when", "begin") and (sub.text or "").strip():
                    return _when(sub.text, tag)
    return None


def _doc_name(root, path) -> str:
    for el in root.iter():
        if _local(el) == "Document":
            name = next((s.text or "" for s in el if _local(s) == "name"), "").strip()
            if name:
                return name
            break
    return Path(path).stem


@dataclass
class _Doc:
    title: str
    marks: list[_Mark]  # the tracks the plan shows
    paths_ignored: int  # untimed paths set aside because the file has timed tracks
    t0: datetime  # what a blank epoch means
    t0_from: str


def _read_doc(path) -> _Doc:
    root = _load(path)
    marks = _placemarks(root)
    if not marks:
        raise ValueError(
            "no track in this file: no Placemark with a <gx:Track>, <gx:MultiTrack> or <LineString>"
        )
    timed = [m for m in marks if m.timed]
    if timed:
        t0 = min(min(m.when) for m in timed)
        return _Doc(_doc_name(root, path), timed, len(marks) - len(timed), t0, "the first <when>")
    stamp = _doc_time(root)
    if stamp is not None:
        return _Doc(_doc_name(root, path), marks, 0, stamp, "the file's TimeStamp")
    return _Doc(_doc_name(root, path), marks, 0, J2000, "J2000 (the file has no times)")


# ---------------------------------------------------------------- the reader
def _span(seconds: float) -> str:
    if seconds < 7200:
        return f"{seconds / 60:.1f} min"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def inspect(path) -> dict:
    doc = _read_doc(path)
    names = [m.name or f"track {i + 1}" for i, m in enumerate(doc.marks)]
    shown = ", ".join(names[:3]) + (f" … (+{len(names) - 3})" if len(names) > 3 else "")
    n = sum(len(m.coords) for m in doc.marks)
    timed = doc.marks[0].timed
    if timed:
        last = max(max(m.when) for m in doc.marks)
        what = f"timed, {n} samples over {_span((last - doc.t0).total_seconds())}"
    else:
        what = f"{n} points, no times — sampled every {DEFAULT_STEP} s unless chosen otherwise"
    kind = "track" if timed else "path"
    return {
        "summary": f"{len(names)} {kind}{'s' * (len(names) != 1)}: {shown} · {what}",
        "warning": (
            f"{doc.paths_ignored} untimed path{'s' * (doc.paths_ignored != 1)} "
            "set aside: the timed tracks are the plan"
            if doc.paths_ignored
            else None
        ),
        "epoch_utc": doc.t0.isoformat(),
        "epoch_note": doc.t0_from,
        "options": []
        if timed
        else [
            {
                "key": "step",
                "label": "sample step (s)",
                "choices": list(STEPS),
                "default": DEFAULT_STEP,
            }
        ],
    }


def _slug(name: str, i: int, seen: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"track{i + 1}"
    tid, k = base, 1
    while tid in seen:
        k += 1
        tid = f"{base}-{k}"
    seen.add(tid)
    return tid


def _thin(n: int) -> np.ndarray:
    if n <= TARGET_POINTS:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, TARGET_POINTS).round().astype(int))


def read(path, args):
    """(GroundTrack or [GroundTrack], meta) for the file's tracks or paths."""
    doc = _read_doc(path)
    timed = doc.marks[0].timed
    step = opt_float(args, "step", float(DEFAULT_STEP))
    if step <= 0:
        raise ValueError("step must be positive")
    requested = args.get("epoch")
    epoch0 = parse_epoch(requested) if requested else doc.t0
    tracks, seen = [], set()
    for i, m in enumerate(doc.marks):
        if timed:
            t = np.array([(w - doc.t0).total_seconds() for w in m.when], dtype=float)
        else:
            t = np.arange(len(m.coords), dtype=float) * step
        keep = _thin(len(t))
        lon, lat, alt = m.coords[keep].T
        tracks.append(
            GroundTrack(
                epoch0,
                t[keep],
                np.radians(lat),
                wrap_pi(np.radians(lon)),
                alt,
                id=_slug(m.name, i, seen),
                label=m.name or None,
            )
        )
    meta = {
        "title": doc.title if len(tracks) > 1 else (tracks[0].label or doc.title),
        "tracks": len(tracks),
        "timed": timed,
        "epoch_utc": epoch0.isoformat(),
        "epoch_from": "request" if requested else doc.t0_from,
        "duration_s": max(float(g.t[-1]) for g in tracks),
        "samples": int(sum(len(g.t) for g in tracks)),
    }
    if not timed:
        meta["step_s"] = step
    if doc.paths_ignored:
        meta["paths_ignored"] = doc.paths_ignored
    if len(tracks) == 1:
        return tracks[0], meta
    meta["primary"] = tracks[0].id
    return tracks, meta


MODULE = {
    "api": 1,
    "name": "kml",
    "title": "KML",
    "description": "reads KML / KMZ tracks and paths for the File source",
    "file_readers": {
        "kml": {
            "label": "KML track",
            "extensions": [".kml", ".kmz"],
            "detect": detect,
            "inspect": inspect,
            "read": read,
        }
    },
}
