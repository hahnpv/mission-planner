from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner import Orbit
from mission_planner.groundtrack import GroundTrack

EPOCH = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def straight_track(n, lat0=0.0, lat1=10.0, lon=0.0):
    return GroundTrack(
        epoch=EPOCH,
        t=np.arange(n) * 10.0,
        lat=np.radians(np.linspace(lat0, lat1, n)),
        lon=np.full(n, np.radians(lon)),
        alt=np.full(n, 400e3),
    )


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
    for p in passes:
        assert p["direction"] in ("ascending", "descending")
        assert 0.0 <= p["heading_deg"] < 360.0
        assert p["aos_utc"] <= p["ca_utc"] <= p["los_utc"]
    assert {p["direction"] for p in passes} == {"ascending", "descending"}


def test_heading_never_rounds_to_360():
    # A due-north track: heading 359.97 must report as 0.0, not 360.0.
    gt = straight_track(3)
    gt.lon[1:] -= np.radians(1e-4)
    assert gt.passes(5.0, 0.0, within_km=100.0)[0]["heading_deg"] < 360.0


def test_passes_across_the_antimeridian():
    gt = straight_track(21, lat0=-10.0, lat1=10.0, lon=179.9)
    (p,) = gt.passes(0.0, -179.9, within_km=50.0)
    assert p["min_dist_km"] < 25.0 and p["direction"] == "ascending"


def test_within_km_is_inclusive_and_single_sample_tracks_have_no_passes():
    gt = straight_track(3, lat0=0.0, lat1=2.0)
    d_km = 1.0 * np.pi / 180 * 6378.137  # target one degree east of sample 1
    assert gt.passes(1.0, 1.0, within_km=d_km + 1e-3)[0]["min_dist_km"] == pytest.approx(
        d_km, abs=0.1
    )
    assert gt.passes(1.0, 1.0, within_km=d_km - 1.0) == []
    assert straight_track(1).passes(0.0, 0.0, within_km=1000.0) == []
    assert np.isnan(straight_track(1).heading).all()


def test_track_arrays_must_agree():
    with pytest.raises(ValueError, match="same length"):
        GroundTrack(EPOCH, np.zeros(3), np.zeros(3), np.zeros(2), np.zeros(3))


def test_time_must_not_run_backwards():
    z = np.zeros(3)
    with pytest.raises(ValueError, match="track mix runs backwards"):
        GroundTrack(EPOCH, np.array([0.0, 10.0, 5.0]), z, z, z, label="mix")
    # Round-off where a simulator's phases join is not a reversal.
    GroundTrack(EPOCH, np.array([0.0, 10.0, 10.0 - 4.5e-13]), z, z, z)


def test_a_naive_epoch_means_utc():
    gt = straight_track(2)
    gt.epoch = datetime(2026, 8, 21, 0, 0)
    naive = GroundTrack(datetime(2026, 8, 21, 0, 0), gt.t, gt.lat, gt.lon, gt.alt)
    assert naive.epoch == EPOCH and naive.epoch.tzinfo is timezone.utc
    assert naive.to_json()["epoch_utc"] == "2026-08-21T00:00:00+00:00"
    assert naive.passes(0.0, 0.0, within_km=10.0)[0]["ca_utc"] == "2026-08-21T00:00:00+00:00"


def test_to_json_shape():
    orb = Orbit.circular(500.0, 45.0, epoch=EPOCH)
    gt = orb.ground_track(3600.0, 60.0)
    d = gt.to_json()
    assert len(d["lat"]) == len(d["lon"]) == len(d["t"]) == len(d["alt_km"])
    assert max(map(abs, d["lat"])) <= 45.1
    assert max(map(abs, d["lon"])) <= 180.0
    assert not {"id", "label", "parent", "color"} & set(d)  # absent, not null


def test_heading_eastward_for_equatorial():
    orb = Orbit.circular(400.0, 0.0, epoch=EPOCH)
    gt = orb.ground_track(3600.0, 30.0)
    hdg = np.degrees(gt.heading) % 360.0
    assert np.all(np.abs(hdg - 90.0) < 1.0)  # due east


def test_to_json_precision_supports_flight_path_angle():
    """The UI differentiates this track to get gamma, so the arc precision
    has to resolve the horizontal step of a near-vertical descent."""
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
