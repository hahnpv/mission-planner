"""File readers (spec key `file_readers`), detection (filekinds.py) and the
built-in "File" source (modules/files.py), over the toy text format of
helpers.py."""

import io

import helpers
import pytest
from helpers import BODY, PAIR_BODY, READER, TOY, TOY_PAIR, core_registry, read

from mission_planner import filekinds, uploads


@pytest.fixture
def detect_calls(monkeypatch):
    """How often a toy detector ran during the test."""
    calls = {"detect": 0}
    monkeypatch.setattr(helpers, "CALLS", calls)
    return calls


@pytest.fixture
def registry_with(monkeypatch):
    def make(*specs):
        reg = core_registry(*specs)
        monkeypatch.setattr("mission_planner.plugins._REGISTRY", reg)
        return reg

    return make


def _upload(client, body=BODY, name="run.txt"):
    return client.post("/api/uploads", data={"file": (io.BytesIO(body), name)}).get_json()


# ---------------------------------------------------------------- spec
@pytest.mark.parametrize(
    "readers, why",
    [
        ([], "must be a dict"),
        ({"": {**READER, "read": read}}, "non-empty string"),
        ({"x": 1}, "file reader 'x' must be a dict"),
        ({"x": {"detect": 1, "inspect": READER["inspect"], "read": read}}, "callable 'detect'"),
        ({"x": {**READER}}, "callable 'read'"),
        ({"x": {**READER, "read": read, "label": 3}}, "label must be a string"),
        ({"x": {**READER, "read": read, "extensions": ["h5"]}}, "extensions"),
    ],
)
def test_bad_reader_specs_fail_the_plugin(registry_with, readers, why):
    reg = registry_with({"api": 1, "name": "bad", "file_readers": readers})
    assert reg.records["bad"].status == "failed" and why in reg.records["bad"].error


def test_reader_ids_are_unique(registry_with):
    twin = {"api": 1, "name": "twin", "file_readers": {"toy": {**READER, "read": read}}}
    reg = registry_with(TOY, twin)
    assert reg.records["toy"].status == "loaded"
    assert "file reader 'toy' is already provided by plugin 'toy'" in reg.records["twin"].error


# ---------------------------------------------------------------- detection
def test_detect_once_and_label(app_with, detect_calls):
    c, _ = app_with(TOY)
    up = _upload(c)
    assert (up["kind"], up["kind_label"], up["kind_note"]) == ("toy", "Toy track", None)
    listed = c.get("/api/uploads").get_json()
    assert [(x["name"], x["kind"]) for x in listed] == [("run.txt", "toy")]
    assert c.get(f"/api/uploads/{up['id']}").get_json()["kind"] == "toy"
    assert detect_calls["detect"] == 1  # cached in the sidecar
    other = _upload(c, b"just text\n", "notes.txt")
    assert other["kind"] is None and "no active plugin" in other["kind_note"]


def test_switching_a_plugin_redetects(app_with):
    c, reg = app_with(TOY)
    uid = _upload(c)["id"]
    reg.set_enabled("toy", False)
    d = filekinds.detect(uid)
    assert d["kind"] is None
    err = c.get(f"/api/plan?source=file&upload={uid}").get_json()["error"]
    assert "no active plugin reads" in err
    reg.set_enabled("toy", True)
    assert filekinds.detect(uid)["kind"] == "toy"


def test_two_claims_are_reported_not_guessed(app_with):
    greedy = {
        "api": 1,
        "name": "greedy",
        "file_readers": {"any": {**READER, "detect": lambda p: True, "read": read}},
    }
    c, _ = app_with(TOY, greedy)
    up = _upload(c)
    assert up["kind"] is None and "toy, any" in up["kind_note"]


def test_a_detector_that_raises_is_a_no(app_with):
    def boom(path):
        raise RuntimeError("bad detector")

    shaky = {
        "api": 1,
        "name": "shaky",
        "file_readers": {"shaky": {**READER, "detect": boom, "read": read}},
    }
    c, _ = app_with(TOY, shaky)
    assert _upload(c)["kind"] == "toy"


# ---------------------------------------------------------------- the File source
def test_file_source_end_to_end(app_with):
    c, _ = app_with(TOY)
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
    assert res["args"] == {"source": "file", "upload": uid, "scale": "2"}
    assert "choose a file" in c.get("/api/plan?source=file").get_json()["error"]


def test_inspecting_an_unknown_upload_is_a_404(app_with):
    c, _ = app_with(TOY)
    r = c.get(f"/api/files/{'0' * 24}/inspect")
    assert r.status_code == 404 and "no upload" in r.get_json()["error"]
    assert c.get("/api/files/..%2Fx/inspect").status_code == 404  # the router's own 404


def test_a_reader_crash_is_a_500_naming_it(app_with):
    def broken(path, args):
        raise KeyError("column")

    bad = {"api": 1, "name": "toy", "file_readers": {"toy": {**READER, "read": broken}}}
    c, _ = app_with(bad)
    uid = _upload(c)["id"]
    r = c.get(f"/api/plan?source=file&upload={uid}")
    assert r.status_code == 500
    assert r.get_json()["error"] == (
        "PluginError: file reader 'toy' (plugin 'toy') failed: KeyError: 'column'"
    )


def test_a_reader_s_value_error_is_the_user_s_400(app_with):
    def picky(path, args):
        raise ValueError("pick a vehicle first")

    c, _ = app_with({"api": 1, "name": "toy", "file_readers": {"toy": {**READER, "read": picky}}})
    uid = _upload(c)["id"]
    r = c.get(f"/api/plan?source=file&upload={uid}")
    assert r.status_code == 400 and r.get_json()["error"] == "pick a vehicle first"


def test_load_file_mcp_tool(registry_with, tmp_path):
    from mission_planner.modules.files import load_file

    registry_with(TOY)
    f = tmp_path / "run.txt"
    f.write_bytes(BODY)
    out = load_file(str(f), options={"scale": 2})
    assert out["reader"] == "toy" and out["note"] == "toy" and out["title"] == "toy run"
    assert out["span_s"] == [0.0, 60.0] and out["alt_km_range"] == [1.8, 2.0]
    assert uploads.info(out["upload"])["name"] == "run.txt"
    assert "decay_profile" not in out


def test_load_file_passes_the_epoch_and_options_to_the_reader(registry_with, tmp_path):
    from mission_planner.modules.files import load_file

    seen = []

    def spy(path, args):
        seen.append(dict(args))
        return read(path, args)

    registry_with({"api": 1, "name": "toy", "file_readers": {"toy": {**READER, "read": spy}}})
    f = tmp_path / "run.txt"
    f.write_bytes(BODY)
    load_file(str(f), epoch_utc="2026-03-01T00:00:00Z", options={"vehicle": "booster"})
    load_file(str(f))
    assert seen == [{"epoch": "2026-03-01T00:00:00Z", "vehicle": "booster"}, {}]


# ---------------------------------------------------------------- several tracks
def test_a_reader_can_return_several_tracks(app_with, tmp_path):
    c, _ = app_with(TOY_PAIR)
    uid = _upload(c, PAIR_BODY)["id"]
    res = c.get(f"/api/plan?source=file&upload={uid}").get_json()
    assert res["primary"] == "b" and res["track"]["id"] == "b"
    assert [(t["id"], t["label"]) for t in res["tracks"]] == [("a", "Alpha"), ("b", "Bravo")]
    assert res["tracks"][1]["t"] == [60.0, 120.0]  # onto track a's epoch
    assert res["summary"]["n_tracks"] == 2 and "primary" not in res["summary"]

    from mission_planner.modules.files import load_file

    f = tmp_path / "pair.txt"
    f.write_bytes(PAIR_BODY)
    out = load_file(str(f))
    assert [t["id"] for t in out["tracks"]] == ["a", "b"]
    assert out["tracks"][0]["span_s"] == [0.0, 60.0]
