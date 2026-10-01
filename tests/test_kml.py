"""The built-in KML reader (modules/kml.py): detection, the panel's inspect,
timed tracks, untimed paths, KMZ, and the File source end to end."""

import io
import zipfile
from datetime import datetime, timezone

import numpy as np
import pytest

from mission_planner import filekinds
from mission_planner.modules import kml

KML_NS = 'xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2"'


def doc(body: str, name: str = "") -> bytes:
    nm = f"<name>{name}</name>" if name else ""
    return f'<?xml version="1.0"?>\n<kml {KML_NS}><Document>{nm}{body}</Document></kml>'.encode()


def track(name: str, samples, clamp=False) -> str:
    """A Placemark with a gx:Track: samples are (when, lon, lat, alt_m)."""
    mode = "<altitudeMode>clampToGround</altitudeMode>" if clamp else ""
    whens = "".join(f"<when>{w}</when>" for w, *_ in samples)
    coords = "".join(f"<gx:coord>{lon} {lat} {alt}</gx:coord>" for _, lon, lat, alt in samples)
    return f"<Placemark><name>{name}</name><gx:Track>{mode}{whens}{coords}</gx:Track></Placemark>"


def path(name: str, points, clamp=False) -> str:
    """A Placemark with a LineString: points are (lon, lat[, alt_m])."""
    mode = "<altitudeMode>clampToGround</altitudeMode>" if clamp else ""
    coords = " ".join(",".join(str(v) for v in p) for p in points)
    return (
        f"<Placemark><name>{name}</name><LineString>{mode}"
        f"<coordinates>{coords}</coordinates></LineString></Placemark>"
    )


T0 = "2026-03-01T12:00:00Z"
TIMED = doc(
    track(
        "Sat A",
        [(T0, 10.0, 0.0, 400e3), ("2026-03-01T12:01:00Z", 11.0, 1.0, 401e3)],
    )
    + track(
        "Sat B",
        [("2026-03-01T12:00:30Z", -170.0, 5.0, 500e3), ("2026-03-01T12:02:00Z", 190.0, 6.0, 500e3)],
    ),
    name="Two sats",
)
PATH = doc(path("Ground trace", [(0, 0, 0), (1, 1, 0), (2, 2, 0), (3, 3, 0)]))


@pytest.fixture
def file(tmp_path):
    def make(body: bytes, name="t.kml"):
        p = tmp_path / name
        p.write_bytes(body)
        return p

    return make


# ---------------------------------------------------------------- detect
def test_detect_kml_kmz_and_not_the_rest(file, tmp_path):
    assert kml.detect(file(TIMED))
    assert kml.detect(file(b'<kml xmlns="http://earth.google.com/kml/2.1"><Document/></kml>'))
    assert kml.detect(file(b"\xef\xbb\xbf<?xml version='1.0'?><kml></kml>"))  # a BOM
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.kml", TIMED)
    assert kml.detect(file(buf.getvalue(), "t.kmz"))
    other = io.BytesIO()
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("readme.txt", "no kml here")
    assert not kml.detect(file(other.getvalue(), "o.zip"))
    assert not kml.detect(file(b"<gpx><trk/></gpx>"))
    assert not kml.detect(file(b"\x89HDF\r\n\x1a\n\0\0"))
    assert not kml.detect(tmp_path / "missing.kml")


# ---------------------------------------------------------------- timed tracks
def test_timed_tracks_share_the_first_when_as_epoch(file):
    gts, meta = kml.read(file(TIMED), {})
    assert [g.id for g in gts] == ["sat-a", "sat-b"] and [g.label for g in gts] == [
        "Sat A",
        "Sat B",
    ]
    assert gts[0].epoch == datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    assert gts[0].t.tolist() == [0.0, 60.0] and gts[1].t.tolist() == [30.0, 120.0]
    assert np.allclose(np.degrees(gts[0].lat), [0.0, 1.0])
    assert np.allclose(np.degrees(gts[1].lon), [-170.0, -170.0])  # 190 wraps
    assert gts[0].alt.tolist() == [400e3, 401e3]
    assert meta["title"] == "Two sats" and meta["primary"] == "sat-a"
    assert meta["tracks"] == 2 and meta["timed"] and meta["duration_s"] == 120.0
    assert meta["epoch_from"] == "the first <when>" and meta["samples"] == 4


def test_single_track_is_titled_after_its_placemark(file):
    gt, meta = kml.read(
        file(doc(track("ISS", [(T0, 0, 0, 1), ("2026-03-01T12:00:10Z", 1, 1, 2)]))), {}
    )
    assert gt.label == "ISS" and meta["title"] == "ISS" and "primary" not in meta


def test_request_epoch_moves_t0(file):
    gt, meta = kml.read(
        file(doc(track("x", [(T0, 0, 0, 0), ("2026-03-01T12:00:10Z", 1, 1, 0)]))),
        {"epoch": "2030-01-01T00:00:00Z"},
    )
    assert (
        gt.epoch.year == 2030 and gt.t.tolist() == [0.0, 10.0] and meta["epoch_from"] == "request"
    )


def test_multitrack_segments_join_and_clamp_zeroes_altitude(file):
    body = (
        "<Placemark><name>leg</name><gx:MultiTrack>"
        f"<gx:Track><when>{T0}</when><gx:coord>0 0 100</gx:coord></gx:Track>"
        "<gx:Track><altitudeMode>clampToGround</altitudeMode>"
        "<when>2026-03-01T12:00:05Z</when><gx:coord>1 1 100</gx:coord></gx:Track>"
        "</gx:MultiTrack></Placemark>"
    )
    gt, _ = kml.read(file(doc(body)), {})
    assert gt.t.tolist() == [0.0, 5.0] and gt.alt.tolist() == [100.0, 0.0]


def test_when_forms_and_bad_values(file):
    body = track("x", [("2026", 0, 0, 0), ("2026-02", 0, 0, 0), ("2026-02-03", 0, 0, 0)])
    gt, _ = kml.read(file(doc(body)), {})
    assert gt.t.tolist() == [0.0, 31 * 86400.0, 33 * 86400.0]
    with pytest.raises(ValueError, match="placemark 'x'.*not an ISO 8601"):
        kml.read(file(doc(track("x", [("yesterday", 0, 0, 0)]))), {})
    with pytest.raises(ValueError, match="1 <when> for 2 <gx:coord>"):
        kml.read(
            file(
                doc(
                    f"<Placemark><name>x</name><gx:Track><when>{T0}</when>"
                    "<gx:coord>0 0 0</gx:coord><gx:coord>1 1 1</gx:coord></gx:Track></Placemark>"
                )
            ),
            {},
        )
    with pytest.raises(ValueError, match="runs backwards"):
        kml.read(file(doc(track("x", [(T0, 0, 0, 0), ("2026-03-01T11:00:00Z", 1, 1, 0)]))), {})


# ---------------------------------------------------------------- paths
def test_path_is_sampled_at_the_step_from_j2000(file):
    gt, meta = kml.read(file(PATH), {})
    assert gt.epoch == kml.J2000 and gt.t.tolist() == [0.0, 60.0, 120.0, 180.0]
    assert meta["step_s"] == 60.0 and not meta["timed"] and "no times" in meta["epoch_from"]
    gt, meta = kml.read(file(PATH), {"step": "10"})
    assert gt.t.tolist() == [0.0, 10.0, 20.0, 30.0] and meta["step_s"] == 10.0
    with pytest.raises(ValueError, match="step must be positive"):
        kml.read(file(PATH), {"step": "0"})


def test_path_takes_the_documents_timestamp(file):
    body = f"<TimeStamp><when>{T0}</when></TimeStamp>" + path("p", [(0, 0), (1, 1)])
    gt, meta = kml.read(file(doc(body)), {})
    assert gt.epoch == datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    assert meta["epoch_from"] == "the file's TimeStamp" and gt.alt.tolist() == [0.0, 0.0]


def test_timed_tracks_win_over_paths(file):
    body = track("t", [(T0, 0, 0, 0), ("2026-03-01T12:00:10Z", 1, 1, 0)]) + path(
        "p", [(0, 0), (1, 1)]
    )
    gt, meta = kml.read(file(doc(body)), {})
    assert gt.label == "t" and meta["paths_ignored"] == 1
    info = kml.inspect(file(doc(body)))
    assert "1 untimed path set aside" in info["warning"] and info["options"] == []


def test_nothing_to_show(file):
    with pytest.raises(ValueError, match="no track in this file"):
        kml.read(
            file(doc("<Placemark><Point><coordinates>0,0</coordinates></Point></Placemark>")), {}
        )
    with pytest.raises(ValueError, match="not well-formed"):
        kml.read(file(b"<kml><Document>"), {})
    with pytest.raises(ValueError, match="not numbers"):
        kml.read(file(doc(path("p", [("a", "b")]))), {})


def test_long_tracks_are_thinned(file, monkeypatch):
    monkeypatch.setattr(kml, "TARGET_POINTS", 5)
    pts = [(i * 0.01, 0) for i in range(100)]
    gt, meta = kml.read(file(doc(path("p", pts))), {})
    assert len(gt.t) == 5 and gt.t[0] == 0.0 and gt.t[-1] == 99 * 60.0 and meta["samples"] == 5


def test_unnamed_placemarks_get_distinct_ids(file):
    body = (
        path("", [(0, 0), (1, 1)])
        + path("", [(0, 0), (1, 1)])
        + path("A", [(0, 0)])
        + path("a", [(1, 1)])
    )
    gts, _ = kml.read(file(doc(body)), {})
    assert [g.id for g in gts] == ["track1", "track2", "a", "a-2"] and gts[0].label is None


# ---------------------------------------------------------------- inspect
def test_inspect_describes_the_file(file):
    info = kml.inspect(file(TIMED))
    assert info["summary"] == "2 tracks: Sat A, Sat B · timed, 4 samples over 2.0 min"
    assert info["warning"] is None and info["epoch_note"] == "the first <when>"
    assert info["epoch_utc"] == "2026-03-01T12:00:00+00:00" and info["options"] == []
    info = kml.inspect(file(PATH))
    assert info["summary"].startswith("1 path: Ground trace · 4 points, no times")
    assert [o["key"] for o in info["options"]] == ["step"] and info["options"][0]["default"] == "60"
    many = doc("".join(path(f"p{i}", [(i, 0), (i, 1)]) for i in range(5)))
    assert "p0, p1, p2 … (+2)" in kml.inspect(file(many))["summary"]


# ---------------------------------------------------------------- through the app
def test_kml_through_the_file_source(core_client):
    up = core_client.post("/api/uploads", data={"file": (io.BytesIO(TIMED), "sats.kml")}).get_json()
    assert (up["kind"], up["kind_label"]) == ("kml", "KML track")
    info = core_client.get(f"/api/files/{up['id']}/inspect").get_json()
    assert info["kind"] == "kml" and info["summary"].startswith("2 tracks")
    plan = core_client.get(f"/api/plan?source=file&upload={up['id']}").get_json()
    assert plan["summary"]["reader"] == "kml" and plan["summary"]["file"] == "sats.kml"
    assert plan["summary"]["kind"] == "trajectory" and plan["primary"] == "sat-a"
    assert [t["id"] for t in plan["tracks"]] == ["sat-a", "sat-b"]
    assert plan["tracks"][1]["t"] == [30.0, 120.0]  # one clock for the plan
    # Pass search spans the plan's tracks.
    res = core_client.get(
        f"/api/passes?source=file&upload={up['id']}&tgt_lat=5.5&tgt_lon=-170&within_km=200"
    ).get_json()
    assert [p["track"] for p in res["passes"]] == ["sat-b"]


def test_kmz_through_the_file_source(core_client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.kml", PATH)
    up = core_client.post(
        "/api/uploads", data={"file": (io.BytesIO(buf.getvalue()), "p.kmz")}
    ).get_json()
    assert up["kind"] == "kml"
    plan = core_client.get(f"/api/plan?source=file&upload={up['id']}&step=10").get_json()
    assert plan["summary"]["title"] == "Ground trace" and plan["track"]["t"] == [
        0.0,
        10.0,
        20.0,
        30.0,
    ]


def test_load_file_mcp_tool_reads_kml(core_reg, tmp_path):
    from mission_planner.modules.files import load_file

    p = tmp_path / "sats.kml"
    p.write_bytes(TIMED)
    out = load_file(str(p))
    assert out["reader"] == "kml" and [t["id"] for t in out["tracks"]] == ["sat-a", "sat-b"]
    assert out["tracks"][0]["span_s"] == [0.0, 60.0]
    assert filekinds.detect(out["upload"])["kind"] == "kml"
