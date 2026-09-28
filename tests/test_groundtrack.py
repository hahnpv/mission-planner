from datetime import datetime, timezone

import numpy as np

from mission_planner import Orbit, Scene

EPOCH = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def test_equatorial_orbit_passes_equatorial_target_every_rev():
    orb = Orbit.circular(400.0, 0.0, epoch=EPOCH)
    gt = orb.ground_track(86400.0, 30.0)
    passes = gt.passes(0.0, 0.0, within_km=300.0)
    # Track drifts west ~22.9 deg/rev; the target is hit once per day-ish
    # window when the track sweeps by: every rev crosses lon 0 once, and
    # the subpoint stays on the equator, so every rev scores a pass.
    assert len(passes) >= 14
    for p in passes:
        assert p["min_dist_km"] <= 300.0


def test_pass_fields_sane():
    orb = Orbit.circular(400.0, 51.6, epoch=EPOCH)
    gt = orb.ground_track(2 * 86400.0, 30.0)
    passes = gt.passes(28.5, -80.6, within_km=800.0)
    assert passes, "expect at least one pass over KSC in 2 days"
    p = passes[0]
    assert p["direction"] in ("ascending", "descending")
    assert 0.0 <= p["heading_deg"] < 360.0
    assert p["aos_utc"] <= p["ca_utc"] <= p["los_utc"]


def test_to_json_shape():
    orb = Orbit.circular(500.0, 45.0, epoch=EPOCH)
    gt = orb.ground_track(3600.0, 60.0)
    d = gt.to_json()
    assert len(d["lat"]) == len(d["lon"]) == len(d["t"])
    assert max(map(abs, d["lat"])) <= 45.1
    assert max(map(abs, d["lon"])) <= 180.0


def test_scene_roundtrip():
    s = Scene(title="phasing demo")
    s.track("vehicle", [0, 1], [10, 11], color="#2a78d6")
    s.marker("delivery", 12.3, 45.6, symbol="target")
    s.windows("options", ["utc", "dist_km"], [["2026-08-22T01:00Z", 120]])
    doc = s.to_json()
    s2 = Scene.from_json(doc)
    assert s2.title == "phasing demo"
    assert [layer["kind"] for layer in s2.layers] == ["track", "marker", "windows"]


def test_scene_rejects_unknown_kind():
    import pytest

    with pytest.raises(ValueError):
        Scene().add({"kind": "nope"})


def test_heading_eastward_for_equatorial():
    orb = Orbit.circular(400.0, 0.0, epoch=EPOCH)
    gt = orb.ground_track(3600.0, 30.0)
    hdg = np.degrees(gt.heading) % 360.0
    assert np.all(np.abs(hdg - 90.0) < 1.0)  # due east


def test_to_json_precision_supports_flight_path_angle():
    """The UI differentiates this track to get gamma, so the arc precision
    has to resolve the horizontal step of a near-vertical descent."""
    from datetime import datetime, timezone

    import numpy as np

    from mission_planner.groundtrack import GroundTrack

    gt = GroundTrack(
        epoch=datetime(2026, 8, 23, tzinfo=timezone.utc),
        t=np.array([0.0, 10.0]),
        lat=np.radians([-35.02400, -35.02431]),  # 34 m apart
        lon=np.radians([-157.41900, -157.41874]),
        alt=np.array([1040.0, 310.0]),
    )
    d = gt.to_json()
    assert d["lat"][0] != d["lat"][1]  # 3 decimals collapsed these
    assert d["lon"][0] != d["lon"][1]
    assert d["alt_km"] == [1.04, 0.31]  # metre altitude resolution
