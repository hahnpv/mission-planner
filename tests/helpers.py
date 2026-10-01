"""Test helpers shared by several test modules (not a test file itself).

- `core_registry(*specs)`: a Registry of the built-ins plus plugin spec dicts,
  as if those plugins were installed -- never the real entry points.
- The toy file formats: `TOY` reads `#toy-track` text files into one track,
  `TOY_PAIR` reads `#toy-pair` files into two (ids a / b, the second on an
  epoch a minute later).  Both are plugins with `file_readers`.
- `write_pack(path)`: a data pack with two sites and one overlay.
"""

import textwrap
from datetime import datetime, timezone

import numpy as np

from mission_planner.groundtrack import GroundTrack
from mission_planner.plugins import Registry, builtin_sources


def core_registry(*specs) -> Registry:
    return Registry([*builtin_sources(), *((s["name"], False, (lambda s=s: s)) for s in specs)])


# ---------------------------------------------------------------- toy file readers
MAGIC = "#toy-track"
PAIR_MAGIC = "#toy-pair"
E0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
CALLS = {"detect": 0}  # how often a toy detector ran (reset by test_filekinds' fixture)


def _detector(magic):
    def detect(path):
        CALLS["detect"] += 1
        with open(path, "rb") as f:
            return f.read(len(magic)) == magic.encode()

    return detect


def rows(path):
    return np.loadtxt(path, comments="#", ndmin=2)


def inspect(path):
    return {
        "summary": f"{len(rows(path))} samples",
        "warning": None,
        "epoch_utc": "2026-01-01T00:00:00+00:00",
        "epoch_note": "the toy default",
        "options": [{"key": "scale", "label": "scale", "choices": ["1", "2"], "default": "1"}],
    }


def read(path, args):
    t, lat, lon, alt = rows(path).T
    k = float(args.get("scale", 1))
    gt = GroundTrack(E0, t, np.radians(lat), np.radians(lon), alt * k, extra={"note": "toy"})
    return gt, {"title": "toy run"}


def read_pair(path, args):
    t, lat, lon, alt = rows(path).T
    a = GroundTrack(E0, t, np.radians(lat), np.radians(lon), alt, id="a", label="Alpha")
    # Same samples, an epoch one minute later: shifted onto the first track's clock.
    b = GroundTrack(
        E0.replace(minute=1), t, np.radians(lat), np.radians(lon), alt, id="b", label="Bravo"
    )
    return [a, b], {"title": "pair", "primary": "b"}


READER = {
    "label": "Toy track",
    "extensions": [".txt"],
    "detect": _detector(MAGIC),
    "inspect": inspect,
}
TOY = {"api": 1, "name": "toy", "file_readers": {"toy": {**READER, "read": read}}}
PAIR_READER = {**READER, "label": "Toy pair", "detect": _detector(PAIR_MAGIC)}
TOY_PAIR = {
    "api": 1,
    "name": "toypair",
    "file_readers": {"toypair": {**PAIR_READER, "read": read_pair}},
}
# Two samples a minute apart, 1000 m -> 900 m, heading north-east.
BODY = (MAGIC + "\n0 10 20 1000\n60 11 21 900\n").encode()
PAIR_BODY = (PAIR_MAGIC + "\n0 10 20 1000\n60 11 21 900\n").encode()


# ---------------------------------------------------------------- data packs
def write_pack(path):
    (path / "overlays").mkdir(parents=True)
    (path / "sites.yaml").write_text(
        "- {name: Test Range, lat: 22.0, lon: -159.8}\n- {name: Kodiak, lat: 57.5, lon: -152.0}\n"
    )
    (path / "overlays" / "box.geojson").write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},'
        ' "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}}]}'
    )
    (path / "overlays" / "box.yaml").write_text(
        textwrap.dedent("""\
            title: A box
            style: {color: "#123456", opacity: 0.2}
            source: {dataset: unit test}
        """)
    )
    return path
