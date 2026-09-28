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
contract can grow without breaking older servers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_KINDS = {"track", "marker", "polygon", "windows", "label"}


@dataclass
class Scene:
    title: str = ""
    layers: list[dict] = field(default_factory=list)

    def add(self, layer: dict) -> Scene:
        kind = layer.get("kind")
        if kind not in _KINDS:
            raise ValueError(f"unknown layer kind {kind!r} (one of {sorted(_KINDS)})")
        self.layers.append(layer)
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
    def from_json(cls, doc: dict) -> Scene:
        s = cls(title=str(doc.get("title", "")))
        for layer in doc.get("layers", []):
            s.add(dict(layer))
        return s
