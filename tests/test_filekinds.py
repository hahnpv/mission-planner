"""File readers (spec key `file_readers`), detection (filekinds.py) and the
built-in "File" source (modules/files.py), over a toy text format."""

import io
from datetime import datetime, timezone

import numpy as np
import pytest

import mission_planner.plugins as plugins
import mission_planner.server as server
from mission_planner import filekinds, uploads
from mission_planner.groundtrack import GroundTrack
from mission_planner.plugins import Registry, builtin_sources

MAGIC = "#toy-track"
CALLS = {"detect": 0}


def _detect(path):
    CALLS["detect"] += 1
    with open(path, "rb") as f:
        return f.read(len(MAGIC)) == MAGIC.encode()


def _rows(path):
    return np.loadtxt(path, comments="#", ndmin=2)


def _inspect(path):
    return {
        "summary": f"{len(_rows(path))} samples",
        "warning": None,
        "epoch_utc": "2026-01-01T00:00:00+00:00",
        "epoch_note": "the toy default",
        "options": [{"key": "scale", "label": "scale", "choices": ["1", "2"], "default": "1"}],
    }


def _read(path, args):
    t, lat, lon, alt = _rows(path).T
    k = float(args.get("scale", 1))
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    gt = GroundTrack(epoch, t, np.radians(lat), np.radians(lon), alt * k, extra={"note": "toy"})
    return gt, {"title": "toy run"}


READER = {"label": "Toy track", "extensions": [".txt"], "detect": _detect, "inspect": _inspect}
TOY = {"api": 1, "name": "toy", "file_readers": {"toy": {**READER, "read": _read}}}
BODY = (MAGIC + "\n0 10 20 1000\n60 11 21 900\n").encode()


def _registry(monkeypatch, *specs):
    extra = [(s["name"], False, lambda s=s: s) for s in specs]
    reg = Registry([*builtin_sources(), *extra])
    monkeypatch.setattr(plugins, "_REGISTRY", reg)
    return reg


def _client(monkeypatch, *specs):
    reg = _registry(monkeypatch, *specs)
    return reg, server.create_app().test_client()


def _upload(client, body=BODY, name="run.txt"):
    return client.post("/api/uploads", data={"file": (io.BytesIO(body), name)}).get_json()


# ---------------------------------------------------------------- spec
@pytest.mark.parametrize(
    "readers, why",
    [
        ([], "must be a dict"),
        ({"x": {"detect": 1, "inspect": _inspect, "read": _read}}, "callable 'detect'"),
        ({"x": {"detect": _detect, "inspect": _inspect}}, "callable 'read'"),
        ({"x": {**READER, "read": _read, "extensions": ["h5"]}}, "extensions"),
    ],
)
def test_bad_reader_specs_fail_the_plugin(monkeypatch, readers, why):
    reg = _registry(monkeypatch, {"api": 1, "name": "bad", "file_readers": readers})
    assert reg.records["bad"].status == "failed" and why in reg.records["bad"].error


def test_reader_ids_are_unique(monkeypatch):
    twin = {"api": 1, "name": "twin", "file_readers": {"toy": {**READER, "read": _read}}}
    reg = _registry(monkeypatch, TOY, twin)
    assert reg.records["toy"].status == "loaded"
    assert "file reader 'toy' is already provided by plugin 'toy'" in reg.records["twin"].error


# ---------------------------------------------------------------- detection
def test_detect_once_and_label(monkeypatch):
    _, c = _client(monkeypatch, TOY)
    CALLS["detect"] = 0
    up = _upload(c)
    assert (up["kind"], up["kind_label"], up["kind_note"]) == ("toy", "Toy track", None)
    listed = c.get("/api/uploads").get_json()
    assert [(x["name"], x["kind"]) for x in listed] == [("run.txt", "toy")]
    assert CALLS["detect"] == 1  # cached in the sidecar
    other = _upload(c, b"just text\n", "notes.txt")
    assert other["kind"] is None and "no active plugin" in other["kind_note"]


def test_switching_a_plugin_redetects(monkeypatch):
    reg, c = _client(monkeypatch, TOY)
    uid = _upload(c)["id"]
    reg.set_enabled("toy", False)
    d = filekinds.detect(uid)
    assert d["kind"] is None
    err = c.get(f"/api/plan?source=file&upload={uid}").get_json()["error"]
    assert "no active plugin reads" in err
    reg.set_enabled("toy", True)
    assert filekinds.detect(uid)["kind"] == "toy"


def test_two_claims_are_reported_not_guessed(monkeypatch):
    greedy = {
        "api": 1,
        "name": "greedy",
        "file_readers": {"any": {**READER, "detect": lambda p: True, "read": _read}},
    }
    _, c = _client(monkeypatch, TOY, greedy)
    up = _upload(c)
    assert up["kind"] is None and "toy, any" in up["kind_note"]


def test_a_detector_that_raises_is_a_no(monkeypatch):
    def boom(path):
        raise RuntimeError("bad detector")

    shaky = {
        "api": 1,
        "name": "shaky",
        "file_readers": {"shaky": {**READER, "detect": boom, "read": _read}},
    }
    _, c = _client(monkeypatch, TOY, shaky)
    assert _upload(c)["kind"] == "toy"


# ---------------------------------------------------------------- the File source
def test_file_source_end_to_end(monkeypatch):
    reg, c = _client(monkeypatch, TOY)
    mods = {m["name"]: m for m in c.get("/api/modules").get_json()}
    assert mods["files"]["builtin"] and mods["files"]["sources"][0]["id"] == "file"
    uid = _upload(c)["id"]
    info = c.get(f"/api/files/{uid}/inspect").get_json()
    assert (info["kind"], info["kind_label"], info["name"]) == ("toy", "Toy track", "run.txt")
    assert info["summary"] == "2 samples" and info["options"][0]["key"] == "scale"
    res = c.get(f"/api/plan?source=file&upload={uid}&scale=2").get_json()
    s = res["summary"]
    assert (s["kind"], s["source"], s["reader"], s["file"]) == (
        "trajectory",
        "file",
        "toy",
        "run.txt",
    )
    assert s["title"] == "toy run" and res["track"]["alt_km"] == [2.0, 1.8]
    assert "choose a file" in c.get("/api/plan?source=file").get_json()["error"]


def test_a_reader_crash_is_a_500_naming_it(monkeypatch):
    def broken(path, args):
        raise KeyError("column")

    bad = {"api": 1, "name": "toy", "file_readers": {"toy": {**READER, "read": broken}}}
    _, c = _client(monkeypatch, bad)
    uid = _upload(c)["id"]
    r = c.get(f"/api/plan?source=file&upload={uid}")
    assert (
        r.status_code == 500 and "file reader 'toy' (plugin 'toy') failed" in r.get_json()["error"]
    )


def test_load_file_mcp_tool(monkeypatch, tmp_path):
    from mission_planner.modules.files import load_file

    _registry(monkeypatch, TOY)
    f = tmp_path / "run.txt"
    f.write_bytes(BODY)
    out = load_file(str(f), options={"scale": 2})
    assert out["reader"] == "toy" and out["note"] == "toy" and out["title"] == "toy run"
    assert uploads.info(out["upload"])["name"] == "run.txt"
    assert "decay_profile" not in out


# ---------------------------------------------------------------- several tracks
def _read_two(path, args):
    t, lat, lon, alt = _rows(path).T
    e0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = GroundTrack(e0, t, np.radians(lat), np.radians(lon), alt, id="a", label="Alpha")
    # Same samples, an epoch one minute later: shifted onto the first track's clock.
    b = GroundTrack(
        e0.replace(minute=1), t, np.radians(lat), np.radians(lon), alt, id="b", label="Bravo"
    )
    return [a, b], {"title": "pair", "primary": "b"}


def test_a_reader_can_return_several_tracks(monkeypatch, tmp_path):
    pair = {"api": 1, "name": "toy", "file_readers": {"toy": {**READER, "read": _read_two}}}
    _, c = _client(monkeypatch, pair)
    uid = _upload(c)["id"]
    res = c.get(f"/api/plan?source=file&upload={uid}").get_json()
    assert res["primary"] == "b" and res["track"]["id"] == "b"
    assert [(t["id"], t["label"]) for t in res["tracks"]] == [("a", "Alpha"), ("b", "Bravo")]
    assert res["tracks"][1]["t"] == [60.0, 120.0]  # onto track a's epoch
    assert res["summary"]["n_tracks"] == 2 and "primary" not in res["summary"]

    from mission_planner.modules.files import load_file

    f = tmp_path / "pair.txt"
    f.write_bytes(BODY)
    out = load_file(str(f))
    assert [t["id"] for t in out["tracks"]] == ["a", "b"]
    assert out["tracks"][0]["span_s"] == [0.0, 60.0]


def test_track_sets_are_checked():
    from mission_planner.planning import MAX_TRACK_POINTS, track_set_payload

    e0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def tr(tid, n=3):
        z = np.zeros(n)
        return GroundTrack(e0, np.arange(float(n)), z, z, z, id=tid)

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


def test_time_must_not_run_backwards():
    e0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    z = np.zeros(3)
    with pytest.raises(ValueError, match="runs backwards"):
        GroundTrack(e0, np.array([0.0, 10.0, 5.0]), z, z, z, label="mix")
    # Round-off where a simulator's phases join is not a reversal.
    GroundTrack(e0, np.array([0.0, 10.0, 10.0 - 4.5e-13]), z, z, z)


def test_track_color_rides_along():
    from mission_planner.planning import track_set_payload

    e0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    z = np.zeros(2)
    main = GroundTrack(e0, np.array([0.0, 1.0]), z, z, z, id="main")
    booster = GroundTrack(
        e0,
        np.array([0.5, 1.0]),
        z,
        z,
        z,
        id="b",
        parent={"id": "main", "t_s": 0.5},
        color="#d03b3b",
    )
    out = track_set_payload({}, [main, booster])["tracks"]
    assert "color" not in out[0] and out[1]["color"] == "#d03b3b"
