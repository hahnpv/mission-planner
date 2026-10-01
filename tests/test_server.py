"""The web app's request handling: bad input is a 400 with a message, a
failure is JSON too, background jobs and the scene stream behave."""

import threading
import time

import pytest

import mission_planner.server as server
from mission_planner import jobs
from mission_planner.jobs import JobStore
from mission_planner.planning import default_dt

QS = "site=Cape+Canaveral+%2F+KSC&hp=400&inc=51.6&hours=2&epoch=2026-08-23T00:00:00%2B00:00"


# ---------------------------------------------------------------- /api/plan input


@pytest.mark.parametrize(
    "query, why",
    [
        ("dt=0", "dt must be positive"),
        ("hours=-5", "hours must not be negative"),
        ("hp=abc", "hp must be a number"),
        ("hp=nan", "hp must be a finite number"),
        ("hours=inf", "hours must be a finite number"),
        ("site=NoSuchSite", "unknown launch site 'NoSuchSite'"),
        ("hours=100000&dt=30", "raise dt"),
        ("epoch=yesterday", "ISO 8601"),
        ("mode=decay", "beta"),
        ("mode=decay&beta=100&hp=90", "entry interface"),
        ("mode=nope", "unknown mode 'nope'"),
        ("source=nope", "unknown source 'nope'"),
        ("site=Vandenberg&inc=10", "cannot pass over"),
    ],
)
def test_bad_plan_input_is_a_400_with_a_reason(core_client, query, why):
    r = core_client.get(f"/api/plan?{query}")
    assert r.status_code == 400, r.get_json()
    assert why in r.get_json()["error"]


def test_blank_optional_args_mean_absent(core_client):
    r = core_client.get(f"/api/plan?{QS}&hp=&ha=&beta=&dt=")
    assert r.status_code == 200 and r.get_json()["summary"]["alt_km"] == 400.0


def test_plan_carries_the_args_that_made_it_as_strings(core_client):
    res = core_client.get(f"/api/plan?{QS}&ha=&dt=").get_json()
    assert res["args"] == {  # blanks dropped, everything a string
        "site": "Cape Canaveral / KSC",
        "hp": "400",
        "inc": "51.6",
        "hours": "2",
        "epoch": "2026-08-23T00:00:00+00:00",
    }


def test_custom_site_from_lat_lon_keeps_its_label(core_client):
    s = core_client.get("/api/plan?hours=1&site=My+Pad&lat=10&lon=20").get_json()["summary"]
    assert (s["site"], s["site_lat"], s["site_lon"]) == ("My Pad", 10.0, 20.0)


def test_dt_defaults_to_the_horizon_rule(core_client):
    t = core_client.get("/api/plan?hours=720").get_json()["track"]["t"]
    assert t[1] == default_dt(720) == 130.0 and len(t) == int(720 * 3600 / 130) + 1


def test_api_404_and_500_are_json(app_with):
    def boom(a):
        raise RuntimeError("simulator exploded")

    client, _ = app_with({"name": "sim", "sources": {"bad": {"fn": boom, "kind": "orbit"}}})
    assert client.get("/api/nothing").get_json() == {
        "error": "The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again."
    }
    r = client.get("/api/plan?source=bad")
    assert r.status_code == 500
    assert r.get_json()["error"] == (
        "PluginError: source 'bad' (plugin 'sim') failed: RuntimeError: simulator exploded"
    )


def test_pages_outside_the_api_keep_flask_s_own_errors(core_client):
    r = core_client.get("/nothing")
    assert r.status_code == 404 and r.get_json() is None  # HTML, not {"error": ...}


def test_index_and_api_answers_are_never_cached(core_client):
    r = core_client.get("/")
    assert r.status_code == 200 and b"<title>" in r.data
    assert r.headers["Cache-Control"] == "no-store"
    assert core_client.get("/api/sites").headers["Cache-Control"] == "no-store"
    ev = core_client.get("/api/events")
    assert ev.mimetype == "text/event-stream" and ev.headers["Cache-Control"] == "no-store"
    ev.close()
    assert "Cache-Control" not in core_client.get("/ui/state.js").headers


def test_coastline_and_presets_come_from_the_core_data(core_client):
    coast = core_client.get("/api/coastline").get_json()
    assert coast["type"] == "FeatureCollection" and len(coast["features"]) > 50
    presets = {p["name"]: p for p in core_client.get("/api/presets").get_json()}
    assert {"ISS", "GEO", "Molniya", "GTO", "Sun-synchronous"} <= set(presets)
    sso = presets["Sun-synchronous"]
    assert sso["sun_synchronous"] is True and sso["pack"] == "core" and sso["perigee_km"] == 700


def test_unknown_plugin_assets_are_404(core_client):
    assert core_client.get("/plugins/nope/x.js").status_code == 404
    assert core_client.get("/plugins/passes/nope.js").status_code == 404


# ---------------------------------------------------------------- POST bodies


@pytest.mark.parametrize("body", [[1], {"layers": 5}, {"layers": [1]}, {"title": {"a": 1}}])
def test_scene_rejects_malformed_documents(core_client, body):
    r = core_client.post("/api/scene", json=body)
    assert r.status_code == 400 and "error" in r.get_json()


def test_scene_body_must_be_json(core_client):
    r = core_client.post("/api/scene", data="not json", content_type="text/plain")
    assert r.status_code == 400 and "must be JSON" in r.get_json()["error"]


@pytest.mark.parametrize(
    "layer",
    [
        {"kind": "track", "name": "t", "lat": [0, 1], "lon": [0]},
        {"kind": "track", "name": "t", "lat": "x", "lon": [0]},
        {"kind": "marker", "name": "m", "lat": "x", "lon": 0},
        {"kind": "marker", "name": "m", "lat": True, "lon": 0},
        {"kind": "windows", "name": "w", "columns": "a", "rows": []},
        {"kind": "windows", "name": "w", "columns": [], "rows": [1]},
        {"kind": "label", "text": "l", "lat": 0},
        {"kind": "label", "lat": 0, "lon": 0},
    ],
)
def test_scene_checks_layer_fields(core_client, layer):
    r = core_client.post("/api/scene", json={"layers": [layer]})
    assert r.status_code == 400 and layer["kind"] in r.get_json()["error"]


def test_scene_roundtrips_and_versions(core_client):
    doc = {"title": "demo", "layers": [{"kind": "marker", "name": "x", "lat": 1, "lon": 2}]}
    assert core_client.post("/api/scene", json=doc).get_json()["version"] == 1
    assert core_client.post("/api/scene", json=doc).get_json()["version"] == 2
    assert core_client.get("/api/scene").get_json() == {"version": 2, "scene": doc}


TRACK = {"t": [0, 60], "lat": [0, 1], "lon": [0, 1], "alt_km": [400, 400]}


@pytest.mark.parametrize(
    "plan, why",
    [
        ([1], "summary"),
        ({"track": TRACK}, "summary"),
        ({"summary": {}}, "track"),
        ({"summary": {}, "track": {k: v for k, v in TRACK.items() if k != "alt_km"}}, "alt_km"),
        ({"summary": {}, "track": {**TRACK, "lat": [0]}}, "same length"),
        ({"summary": {}, "track": {**TRACK, "alt_km": [1]}}, "same length"),
        ({"summary": {}, "track": TRACK, "tracks": 5}, "'tracks' must be a list"),
        ({"summary": {}, "track": TRACK, "tracks": [TRACK, {"t": [0]}]}, "tracks[1]"),
    ],
)
def test_scene_checks_its_plan(core_client, plan, why):
    r = core_client.post("/api/scene", json={"layers": [], "plan": plan})
    assert r.status_code == 400 and why in r.get_json()["error"]


def test_scene_carries_a_plan(core_client):
    plan = core_client.get("/api/plan?source=site&hours=1").get_json()
    doc = {"title": "pushed", "layers": [], "plan": plan}
    core_client.post("/api/scene", json=doc)
    assert core_client.get("/api/scene").get_json()["scene"] == doc


def test_module_toggle_rejects_non_object_bodies(core_client):
    r = core_client.post("/api/modules/passes", json=[1])
    assert r.status_code == 400 and "enabled" in r.get_json()["error"]


# ---------------------------------------------------------------- scene stream


def test_events_stream_reports_versions_wakes_on_a_scene_and_heartbeats(core_client, monkeypatch):
    monkeypatch.setattr(server, "SSE_HEARTBEAT_S", 0.05)
    core_client.post("/api/scene", json={"layers": []})
    chunks = iter(core_client.get("/api/events").response)
    assert next(chunks) == b'data: {"version": 1}\n\n'
    core_client.post("/api/scene", json={"layers": []})  # a new scene wakes the stream
    assert next(chunks) == b'data: {"version": 2}\n\n'
    assert (
        next(chunks) == b": ping\n\n"
    )  # nothing changed: the keep-alive that flushes dead clients


def test_scene_store_is_per_app(core_reg):
    a, b = server.create_app().test_client(), server.create_app().test_client()
    a.post("/api/scene", json={"layers": []})
    assert b.get("/api/scene").get_json()["version"] == 0


# ---------------------------------------------------------------- jobs


def test_running_jobs_are_never_evicted(wait_job):
    store = JobStore(keep=2)
    release = threading.Event()
    ids = [store.start(lambda: (release.wait(5), {"n": 1})[1]) for _ in range(5)]
    assert all(store.poll(i)["status"] == "running" for i in ids)
    store.start(lambda: {})  # nothing has finished: nothing to evict
    assert all(store.poll(i)["status"] == "running" for i in ids)
    release.set()
    for i in ids:
        assert wait_job(lambda: store.poll(i))["n"] == 1
    store.start(lambda: {})  # now the oldest finished ones may go
    assert store.poll(ids[-1]) is not None and store.poll(ids[0]) is None


def test_job_result_cannot_mask_its_status(wait_job):
    store = JobStore()
    job = store.start(lambda: {"status": "boom", "elapsed_s": -1, "x": 1})
    out = wait_job(lambda: store.poll(job))
    assert out["status"] == "done" and out["x"] == 1 and out["elapsed_s"] >= 0


def test_elapsed_stops_when_the_job_does(wait_job):
    store = JobStore()
    job = store.start(lambda: {"x": 1})
    done = wait_job(lambda: store.poll(job))
    time.sleep(0.15)  # more than elapsed_s's 0.1 s resolution
    assert store.poll(job)["elapsed_s"] == done["elapsed_s"]


def test_job_that_returns_no_dict_is_an_error(wait_job):
    # Through the module-level store plugins share.
    job = jobs.start(lambda: None)
    out = wait_job(lambda: jobs.poll(job))
    assert out["status"] == "error" and "not a dict" in out["error"]


def test_plan_job_reports_bad_input_as_a_job_error(core_client, wait_job):
    job = core_client.post("/api/plan_job?site=NoSuchSite").get_json()["job_id"]
    res = wait_job(lambda: core_client.get(f"/api/plan_job/{job}").get_json())
    assert res["status"] == "error" and "NoSuchSite" in res["error"]
    assert core_client.get("/api/plan_job/nope").status_code == 404


# ---------------------------------------------------------------- app construction


def test_app_attribute_is_built_lazily_over_the_process_registry(core_reg, monkeypatch):
    monkeypatch.setattr(server, "_APP", None)
    assert server.app is server.app
    mods = server.app.test_client().get("/api/modules").get_json()
    assert mods and all(m["builtin"] for m in mods)  # core_reg, not the installed plugins
