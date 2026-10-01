"""Target-pass module: the capability is the module's, not the core's."""

import io

from helpers import PAIR_BODY, TOY_PAIR

from mission_planner.modules.passes import find_passes

QS = "site=Cape+Canaveral+%2F+KSC&hp=400&inc=51.6&hours=24&epoch=2026-08-23T00:00:00%2B00:00"
FIELDS = {"aos_utc", "los_utc", "ca_utc", "ca_t_s", "min_dist_km", "direction", "alt_km"}


def test_module_serves_the_passes_endpoint(core_client):
    r = core_client.get(f"/api/passes?{QS}&tgt_lat=28.5&tgt_lon=-80.6&within_km=800")
    assert r.status_code == 200
    body = r.get_json()
    assert body["n"] == len(body["passes"]) > 0
    p = body["passes"][0]
    assert FIELDS <= set(p) and "track" not in p  # one track: no track tag
    assert p["min_dist_km"] <= 800.0


def test_passes_endpoint_needs_a_numeric_target(core_client):
    r = core_client.get(f"/api/passes?{QS}")
    assert r.status_code == 400 and "tgt_lat" in r.get_json()["error"]
    r = core_client.get(f"/api/passes?{QS}&tgt_lat=x&tgt_lon=0")
    assert r.status_code == 400 and "tgt_lat must be a number" in r.get_json()["error"]


def test_endpoint_is_registered_by_the_module_blueprint(core_client):
    """It must come from the module's blueprint, so disabling the module
    takes the route with it."""
    rule = next(r for r in core_client.application.url_map.iter_rules() if str(r) == "/api/passes")
    assert rule.endpoint.startswith("passes.")


def test_mcp_tool_matches_the_endpoint(core_client):
    res = core_client.get(f"/api/passes?{QS}&tgt_lat=28.5&tgt_lon=-80.6&within_km=800").get_json()
    tool = find_passes(
        28.5,
        -80.6,
        site="Cape Canaveral / KSC",
        alt_km=400.0,
        inc_deg=51.6,
        epoch_utc="2026-08-23T00:00:00+00:00",
        hours=24.0,
        within_km=800.0,
    )
    assert tool["n"] == res["n"]
    assert [p["ca_utc"][:16] for p in tool["passes"]] == [p["ca_utc"][:16] for p in res["passes"]]


def test_mcp_tool_takes_element_anchored_orbits():
    out = find_passes(0.0, 65.0, site="", node_lon_deg=65.0, alt_km=400.0, inc_deg=51.6, hours=2)
    assert out["n"] >= 1 and out["passes"][0]["min_dist_km"] < 50.0


def test_passes_of_a_multi_track_plan_are_tagged_and_on_one_clock(app_with):
    c, _ = app_with(TOY_PAIR)
    up = c.post("/api/uploads", data={"file": (io.BytesIO(PAIR_BODY), "pair.txt")}).get_json()
    # Both tracks run (10, 20) -> (11, 21); the target sits between the samples.
    r = c.get(f"/api/passes?source=file&upload={up['id']}&tgt_lat=10.5&tgt_lon=20.5&within_km=100")
    assert r.status_code == 200
    win = r.get_json()["passes"]
    assert [(p["track"], p["label"]) for p in win] == [("a", "Alpha"), ("b", "Bravo")]
    assert win[1]["ca_t_s"] - win[0]["ca_t_s"] == 60.0  # track b's epoch is a minute later
    assert win[1]["ca_utc"] > win[0]["ca_utc"] and FIELDS <= set(win[0])
