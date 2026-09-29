"""The web app's request handling: bad input is a 400 with a message, a
failure is JSON too, background jobs and the scene stream behave."""

import time

import pytest

import mission_planner.server as server
from mission_planner import jobs
from mission_planner.jobs import JobStore

QS = "site=Cape+Canaveral+%2F+KSC&hp=400&inc=51.6&hours=2&epoch=2026-08-23T00:00:00%2B00:00"


# ---------------------------------------------------------------- /api/plan input


@pytest.mark.parametrize(
    "query, why",
    [
        ("dt=0", "dt must be positive"),
        ("hours=-5", "hours must not be negative"),
        ("hp=abc", "hp must be a number"),
        ("site=NoSuchSite", "unknown launch site 'NoSuchSite'"),
        ("hours=100000&dt=30", "raise dt"),
        ("epoch=yesterday", "ISO 8601"),
        ("mode=decay", "beta"),
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


def test_custom_site_from_lat_lon_keeps_its_label(core_client):
    s = core_client.get("/api/plan?hours=1&site=My+Pad&lat=10&lon=20").get_json()["summary"]
    assert (s["site"], s["site_lat"], s["site_lon"]) == ("My Pad", 10.0, 20.0)


def test_dt_defaults_to_a_sane_point_count(core_client):
    t = core_client.get("/api/plan?hours=720").get_json()["track"]["t"]
    assert 5000 < len(t) < 25000


def test_api_404_and_500_are_json(core_client, core_reg):
    assert core_client.get("/api/nothing").get_json() == {
        "error": "The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again."
    }

    def boom(a):
        raise RuntimeError("simulator exploded")

    core_reg.records["passes"].spec["sources"] = {"bad": {"fn": boom, "kind": "orbit"}}
    r = core_client.get("/api/plan?source=bad")
    assert r.status_code == 500
    assert (
        "plugin 'passes'" in r.get_json()["error"] and "simulator exploded" in r.get_json()["error"]
    )


# ---------------------------------------------------------------- POST bodies


@pytest.mark.parametrize("body", [[1], {"layers": 5}, {"layers": [1]}, {"title": {"a": 1}}])
def test_scene_rejects_malformed_documents(core_client, body):
    r = core_client.post("/api/scene", json=body)
    assert r.status_code == 400 and "error" in r.get_json()


@pytest.mark.parametrize(
    "layer",
    [
        {"kind": "track", "name": "t", "lat": [0, 1], "lon": [0]},
        {"kind": "marker", "name": "m", "lat": "x", "lon": 0},
        {"kind": "windows", "name": "w", "columns": "a", "rows": []},
        {"kind": "label", "text": "l", "lat": 0},
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


def test_module_toggle_rejects_non_object_bodies(core_client):
    r = core_client.post("/api/modules/passes", json=[1])
    assert r.status_code == 400 and "enabled" in r.get_json()["error"]


# ---------------------------------------------------------------- scene stream


def test_events_stream_reports_versions_and_heartbeats(core_client, monkeypatch):
    monkeypatch.setattr(server, "SSE_HEARTBEAT_S", 0.05)
    core_client.post("/api/scene", json={"layers": []})
    chunks = iter(core_client.get("/api/events").response)
    assert next(chunks) == b'data: {"version": 1}\n\n'
    assert (
        next(chunks) == b": ping\n\n"
    )  # nothing changed: the keep-alive that flushes dead clients


def test_scene_store_is_per_app(core_reg):
    a, b = server.create_app().test_client(), server.create_app().test_client()
    a.post("/api/scene", json={"layers": []})
    assert b.get("/api/scene").get_json()["version"] == 0


# ---------------------------------------------------------------- jobs


def test_running_jobs_are_never_evicted():
    store = JobStore(keep=2)
    ids = [store.start(lambda: (time.sleep(0.3), {"n": 1})[1]) for _ in range(5)]
    assert all(store.poll(i)["status"] == "running" for i in ids)
    for _ in range(50):
        if all(store.poll(i)["status"] == "done" for i in ids):
            break
        time.sleep(0.05)
    store.start(lambda: {})  # now the oldest finished ones may go
    assert store.poll(ids[-1]) is not None and store.poll(ids[0]) is None


def test_job_result_cannot_mask_its_status():
    store = JobStore()
    job = store.start(lambda: {"status": "boom", "elapsed_s": -1, "x": 1})
    for _ in range(50):
        out = store.poll(job)
        if out["status"] != "running":
            break
        time.sleep(0.02)
    assert out["status"] == "done" and out["x"] == 1 and out["elapsed_s"] >= 0


def test_job_that_returns_no_dict_is_an_error():
    job = jobs.start(lambda: None)
    for _ in range(50):
        out = jobs.poll(job)
        if out["status"] != "running":
            break
        time.sleep(0.02)
    assert out["status"] == "error" and "not a dict" in out["error"]


def test_plan_job_reports_bad_input_as_a_job_error(core_client):
    job = core_client.post("/api/plan_job?site=NoSuchSite").get_json()["job_id"]
    for _ in range(100):
        res = core_client.get(f"/api/plan_job/{job}").get_json()
        if res["status"] != "running":
            break
        time.sleep(0.02)
    assert res["status"] == "error" and "NoSuchSite" in res["error"]
    assert core_client.get("/api/plan_job/nope").status_code == 404


# ---------------------------------------------------------------- app construction


def test_app_attribute_is_built_lazily_and_once():
    assert server.app is server.app
    assert server.create_app() is not server.app
