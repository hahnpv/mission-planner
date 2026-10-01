"""planning.py: reading request args, and the /api/plan payload for one or
several tracks."""

from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner import Orbit
from mission_planner.groundtrack import GroundTrack
from mission_planner.planning import (
    MAX_TRACK_POINTS,
    args_from_params,
    default_dt,
    opt_float,
    plan_payload,
    track_set_payload,
)

E0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def tr(tid, n=3):
    z = np.zeros(n)
    return GroundTrack(E0, np.arange(float(n)), z, z, z, id=tid)


# ---------------------------------------------------------------- args
@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "x", "1e400"])
def test_opt_float_wants_a_finite_number(bad):
    with pytest.raises(ValueError, match="hp must be a (finite )?number"):
        opt_float({"hp": bad}, "hp")


def test_opt_float_blank_means_default():
    assert opt_float({"hp": ""}, "hp", 5.0) == 5.0 and opt_float({}, "hp") is None
    assert opt_float({"hp": "3"}, "hp") == 3.0


def test_default_dt_coarsens_long_horizons():
    assert default_dt(1.0) == 30.0 and default_dt(1.0, 60.0) == 60.0
    assert default_dt(720.0) == 130.0  # 20k points over 30 days, rounded to 10 s


def test_args_from_params_fills_in_a_custom_site_longitude():
    a = args_from_params(site="pad", lat=10.0)
    assert (a["source"], a["site"], a["lat"], a["lon"]) == ("site", "pad", 10.0, 0.0)
    assert args_from_params(site="")["source"] == "preset"


# ---------------------------------------------------------------- payloads
def test_plan_payload_carries_the_request_args_only_when_given():
    orb = Orbit.circular(400.0, 51.6, epoch=E0)
    gt = orb.ground_track(600.0, 60.0)
    assert "args" not in plan_payload(orb, {}, gt)
    out = plan_payload(orb, {}, gt, {"hp": 400, "ha": None, "dt": "", "source": "site"})
    assert out["args"] == {"hp": "400", "source": "site"}  # strings; blanks dropped


def test_track_sets_are_checked():
    with pytest.raises(ValueError, match="share the id"):
        track_set_payload({}, [tr("x"), tr("x")])
    with pytest.raises(ValueError, match="primary"):
        track_set_payload({"primary": "nope"}, [tr("x")])
    with pytest.raises(ValueError, match="limit"):
        track_set_payload({}, [tr("x", MAX_TRACK_POINTS), tr("y")])
    with pytest.raises(ValueError, match="no tracks"):
        track_set_payload({}, [])
    # Unnamed tracks get ids.
    assert [t["id"] for t in track_set_payload({}, [tr(None), tr(None)])["tracks"]] == [
        "track1",
        "track2",
    ]


def test_track_set_shares_the_first_epoch_and_keeps_colours():
    z = np.zeros(2)
    main = GroundTrack(E0, np.array([0.0, 1.0]), z, z, z, id="main")
    booster = GroundTrack(
        E0.replace(minute=1),
        np.array([0.5, 1.0]),
        z,
        z,
        z,
        id="b",
        parent={"id": "main", "t_s": 0.5},
        color="#d03b3b",
    )
    out = track_set_payload({"title": "x", "primary": "b"}, [main, booster])
    a, b = out["tracks"]
    assert "color" not in a and b["color"] == "#d03b3b" and b["parent"]["id"] == "main"
    assert b["t"] == [60.5, 61.0] and b["epoch_utc"] == E0.isoformat()  # onto main's clock
    assert out["primary"] == "b" and out["track"] is b
    assert out["summary"] == {"title": "x", "n_tracks": 2}  # primary is not a summary field
