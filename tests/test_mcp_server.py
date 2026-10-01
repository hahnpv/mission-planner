"""The MCP server: every tool registers, the core ones work without the UI."""

import asyncio
import io
import urllib.error

import pytest

pytest.importorskip("mcp")

# conftest.py installed a core-only registry before this import, which is
# when mcp_server registers the active plugins' tools.
from helpers import core_registry  # noqa: E402

import mission_planner.mcp_server as ms  # noqa: E402
from mission_planner.planning import default_dt  # noqa: E402
from mission_planner.plugins import CORE_MCP_TOOLS  # noqa: E402

EPOCH = "2026-08-23T00:00:00Z"


def tool_names():
    return {t.name for t in asyncio.run(ms.mcp.list_tools())}


def test_registered_tools_are_exactly_the_core_list_plus_the_builtin_modules(core_reg):
    module_tools = {fn.__name__ for r in core_reg.records.values() for fn in r.get("mcp_tools", [])}
    assert module_tools == {"find_passes", "maneuver_budget", "load_file"}
    # CORE_MCP_TOOLS is what the registry checks plugin tool names against,
    # so it must name every tool mcp_server.py defines itself.
    assert tool_names() == set(CORE_MCP_TOOLS) | module_tools


def test_plan_orbit_site_and_element_anchored():
    site = ms.plan_orbit(site="Kourou", alt_km=500.0, inc_deg=6.0, epoch_utc=EPOCH, hours=2)
    assert site["launch_azimuth_deg"] == pytest.approx(86.8, abs=0.1)  # east, a touch north
    assert site["summary"]["inc_deg"] == 6.0 and "entry" not in site
    geo = ms.plan_orbit(site="", alt_km=35786.0, inc_deg=0.0, node_lon_deg=-100.0, epoch_utc=EPOCH)
    assert geo["launch_azimuth_deg"] is None and geo["summary"]["revs_per_day"] == pytest.approx(
        1.0, abs=0.01
    )
    with pytest.raises(ValueError, match="unknown launch site"):
        ms.plan_orbit(site="Atlantis")


def test_plan_orbit_decay_reports_entry():
    out = ms.plan_orbit(alt_km=200.0, mode="decay", beta=300.0, hours=24 * 20, epoch_utc=EPOCH)
    assert out["entry"] is not None and out["final_alt_km"] == pytest.approx(100.0, abs=2.0)


def test_plan_orbit_passes_on_a_plugin_mode_s_impact(monkeypatch):
    def to_the_ground(orbit, beta, duration_s, dt_s):
        gt = orbit.ground_track(duration_s, dt_s)
        gt.extra["impact"] = {"t_s": 99.0, "lat_deg": 1.0, "lon_deg": 2.0}
        return gt

    reg = core_registry({"name": "sim", "propagators": {"fly": {"fn": to_the_ground}}})
    monkeypatch.setattr("mission_planner.plugins._REGISTRY", reg)
    out = ms.plan_orbit(mode="fly", hours=1, epoch_utc=EPOCH)
    assert out["impact"]["t_s"] == 99.0 and "entry" not in out


def test_track_samples_downsamples_a_window_of_the_plan():
    out = ms.track_samples(site="Kourou", alt_km=500.0, inc_deg=6.0, epoch_utc=EPOCH, hours=6)
    assert out["n"] == 361 and out["t_s"][-1] == 6 * 3600  # 60 s steps: all of them fit
    few = ms.track_samples(
        site="Kourou",
        alt_km=500.0,
        inc_deg=6.0,
        epoch_utc=EPOCH,
        hours=6,
        max_points=10,
        start_hours=1,
        end_hours=2,
    )
    assert few["n"] == 10 and few["t_s"][0] == 3600 and few["t_s"][-1] == 7200
    assert set(few) == {"epoch_utc", "n", "dt_s", "t_s", "lat_deg", "lon_deg", "alt_km"}
    assert all(len(few[k]) == 10 for k in ("lat_deg", "lon_deg", "alt_km"))
    assert max(abs(x) for x in out["lat_deg"]) <= 6.01  # never above the inclination
    with pytest.raises(ValueError, match="max_points"):
        ms.track_samples(max_points=1)
    with pytest.raises(ValueError, match="end_hours"):
        ms.track_samples(start_hours=2, end_hours=1)


def test_track_samples_window_is_clipped_by_entry_and_coarsens_with_the_horizon():
    # A decay track ends at entry (~7 days here), well before the window's end.
    w = ms.track_samples(
        alt_km=200.0, mode="decay", beta=300.0, hours=480, epoch_utc=EPOCH, max_points=5000
    )
    assert w["n"] == 5000 and w["t_s"][-1] < 480 * 3600
    assert w["alt_km"][-1] == pytest.approx(100.0, abs=0.5) and w["dt_s"] == default_dt(480, 60.0)
    # A month at the 60 s floor would be 43k samples: the step coarsens first.
    c = ms.track_samples(site="Kourou", alt_km=500.0, inc_deg=6.0, epoch_utc=EPOCH, hours=720)
    assert c["n"] == 500 and c["dt_s"] == 130.0
    assert c["t_s"][-1] == 720 * 3600 - (720 * 3600) % 130  # the last whole step


def test_list_launch_sites_tags_packs():
    sites = ms.list_launch_sites()["sites"]
    assert {"name", "lat", "lon", "pack"} <= set(sites[0])
    assert any(s["name"] == "Cape Canaveral / KSC" and s["pack"] == "core" for s in sites)
    assert {s["pack"] for s in sites} == {"core"}  # no data packs in the core's suite


def test_show_plan_pushes_a_timed_plan_for_every_orbit_kind(monkeypatch, core_client):
    posted = []
    monkeypatch.setattr(ms, "_post_scene", lambda doc: posted.append(doc) or {"version": 1})
    ms.show_plan(
        site="Vandenberg", inc_deg=98.0, epoch_utc=EPOCH, hours=3, tgt_lat=34.7, tgt_lon=-120.6
    )
    ms.show_plan(site="", alt_km=35786.0, inc_deg=0.0, node_lon_deg=-100.0, epoch_utc=EPOCH)
    # The plan is the UI's own /api/plan answer for the same orbit, times and all
    # (the args that made it ride along, spelt the tool's way).
    q = "source=site&site=Vandenberg&hp=400&ha=400&inc=98&hours=3&dt=60&epoch=" + EPOCH
    plan = dict(posted[0]["plan"])
    args = plan.pop("args")
    assert plan == {
        k: v for k, v in core_client.get("/api/plan?" + q).get_json().items() if k != "args"
    }
    assert args["source"] == "site" and args["site"] == "Vandenberg" and args["hours"] == "3"
    assert posted[0]["plan"]["track"]["t"][-1] == 3 * 3600
    # Layers only annotate: the target and its passes.
    kinds = [[layer["kind"] for layer in doc["layers"]] for doc in posted]
    assert kinds[0] == ["marker", "windows"]
    assert kinds[1] == [] and posted[1]["title"].startswith("node -100")
    assert posted[1]["plan"]["summary"]["source"] == "preset"


def test_show_plan_titles_the_planned_shape_and_flies_drag_modes(monkeypatch):
    posted = []
    monkeypatch.setattr(ms, "_post_scene", lambda doc: posted.append(doc) or {"version": 1})
    ms.show_plan(site="Kourou", perigee_km=500.0, apogee_km=500.0, inc_deg=6.0, epoch_utc=EPOCH)
    ms.show_plan(site="Kourou", perigee_km=250.0, apogee_km=35786.0, inc_deg=6.0, epoch_utc=EPOCH)
    ms.show_plan(alt_km=200.0, mode="decay", beta=300.0, hours=240, epoch_utc=EPOCH)
    assert posted[0]["title"] == "Kourou · 500 km / 6.0°"  # the planned altitude, not alt_km
    assert posted[1]["title"] == "Kourou · 250x35786 km / 6.0°"
    decay = posted[2]["plan"]
    assert decay["track"]["entry"] is not None and decay["summary"]["alt_km"] == 200.0
    assert decay["args"]["mode"] == "decay" and decay["args"]["beta"] == "300.0"


def test_show_scene_validates_before_posting(monkeypatch):
    posted = []
    monkeypatch.setattr(ms, "_post_scene", lambda doc: posted.append(doc) or {"version": 3})
    with pytest.raises(ValueError, match="unknown layer kind"):
        ms.show_scene({"layers": [{"kind": "nope"}]})
    assert posted == []
    out = ms.show_scene(
        {"title": "t", "layers": [{"kind": "label", "text": "hi", "lat": 1, "lon": 2}]}
    )
    assert out == {"ok": True, "url": ms.UI_URL, "version": 3}
    assert posted[0]["title"] == "t" and posted[0]["layers"][0]["text"] == "hi"


def test_post_scene_reports_the_ui_s_answer_or_its_absence(monkeypatch):
    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    sent = []
    monkeypatch.setattr(
        ms.urllib.request,
        "urlopen",
        lambda req, timeout: sent.append(req) or Reply(b'{"version": 7}'),
    )
    assert ms._post_scene({"layers": []}) == {"version": 7}
    assert sent[0].full_url == ms.UI_URL + "/api/scene" and sent[0].get_method() == "POST"

    def http_error(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad", {}, io.BytesIO(b'{"error": "no such layer"}')
        )

    monkeypatch.setattr(ms.urllib.request, "urlopen", http_error)
    with pytest.raises(RuntimeError, match="rejected the scene .400.: no such layer"):
        ms._post_scene({"layers": []})

    def html_error(req, timeout):  # a proxy's page, not the UI's JSON
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, io.BytesIO(b"<html>"))

    monkeypatch.setattr(ms.urllib.request, "urlopen", html_error)
    with pytest.raises(RuntimeError, match="rejected the scene .502.: Bad Gateway"):
        ms._post_scene({"layers": []})

    def refused(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(ms.urllib.request, "urlopen", refused)
    with pytest.raises(RuntimeError, match="not reachable at http://127.0.0.1:3030 .*server"):
        ms._post_scene({"layers": []})
