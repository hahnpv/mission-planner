"""The upload store (content ids, listing) and its routes, plus a trajectory
source that plans from an uploaded file end to end."""

import io
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner import uploads
from mission_planner.groundtrack import GroundTrack


def test_put_is_content_addressed(tmp_path):
    a = uploads.put_stream(io.BytesIO(b"hello"), "a.txt")
    b = uploads.put_stream(io.BytesIO(b"hello"), "dir/b.txt")
    c = uploads.put_stream(io.BytesIO(b"other"), "c.txt")
    assert a["id"] == b["id"] != c["id"]
    assert b["name"] == "b.txt"  # the latest upload names it; no directories
    assert uploads.path(a["id"]).read_bytes() == b"hello"
    assert uploads.info(c["id"])["size"] == 5
    f = tmp_path / "local.h5"
    f.write_bytes(b"xyz")
    assert uploads.put_file(f)["name"] == "local.h5"


def test_store_defaults_to_the_xdg_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("MP_UPLOAD_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert uploads.upload_dir() == tmp_path / "xdg" / "mission-planner" / "uploads"
    assert uploads.upload_dir().is_dir()


def test_list_newest_first_and_by_extension():
    ids = [uploads.put_stream(io.BytesIO(n.encode()), n)["id"] for n in ("x.h5", "y.CSV")]
    # Same-second uploads: order by the stored time, which we make distinct.
    for uid, ts in zip(ids, ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")):
        uploads.update_info(uid, uploaded_utc=ts)
    assert [x["id"] for x in uploads.list_uploads()] == ids[::-1]
    assert [x["name"] for x in uploads.list_uploads([".csv"])] == ["y.CSV"]
    assert uploads.list_uploads([".h5", ".hdf5"])[0]["name"] == "x.h5"


def test_listing_skips_strays_and_a_lost_sidecar_still_describes_its_file(upload_dir):
    uid = uploads.put_stream(io.BytesIO(b"kept"), "k.bin")["id"]
    (upload_dir / "notes.json").write_text("{}")  # not an upload id
    (upload_dir / ("f" * 24 + ".json")).write_text("{}")  # a sidecar whose data is gone
    uploads.path(uid).with_name(uid + ".json").unlink()  # the data without its sidecar
    assert [x["id"] for x in uploads.list_uploads()] == []  # listing goes by sidecars
    assert uploads.info(uid) == {"id": uid, "name": uid, "size": 4, "uploaded_utc": None}
    uploads.path(uid).with_name(uid + ".json").write_text("not json")
    assert uploads.info(uid)["name"] == uid  # a corrupt sidecar: the same fallback


@pytest.mark.parametrize("uid", ["", None, "../etc/passwd", "a" * 24 + "/x", "0" * 24])
def test_bad_or_unknown_ids_are_value_errors(uid):
    with pytest.raises(ValueError):
        uploads.path(uid)


def test_oversized_upload_is_refused(monkeypatch, upload_dir):
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ValueError, match="exceeds"):
        uploads.put_stream(io.BytesIO(b"x" * 11), "big")
    assert not list(upload_dir.iterdir())  # no partial file left behind


def test_upload_routes(core_client):
    r = core_client.post("/api/uploads", data={"file": (io.BytesIO(b"abc"), "run.h5")})
    assert r.status_code == 200
    up = r.get_json()
    assert up["name"] == "run.h5" and up["size"] == 3
    assert up["kind"] is None and "no active plugin" in up["kind_note"]  # no reader claims it
    assert core_client.get(f"/api/uploads/{up['id']}").get_json()["name"] == "run.h5"
    assert [x["id"] for x in core_client.get("/api/uploads?ext=.h5").get_json()] == [up["id"]]
    assert core_client.get("/api/uploads?ext=.csv").get_json() == []
    assert core_client.get("/api/uploads/" + "0" * 24).status_code == 404
    r = core_client.post("/api/uploads", data={})
    assert r.status_code == 400 and "file" in r.get_json()["error"]


def _from_file(a):
    """A toy trajectory source: an upload of lines 't lat lon alt'."""
    rows = np.loadtxt(uploads.path(a.get("upload")), ndmin=2)
    t, lat, lon, alt = rows.T
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    gt = GroundTrack(epoch, t, np.radians(lat), np.radians(lon), alt)
    return gt, {"title": uploads.info(a["upload"])["name"]}


def test_trajectory_source_plans_from_an_upload(app_with):
    spec = {
        "api": 1,
        "name": "fromfile",
        "sources": {"ff": {"fn": _from_file, "label": "file", "kind": "trajectory"}},
    }
    client, _ = app_with(spec)
    body = b"0 10 20 1000\n60 11 21 900\n"
    up = client.post("/api/uploads", data={"file": (io.BytesIO(body), "t.txt")}).get_json()
    res = client.get(f"/api/plan?source=ff&upload={up['id']}").get_json()
    assert res["summary"]["title"] == "t.txt" and res["summary"]["kind"] == "trajectory"
    assert res["track"]["lat"] == [10.0, 11.0]
    err = client.get("/api/plan?source=ff&upload=nope").get_json()["error"]
    assert "not an upload id" in err


def test_delete(core_client, upload_dir):
    up = uploads.put_stream(io.BytesIO(b"gone soon"), "g.h5")
    keep = uploads.put_stream(io.BytesIO(b"stays"), "k.h5")
    r = core_client.delete(f"/api/uploads/{up['id']}")
    assert r.status_code == 200 and r.get_json()["name"] == "g.h5"
    assert sorted(p.name for p in upload_dir.iterdir()) == sorted(
        [keep["id"], keep["id"] + ".json"]
    )
    assert [x["id"] for x in uploads.list_uploads()] == [keep["id"]]
    with pytest.raises(ValueError):
        uploads.path(up["id"])
    assert core_client.delete(f"/api/uploads/{up['id']}").status_code == 404
    assert core_client.delete("/api/uploads/..%2Fx").status_code == 404
    # Same content again: same id, back in business.
    assert uploads.put_stream(io.BytesIO(b"gone soon"), "g.h5")["id"] == up["id"]
    assert (
        json.loads(uploads.path(up["id"]).with_name(up["id"] + ".json").read_text())["name"]
        == "g.h5"
    )
