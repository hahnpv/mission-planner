"""The groundstation plugin: its math, its route, its MCP tool, and that the
core loads it -- without installing it: the spec goes straight into a
Registry, which is how any plugin can be tested (docs/plugins.md, section 4)."""

import io
import math
from datetime import datetime, timezone

import numpy as np
import pytest
from mp_groundstation import MODULE, ground_contacts
from mp_groundstation.contacts import contacts, coverage, look_angles, mask_ring_deg

import mission_planner.plugins as plugins
import mission_planner.server as server
from mission_planner import SITES, Orbit
from mission_planner.constants import RE
from mission_planner.groundtrack import GroundTrack
from mission_planner.plugins import Registry, builtin_sources

EPOCH = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
KSC = SITES["Cape Canaveral / KSC"]


def _iss(dt=30.0, hours=24.0):
    orb = Orbit.from_launch_site(KSC, alt_km=400, inc_deg=51.6, epoch=EPOCH)
    return orb.ground_track(hours * 3600, dt)


# ---------------------------------------------------------------- geometry
def test_overhead_is_ninety_and_the_footprint_edge_is_zero():
    # On the equator a longitude step is the central angle itself.
    alt = 500e3
    edge = math.acos(RE / (RE + alt))  # central angle of the horizon footprint
    gt = GroundTrack(
        EPOCH,
        np.array([0.0, 1.0]),
        np.zeros(2),
        np.array([0.0, edge]) + math.radians(20.0),
        np.full(2, alt),
    )
    el, _ = look_angles(gt, 0.0, 20.0)
    assert el[0] == pytest.approx(90.0, abs=1e-3) and abs(el[1]) < 1e-9


def test_mask_ring_shrinks_with_the_mask():
    horizon = math.degrees(math.acos(RE / (RE + 400e3)))
    assert mask_ring_deg(400, 0) == pytest.approx(horizon)
    assert mask_ring_deg(400, 10) < horizon and mask_ring_deg(400, 89.999) < 1e-3


# ---------------------------------------------------------------- contacts
def test_the_launch_site_sees_the_vehicle_at_once():
    first = contacts(_iss(), KSC.lat_deg, KSC.lon_deg, 10.0)[0]
    assert first["partial"] and first["aos_t_s"] == 0.0 and first["max_el_deg"] > 89


def test_windows_are_consistent():
    ws = contacts(_iss(), 40.0, -105.0, 10.0)
    assert ws, "a 51.6 deg orbit passes over 40 N within a day"
    for w in ws:
        assert w["aos_t_s"] < w["max_el_t_s"] + 30 and w["max_el_t_s"] < w["los_t_s"] + 30
        assert w["duration_s"] == pytest.approx(w["los_t_s"] - w["aos_t_s"], abs=0.2)
        assert w["max_el_deg"] >= 10.0 and w["duration_s"] < 15 * 60
    assert [w["aos_t_s"] for w in ws] == sorted(w["aos_t_s"] for w in ws)


def test_a_higher_mask_means_less_contact():
    gt = _iss()
    low, high = contacts(gt, 40.0, -105.0, 5.0), contacts(gt, 40.0, -105.0, 30.0)
    assert sum(w["duration_s"] for w in high) < sum(w["duration_s"] for w in low)
    assert all(w["max_el_deg"] >= 30.0 for w in high)


def test_interpolated_aos_matches_fine_sampling():
    coarse = contacts(_iss(30.0, 12.0), 40.0, -105.0, 10.0)
    fine = contacts(_iss(1.0, 12.0), 40.0, -105.0, 10.0)
    assert len(coarse) == len(fine)
    for c, f in zip(coarse, fine):
        assert c["aos_t_s"] == pytest.approx(f["aos_t_s"], abs=3.0)
        assert c["los_t_s"] == pytest.approx(f["los_t_s"], abs=3.0)


def test_bad_mask_and_short_tracks():
    with pytest.raises(ValueError, match="min_el_deg"):
        contacts(_iss(), 0, 0, 95)
    one = GroundTrack(EPOCH, np.zeros(1), np.zeros(1), np.zeros(1), np.full(1, 400e3))
    assert contacts(one, 0, 0, 10) == []


def test_coverage_merges_overlaps_and_finds_the_longest_gap():
    ws = [
        {"aos_t_s": 100, "los_t_s": 200},
        {"aos_t_s": 150, "los_t_s": 300},
        {"aos_t_s": 900, "los_t_s": 1000},
    ]
    c = coverage(ws, 1200)
    assert c["n"] == 3 and c["total_s"] == 300 and c["fraction"] == 0.25
    assert c["longest_gap_s"] == 600 and c["mean_s"] == 116.7  # mean of the three windows
    assert coverage([], 1200) == {
        "n": 0,
        "total_s": 0.0,
        "mean_s": 0.0,
        "fraction": 0.0,
        "longest_gap_s": 1200.0,
    }
    assert coverage(ws, 0)["n"] == 0  # an empty span has nothing to cover


# ---------------------------------------------------------------- the plugin in the app
E0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _read_pair(path, args):
    """A file of 't lat lon alt' lines, as two vehicles: the second one a
    minute behind the first."""
    t, lat, lon, alt = np.loadtxt(path, ndmin=2).T
    a = GroundTrack(E0, t, np.radians(lat), np.radians(lon), alt, id="a", label="Alpha")
    b = GroundTrack(E0.replace(minute=1), t, np.radians(lat), np.radians(lon), alt, id="b")
    return [a, b], {"title": "pair"}


PAIR = {
    "api": 1,
    "name": "pair",
    "file_readers": {
        "pair": {
            "label": "pair",
            "detect": lambda p: True,
            "inspect": lambda p: {"summary": "two vehicles"},
            "read": _read_pair,
        }
    },
}


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("MP_UPLOAD_DIR", str(tmp_path / "uploads"))
    reg = Registry(
        [
            *builtin_sources(),
            ("groundstation", False, lambda: MODULE),
            ("pair", False, lambda: PAIR),
        ]
    )
    monkeypatch.setattr(plugins, "_REGISTRY", reg)
    return server.create_app().test_client(), reg


PLAN = "source=site&hp=400&inc=51.6&hours=12&dt=30&epoch=2026-10-01T12:00:00Z"


def test_loads_and_serves(app):
    c, reg = app
    assert reg.records["groundstation"].status == "loaded"
    r = c.get(f"/api/groundstation/contacts?{PLAN}&gs_lat=40&gs_lon=-105&min_el=10").get_json()
    assert r["n"] == len(r["contacts"]) > 0 and r["station"]["min_el_deg"] == 10
    assert r["contacts"][0]["track"] == "track1" and 0 < r["coverage"]["fraction"] < 0.1
    assert "label" not in r["contacts"][0]
    assert c.get("/plugins/groundstation/groundstation.js").status_code == 200


def test_contacts_of_a_multi_track_plan_are_tagged_and_on_one_clock(app):
    c, _ = app
    # Straight overhead of a station at (10, 20): the first sample is in view.
    body = b"0 10 20 400000\n60 10.5 20.5 400000\n120 20 30 400000\n"
    up = c.post("/api/uploads", data={"file": (io.BytesIO(body), "pair.txt")}).get_json()
    q = f"source=file&upload={up['id']}&gs_lat=10&gs_lon=20&min_el=10"
    r = c.get(f"/api/groundstation/contacts?{q}").get_json()
    assert [(w["track"], w.get("label")) for w in r["contacts"]] == [("a", "Alpha"), ("b", None)]
    a, b = r["contacts"]
    assert a["aos_t_s"] == 0.0 and b["aos_t_s"] == 60.0  # b's epoch is a minute later
    assert b["los_t_s"] - b["aos_t_s"] == pytest.approx(a["los_t_s"] - a["aos_t_s"], abs=0.2)
    assert b["aos_utc"] > a["aos_utc"] and all(w["partial"] for w in (a, b))
    cov = r["coverage"]
    assert cov["n"] == 2 and cov["total_s"] < a["duration_s"] + b["duration_s"]  # they overlap
    assert cov["mean_s"] == pytest.approx(a["duration_s"], abs=0.2)
    assert cov["longest_gap_s"] == pytest.approx(180.0 - b["los_t_s"], abs=0.2)  # span is 180 s


def test_route_needs_a_station(app):
    c, _ = app
    r = c.get(f"/api/groundstation/contacts?{PLAN}")
    assert r.status_code == 400 and "gs_lat" in r.get_json()["error"]


def test_switching_off_gates_the_route(app):
    c, reg = app
    reg.set_enabled("groundstation", False)
    assert c.get(f"/api/groundstation/contacts?{PLAN}&gs_lat=40&gs_lon=-105").status_code == 404


def test_mcp_tool():
    r = ground_contacts(40.0, -105.0, min_el_deg=10, epoch_utc="2026-10-01T12:00:00Z", hours=12)
    assert r["n"] > 0 and r["coverage"]["n"] == r["n"]
    w = r["contacts"][0]
    assert {"aos_utc", "los_utc", "max_el_deg", "aos_az_deg", "los_az_deg"} <= set(w)
