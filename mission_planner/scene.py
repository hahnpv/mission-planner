"""Scene — the display contract between agents/code and the map UI.

A Scene is a JSON-serializable document of layers the UI knows how to draw.
An agent building a phasing picture from a database emits a Scene and POSTs
it to the running server (`/api/scene`); the open browser tab renders it.

Layer kinds:
    track    {kind, name, lat[], lon[], color?, width?, dash?}
    marker   {kind, name, lat, lon, color?, symbol?}   symbol: dot|target|site
    polygon  {kind, name, lat[], lon[], color?, fill?}
    windows  {kind, name, columns[], rows[][]}          rendered as a table
    label    {kind, text, lat, lon, color?}

A scene may also carry a whole plan (`plan`: an /api/plan payload, as
`planning.plan_payload` makes it).  The UI then shows it as if it had planned
it itself -- timed tracks with playback, the window, footprints and every
module -- and the layers annotate it (a target, a table of passes).

Angles are degrees.  Unknown fields are passed through untouched so the
contract can grow without breaking older servers; `from_json` checks the
shape of the fields it does know, so a malformed document is a ValueError
(HTTP 400) rather than a broken map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real

_KINDS = {"track", "marker", "polygon", "windows", "label"}


def _is_number(x) -> bool:
    return isinstance(x, Real) and not isinstance(x, bool)  # bool is an int to Python


def _check(layer: dict) -> dict:
    kind = layer.get("kind")
    if kind not in _KINDS:
        raise ValueError(f"unknown layer kind {kind!r} (one of {sorted(_KINDS)})")

    def angles(key):
        v = layer.get(key)
        if not isinstance(v, (list, tuple)) or not all(_is_number(x) for x in v):
            raise ValueError(f"{kind} layer {key!r} must be a list of numbers")
        return v

    def angle(key):
        if not _is_number(layer.get(key)):
            raise ValueError(f"{kind} layer {key!r} must be a number")

    if kind in ("track", "polygon"):
        if len(angles("lat")) != len(angles("lon")):
            raise ValueError(f"{kind} layer lat/lon lengths differ")
    elif kind in ("marker", "label"):
        angle("lat")
        angle("lon")
        if kind == "label" and not isinstance(layer.get("text"), str):
            raise ValueError("label layer needs a 'text' string")
    else:  # windows
        cols, rows = layer.get("columns"), layer.get("rows")
        if not isinstance(cols, (list, tuple)) or not isinstance(rows, (list, tuple)):
            raise ValueError("windows layer needs 'columns' and 'rows' lists")
        if not all(isinstance(r, (list, tuple)) for r in rows):
            raise ValueError("windows layer rows must be lists")
    return layer


def _check_track(tr, what: str) -> None:
    if not isinstance(tr, dict):
        raise ValueError(f"scene plan {what} must be an object")
    cols = [tr.get(k) for k in ("t", "lat", "lon", "alt_km")]
    if not all(isinstance(c, list) for c in cols):
        raise ValueError(f"scene plan {what} needs t, lat, lon and alt_km lists")
    if not (len(cols[0]) == len(cols[1]) == len(cols[2]) == len(cols[3]) >= 2):
        raise ValueError(
            f"scene plan {what}: t/lat/lon/alt_km need two or more samples each, same length"
        )


def _check_plan(plan) -> dict:
    """The shape the UI relies on: a summary, a track, and `tracks` when
    there are several.  The numbers themselves are the planner's."""
    if not isinstance(plan, dict) or not isinstance(plan.get("summary"), dict):
        raise ValueError("scene 'plan' must be an /api/plan payload with a 'summary'")
    _check_track(plan.get("track"), "track")
    tracks = plan.get("tracks")
    if tracks is not None:
        if not isinstance(tracks, list):
            raise ValueError("scene plan 'tracks' must be a list")
        for i, tr in enumerate(tracks):
            _check_track(tr, f"tracks[{i}]")
    return plan


@dataclass
class Scene:
    title: str = ""
    layers: list[dict] = field(default_factory=list)
    plan: dict | None = None  # an /api/plan payload the UI shows as its plan

    def add(self, layer: dict) -> Scene:
        self.layers.append(_check(layer))
        return self

    def track(self, name, lat, lon, **style) -> Scene:
        return self.add(
            {"kind": "track", "name": name, "lat": list(lat), "lon": list(lon), **style}
        )

    def marker(self, name, lat, lon, **style) -> Scene:
        return self.add(
            {"kind": "marker", "name": name, "lat": float(lat), "lon": float(lon), **style}
        )

    def polygon(self, name, lat, lon, **style) -> Scene:
        return self.add(
            {"kind": "polygon", "name": name, "lat": list(lat), "lon": list(lon), **style}
        )

    def windows(self, name, columns, rows) -> Scene:
        return self.add(
            {
                "kind": "windows",
                "name": name,
                "columns": list(columns),
                "rows": [list(r) for r in rows],
            }
        )

    def label(self, text, lat, lon, **style) -> Scene:
        return self.add(
            {"kind": "label", "text": text, "lat": float(lat), "lon": float(lon), **style}
        )

    def to_json(self) -> dict:
        out = {"title": self.title, "layers": self.layers}
        if self.plan is not None:
            out["plan"] = self.plan
        return out

    @classmethod
    def from_json(cls, doc) -> Scene:
        """Validate a scene document; ValueError describes what's wrong."""
        if not isinstance(doc, dict):
            raise ValueError("scene must be a JSON object with 'title' and 'layers'")
        title = doc.get("title", "")
        if not isinstance(title, str):
            raise ValueError("scene 'title' must be a string")
        layers = doc.get("layers", [])
        if not isinstance(layers, list):
            raise ValueError("scene 'layers' must be a list")
        plan = doc.get("plan")
        s = cls(title=title, plan=None if plan is None else _check_plan(plan))
        for layer in layers:
            if not isinstance(layer, dict):
                raise ValueError("each scene layer must be an object with a 'kind'")
            s.add(dict(layer))
        return s
