"""The MCP server: every tool registers, the core ones work without the UI."""

import asyncio

import pytest

pytest.importorskip("mcp")

import mission_planner.mcp_server as ms  # noqa: E402

EPOCH = "2026-08-23T00:00:00Z"


def tool_names():
    return {t.name for t in asyncio.run(ms.mcp.list_tools())}


def test_core_and_module_tools_are_registered():
    names = tool_names()
    assert {"plan_orbit", "list_launch_sites", "show_scene", "show_plan"} <= names
    assert {"find_passes", "maneuver_budget"} <= names  # built-in modules' tools


def test_plan_orbit_site_and_element_anchored():
    site = ms.plan_orbit(site="Kourou", alt_km=500.0, inc_deg=6.0, epoch_utc=EPOCH, hours=2)
    assert site["launch_azimuth_deg"] is not None and site["summary"]["inc_deg"] == 6.0
    geo = ms.plan_orbit(site="", alt_km=35786.0, inc_deg=0.0, node_lon_deg=-100.0, epoch_utc=EPOCH)
    assert geo["launch_azimuth_deg"] is None and geo["summary"]["revs_per_day"] == pytest.approx(
        1.0, abs=0.01
    )
    with pytest.raises(ValueError, match="unknown launch site"):
        ms.plan_orbit(site="Atlantis")


def test_plan_orbit_decay_reports_entry():
    out = ms.plan_orbit(alt_km=200.0, mode="decay", beta=300.0, hours=24 * 20, epoch_utc=EPOCH)
    assert out["entry"] is not None and out["final_alt_km"] == pytest.approx(100.0, abs=2.0)


def test_list_launch_sites_tags_packs():
    sites = ms.list_launch_sites()["sites"]
    assert {"name", "lat", "lon", "pack"} <= set(sites[0])
    assert any(s["name"] == "Cape Canaveral / KSC" and s["pack"] == "core" for s in sites)


def test_show_plan_pushes_a_timed_plan_for_every_orbit_kind(monkeypatch, core_client):
    posted = []
    monkeypatch.setattr(ms, "_post_scene", lambda doc: posted.append(doc) or {"version": 1})
    ms.show_plan(
        site="Vandenberg", inc_deg=98.0, epoch_utc=EPOCH, hours=3, tgt_lat=34.7, tgt_lon=-120.6
    )
    ms.show_plan(site="", alt_km=35786.0, inc_deg=0.0, node_lon_deg=-100.0, epoch_utc=EPOCH)
    # The plan is the UI's own /api/plan answer for the same orbit, times and all.
    q = "source=site&site=Vandenberg&hp=400&ha=400&inc=98&hours=3&dt=60&epoch=" + EPOCH
    assert posted[0]["plan"] == core_client.get("/api/plan?" + q).get_json()
    assert posted[0]["plan"]["track"]["t"][-1] == 3 * 3600
    # Layers only annotate: the target and its passes.
    kinds = [[layer["kind"] for layer in doc["layers"]] for doc in posted]
    assert kinds[0] == ["marker", "windows"]
    assert kinds[1] == [] and posted[1]["title"].startswith("node -100")
    assert posted[1]["plan"]["summary"]["source"] == "preset"


def test_ui_errors_are_distinguished_from_an_absent_ui(monkeypatch):
    import io
    import urllib.error

    def http_error(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad", {}, io.BytesIO(b'{"error": "no such layer"}')
        )

    monkeypatch.setattr(ms.urllib.request, "urlopen", http_error)
    with pytest.raises(RuntimeError, match="rejected the scene .400.: no such layer"):
        ms._post_scene({"layers": []})
