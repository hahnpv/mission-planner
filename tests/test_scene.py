"""Scene: the display document the UI draws (its route is in test_server.py)."""

import pytest

from mission_planner import Scene


def test_scene_roundtrip_with_every_layer_kind():
    s = Scene(title="phasing demo")
    s.track("vehicle", [0, 1], [10, 11], color="#2a78d6")
    s.marker("delivery", 12.3, 45.6, symbol="target")
    s.polygon("zone", [0, 1, 1], [0, 0, 1], fill="#123456")
    s.windows("options", ["utc", "dist_km"], [["2026-08-22T01:00Z", 120]])
    s.label("note", -5, 20, color="#000")
    doc = s.to_json()
    s2 = Scene.from_json(doc)
    assert s2.title == "phasing demo" and s2.plan is None and "plan" not in doc
    assert [layer["kind"] for layer in s2.layers] == [
        "track",
        "marker",
        "polygon",
        "windows",
        "label",
    ]
    assert s2.layers[2]["fill"] == "#123456" and s2.layers[4]["text"] == "note"


@pytest.mark.parametrize(
    "layer, why",
    [
        ({"kind": "nope"}, "unknown layer kind"),
        ({"kind": "track", "name": "t", "lat": "x", "lon": [0]}, "list of numbers"),
        ({"kind": "polygon", "name": "p", "lat": [0, True], "lon": [0, 1]}, "list of numbers"),
        ({"kind": "marker", "name": "m", "lat": True, "lon": 0}, "must be a number"),
        ({"kind": "label", "lat": 0, "lon": 0}, "'text' string"),
        ({"kind": "label", "text": 5, "lat": 0, "lon": 0}, "'text' string"),
        ({"kind": "windows", "name": "w", "columns": [], "rows": [1]}, "rows must be lists"),
    ],
)
def test_scene_rejects_malformed_layers(layer, why):
    with pytest.raises(ValueError, match=why):
        Scene().add(layer)
