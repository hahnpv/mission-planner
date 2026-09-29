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

Angles are degrees.  Unknown fields are passed through untouched so the
contract can grow without breaking older servers; `from_json` checks the
shape of the fields it does know, so a malformed document is a ValueError
(HTTP 400) rather than a broken map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real

_KINDS = {"track", "marker", "polygon", "windows", "label"}


def _check(layer: dict) -> dict:
    kind = layer.get("kind")
    if kind not in _KINDS:
        raise ValueError(f"unknown layer kind {kind!r} (one of {sorted(_KINDS)})")

    def angles(key):
        v = layer.get(key)
        if not isinstance(v, (list, tuple)) or not all(isinstance(x, Real) for x in v):
            raise ValueError(f"{kind} layer {key!r} must be a list of numbers")
        return v

    def angle(key):
        v = layer.get(key)
        if not isinstance(v, Real):
            raise ValueError(f"{kind} layer {key!r} must be a number")

    if kind in ("track", "polygon"):
        if len(angles("lat")) != len(angles("lon")):
            raise ValueError(f"{kind} layer lat/lon lengths differ")
    elif kind in ("marker", "label"):
        angle("lat")
        angle("lon")
    else:  # windows
        cols, rows = layer.get("columns"), layer.get("rows")
        if not isinstance(cols, (list, tuple)) or not isinstance(rows, (list, tuple)):
            raise ValueError("windows layer needs 'columns' and 'rows' lists")
        if not all(isinstance(r, (list, tuple)) for r in rows):
            raise ValueError("windows layer rows must be lists")
    return layer


@dataclass
class Scene:
    title: str = ""
    layers: list[dict] = field(default_factory=list)

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
        return {"title": self.title, "layers": self.layers}

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
        s = cls(title=title)
        for layer in layers:
            if not isinstance(layer, dict):
                raise ValueError("each scene layer must be an object with a 'kind'")
            s.add(dict(layer))
        return s
