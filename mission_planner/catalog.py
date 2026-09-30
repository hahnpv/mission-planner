"""Launch sites, orbit presets and map overlays as data.

The core ships `data/catalog/` (well-known launch sites, textbook orbit
presets, no overlays); data packs add their own through a plugin's `catalog`
key (see plugins.py), so deployment-specific data never lives in the core.

A catalog directory holds any of::

    sites.yaml      - {name, lat, lon}  (degrees)
    presets.yaml    - {name, perigee_km, apogee_km?, inc_deg, argp_deg?,
                       node_lon_deg?, sun_synchronous?}
                      element-anchored orbits: no launch site, RAAN from
                      node (or GEO station) longitude; or a *file preset*
                      {name, file_from: <POST route>} — the route (a data
                      pack's plugin provides it) stores a file and answers
                      with its upload info; the UI opens it in the File
                      source and plans it (e.g. a constellation's elements)
    overlays/<id>.geojson + overlays/<id>.yaml
                    - shaded map regions; the YAML sidecar carries
                      {title, style: {color, opacity}, source: {...}}

Every item comes back tagged with the pack it came from.  A later pack's
item replaces an earlier one of the same name.

`current()` is cached: the files are re-read only when the set of active
packs or a file's modification time changes, so a plan request costs a few
stats, not a re-parse of every overlay.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import yaml

_lock = threading.Lock()
_cache: tuple[tuple, dict] | None = None  # (key, merged catalog)


def _files(path: Path) -> list[Path]:
    out = [path / "sites.yaml", path / "presets.yaml"]
    out += sorted((path / "overlays").glob("*.geojson"))
    out += sorted((path / "overlays").glob("*.yaml"))
    return out


def _load_dir(pack: str, path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"sites": [], "presets": [], "overlays": []}
    for kind in ("sites", "presets"):
        fn = path / f"{kind}.yaml"
        if fn.exists():
            items = yaml.safe_load(fn.read_text()) or []
            out[kind] = [{**item, "pack": pack} for item in items]
    for gj in sorted((path / "overlays").glob("*.geojson")):
        meta_fn = gj.with_suffix(".yaml")
        meta = yaml.safe_load(meta_fn.read_text()) if meta_fn.exists() else {}
        out["overlays"].append(
            {
                "id": gj.stem,
                "name": meta.get("title", gj.stem),
                "style": meta.get("style", {}),
                "source": meta.get("source", {}),
                "geojson": json.loads(gj.read_text()),
                "pack": pack,
            }
        )
    return out


def merged(dirs: list[tuple[str, Path]]) -> dict[str, list[dict]]:
    """Uncached merge of catalog directories in order (later packs win)."""
    by_kind: dict[str, dict[str, dict]] = {"sites": {}, "presets": {}, "overlays": {}}
    for pack, path in dirs:
        for kind, items in _load_dir(pack, Path(path)).items():
            for item in items:
                by_kind[kind][item.get("name")] = item
    return {kind: list(items.values()) for kind, items in by_kind.items()}


def _key(dirs: list[tuple[str, Path]]) -> tuple:
    key = []
    for pack, path in dirs:
        path = Path(path)
        stamps = tuple((str(f), f.stat().st_mtime_ns) for f in _files(path) if f.exists())
        key.append((pack, str(path), stamps))
    return tuple(key)


def current() -> dict[str, list[dict]]:
    """The core catalog plus every active data pack (cached, see module doc)."""
    global _cache
    from .plugins import registry

    dirs = registry().catalog_dirs()
    key = _key(dirs)
    with _lock:
        if _cache is not None and _cache[0] == key:
            return _cache[1]
    cat = merged(dirs)
    with _lock:
        _cache = (key, cat)
    return cat
