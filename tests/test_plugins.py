"""Plugin API: dependency chains, live switches, server gating, plugin
sources and propagators.

Runs against fake plugins so the core's tests never need a real plugin
package installed.
"""

import functools
from datetime import datetime, timezone

import pytest
from flask import Blueprint, jsonify
from helpers import core_registry, write_pack

from mission_planner import Orbit
from mission_planner.plugins import API_VERSION, Registry, builtin_sources

EPOCH = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def src(spec, name=None, builtin=False):
    return (name or spec["name"], builtin, lambda: spec)


def reg_of(*specs):
    return Registry([src(s) for s in specs])


# ---------------------------------------------------------------- dependency chains


def test_missing_requirement_makes_plugin_unavailable():
    r = reg_of({"name": "a", "requires": ["ghost"]}).records["a"]
    assert r.status == "unavailable" and "'ghost', which is not installed" in r.error


def test_unavailability_propagates_down_a_chain_naming_the_link():
    reg = reg_of(
        {"name": "a", "requires": ["b"]},
        {"name": "b", "requires": ["c"]},
        {"name": "c", "available": lambda: "simulator not found"},
    )
    assert reg.records["c"].error == "simulator not found"
    assert reg.records["b"].status == "unavailable" and "'c'" in reg.records["b"].error
    assert reg.records["a"].status == "unavailable" and "'b'" in reg.records["a"].error
    assert not any(reg.active(n) for n in "abc")


def test_an_availability_check_that_raises_is_unavailable_not_fatal():
    r = reg_of({"name": "a", "available": lambda: 1 / 0}).records["a"]
    assert r.status == "unavailable" and "availability check raised ZeroDivisionError" in r.error


def test_cycle_fails_its_members():
    reg = reg_of({"name": "a", "requires": ["b"]}, {"name": "b", "requires": ["a"]})
    statuses = {reg.records[n].status for n in "ab"}
    assert "failed" in statuses and "loaded" not in statuses
    assert any("cycle" in (reg.records[n].error or "") for n in "ab")


@pytest.mark.parametrize(
    "spec, why",
    [
        ({"name": "a", "api": API_VERSION + 1}, "plugin API"),
        ({"name": "a", "api": 0}, "plugin API"),
        ({"name": "a", "api": True}, "plugin API"),  # a bool is an int to Python, not to us
        ({"name": "a", "requires": "b"}, "list of plugin names"),
        ({"title": "no name"}, "string 'name'"),
        ({"name": "a", "works_with": ["orbit", "boat"]}, "'works_with'"),
        ({"name": "a", "sources": {"site": {"fn": print, "kind": "orbit"}}}, "core: site/preset"),
        ({"name": "a", "sources": {"s": {"kind": "orbit"}}}, "callable 'fn'"),
        ({"name": "a", "sources": {"s": {"fn": print, "kind": "tle"}}}, "kind must be"),
        ({"name": "a", "sources": "oops"}, "'sources' must be a dict"),
        ({"name": "a", "propagators": "oops"}, "'propagators' must be a dict"),
        ({"name": "a", "propagators": {"m": {"label": "no fn"}}}, "callable 'fn'"),
        ({"name": "a", "propagators": {"kepler": {"fn": print}}}, "core: kepler/decay"),
        ({"name": "a", "catalog": 123}, "'catalog' must be a path"),
        ({"name": "a", "static_dir": 123}, "'static_dir' must be a path"),
        ({"name": "a", "blueprint": "notabp"}, "flask Blueprint"),
        ({"name": "a", "mcp_tools": [1]}, "'mcp_tools' must be a list of named functions"),
        (
            {"name": "a", "mcp_tools": [functools.partial(print, "x")]},  # callable, no __name__
            "'mcp_tools' must be a list of named functions",
        ),
        ({"name": "a", "available": "yes"}, "'available' must be a callable"),
        ({"name": "a", "title": 3}, "'title' must be a string"),
        ({"name": ""}, "non-empty string 'name'"),
    ],
)
def test_invalid_specs_fail(spec, why):
    (r,) = Registry([("a", False, lambda: spec)]).records.values()
    assert r.status == "failed" and why in r.error


def test_self_requirement_is_a_cycle_not_a_crash():
    r = reg_of({"name": "a", "requires": ["a"]}).records["a"]
    assert r.status == "failed" and "cycle: a -> a" in r.error


def test_every_member_of_a_long_cycle_fails_and_the_diamond_above_it_waits():
    reg = reg_of(
        {"name": "top", "requires": ["l", "r"]},
        {"name": "l", "requires": ["c1"]},
        {"name": "r", "requires": ["c1"]},
        {"name": "c1", "requires": ["c2"]},
        {"name": "c2", "requires": ["c3"]},
        {"name": "c3", "requires": ["c1"]},
    )
    for n in ("c1", "c2", "c3"):
        assert reg.records[n].status == "failed" and "cycle" in reg.records[n].error, n
    for n in ("l", "r", "top"):
        assert reg.records[n].status == "unavailable", n


def test_diamond_dependencies_resolve_and_switch_together():
    reg = reg_of(
        {"name": "top", "requires": ["l", "r"]},
        {"name": "l", "requires": ["base"]},
        {"name": "r", "requires": ["base"]},
        {"name": "base"},
    )
    assert all(reg.active(n) for n in ("top", "l", "r", "base"))
    reg.set_enabled("base", False)
    assert not any(reg.active(n) for n in ("top", "l", "r"))
    assert reg.waiting_on("top") == "l" and reg.waiting_on("l") == "base"
    reg.set_enabled("top", True)
    assert all(reg.active(n) for n in ("top", "l", "r", "base"))


def test_duplicate_names_each_get_their_own_failed_record():
    reg = reg_of({"name": "a", "title": "first"}, {"name": "a"}, {"name": "a"})
    assert reg.records["a"].status == "loaded" and reg.records["a"].get("title") == "first"
    dups = [r for r in reg.records.values() if r.name != "a"]
    assert [r.name for r in dups] == ["a#dup1", "a#dup2"]
    assert all(r.status == "failed" and "duplicate" in r.error for r in dups)


@pytest.mark.parametrize(
    "first, second, why",
    [
        (
            {"name": "p", "propagators": {"m": {"fn": print}}},
            {"name": "q", "propagators": {"m": {"fn": print}}},
            "mode 'm' is already provided by plugin 'p'",
        ),
        (
            {"name": "p", "sources": {"s": {"fn": print, "kind": "orbit"}}},
            {"name": "q", "sources": {"s": {"fn": print, "kind": "trajectory"}}},
            "source 's' is already provided by plugin 'p'",
        ),
        (
            {"name": "p", "blueprint": Blueprint("shared", __name__)},
            {"name": "q", "blueprint": Blueprint("shared", __name__)},
            "blueprint 'shared' is already provided by plugin 'p'",
        ),
        (
            {"name": "p", "mcp_tools": [print]},
            {"name": "q", "mcp_tools": [print]},
            "MCP tool 'print' is already provided by plugin 'p'",
        ),
    ],
)
def test_shared_ids_fail_the_later_plugin(first, second, why):
    reg = reg_of(first, second)
    assert reg.records["p"].status == "loaded"
    assert reg.records["q"].status == "failed" and reg.records["q"].error == why


def test_core_ids_cannot_be_claimed_by_a_plugin():
    def plan_orbit():
        pass

    def track_samples():
        pass

    reg = core_registry(
        {"name": "q", "mcp_tools": [plan_orbit]},
        {"name": "r", "blueprint": Blueprint("passes", __name__)},
        {"name": "s", "mcp_tools": [track_samples]},
    )
    assert "MCP tool 'plan_orbit' is already provided by core" == reg.records["q"].error
    assert "blueprint 'passes' is already provided by plugin 'passes'" == reg.records["r"].error
    assert "MCP tool 'track_samples' is already provided by core" == reg.records["s"].error


def test_env_disable_of_an_unknown_name_is_reported_not_fatal(monkeypatch, capsys):
    monkeypatch.setenv("MP_DISABLE_MODULES", "ghost,a")
    reg = reg_of({"name": "a"})
    assert not reg.records["a"].enabled
    assert "no plugin 'ghost'" in capsys.readouterr().err


def test_import_error_is_reported_not_raised():
    def boom():
        raise ModuleNotFoundError("No module named 'not_a_real_dependency_xyz'")

    r = Registry([("broken", False, boom)]).records["broken"]
    assert r.status == "failed" and "not_a_real_dependency_xyz" in r.error


def test_switches_cascade_up_and_dependents_wait():
    reg = reg_of({"name": "a", "requires": ["b"]}, {"name": "b"})
    reg.set_enabled("b", False)
    assert reg.records["a"].enabled and not reg.active("a")
    assert reg.waiting_on("a") == "b"
    reg.set_enabled("a", True)  # switching a dependent on switches its requirement on
    assert reg.records["b"].enabled and reg.active("a")


def test_builtins_cannot_be_switched_and_env_sets_starting_switches(monkeypatch):
    monkeypatch.setenv("MP_DISABLE_MODULES", "a")
    reg = Registry([src({"name": "a"}), src({"name": "core_thing"}, builtin=True)])
    assert not reg.records["a"].enabled
    with pytest.raises(ValueError, match="built in"):
        reg.set_enabled("core_thing", False)


def test_plugin_mode_dispatch_follows_the_switch():
    def fake(orbit, beta, duration_s, dt_s):
        return orbit.ground_track(duration_s, dt_s)

    reg = reg_of({"name": "sim", "propagators": {"fake": {"fn": fake}}})
    assert reg.propagator("fake")["fn"] is fake
    reg.set_enabled("sim", False)
    with pytest.raises(ValueError, match="plugin 'sim', which is switched off"):
        reg.propagator("fake")
    with pytest.raises(ValueError, match="unknown mode 'nope'"):
        reg.propagator("nope")


# ---------------------------------------------------------------- server over a fake registry

fake_bp = Blueprint("fakeplug", __name__)


@fake_bp.route("/api/fakeplug")
def _fake_route():
    return jsonify({"ok": True})


def _slow_mode(orbit, beta, duration_s, dt_s):
    return orbit.ground_track(duration_s, dt_s)


def _crashing_mode(orbit, beta, duration_s, dt_s):
    raise KeyError("state")  # the plugin's bug


def _picky_mode(orbit, beta, duration_s, dt_s):
    raise ValueError("beta too low for this mode")  # the user's input


def _orbit_source(a):
    """An orbit source: a circular orbit at the requested altitude."""
    return Orbit.circular(float(a.get("alt", 500.0)), 45.0, epoch=EPOCH), {"title": "fake orbit"}


def _track_source(a):
    """A finished trajectory: a straight line north from the equator."""
    import numpy as np

    from mission_planner.groundtrack import GroundTrack

    n = int(a.get("n", 11))
    gt = GroundTrack(
        epoch=datetime(2026, 8, 23),  # naive: UTC
        t=np.arange(n) * 10.0,
        lat=np.radians(np.linspace(0.0, 10.0, n)),
        lon=np.zeros(n),
        alt=np.linspace(100e3, 0.0, n),
    )
    return gt, {"title": "fake track"}


@pytest.fixture
def fake(app_with, tmp_path):
    specs = [
        {
            "name": "fakeplug",
            "title": "fake plugin",
            "blueprint": fake_bp,
            "js": "fake.js",
            "static_dir": tmp_path,
            "propagators": {
                "slowfake": {"fn": _slow_mode, "label": "slow fake", "slow": True},
                "crash": {"fn": _crashing_mode},
                "picky": {"fn": _picky_mode},
            },
            "sources": {
                "fakeorb": {"fn": _orbit_source, "label": "Fake orbit", "kind": "orbit"},
                "faketrack": {"fn": _track_source, "label": "Fake track", "kind": "trajectory"},
            },
        },
        {"name": "pack", "catalog": write_pack(tmp_path / "pack")},
        {"name": "needy", "requires": ["fakeplug"]},
    ]
    (tmp_path / "fake.js").write_text("MP.register({title: 'fake', html: '', init() {}});")
    return app_with(*specs)


QS = "site=Cape+Canaveral+%2F+KSC&hp=400&inc=51.6&hours=2&epoch=2026-08-23T00:00:00%2B00:00"


def test_modules_endpoint_lists_builtins_and_plugins(fake):
    client, _ = fake
    mods = {m["name"]: m for m in client.get("/api/modules").get_json()}
    assert mods["passes"]["builtin"] and mods["maneuvers"]["builtin"]
    f = mods["fakeplug"]
    assert not f["builtin"] and f["active"] and f["routes"]
    assert f["js_url"] == "/plugins/fakeplug/fake.js"
    assert f["modes"][0] == {
        "mode": "slowfake",
        "label": "slow fake",
        "needs_beta": False,
        "slow": True,
    }
    assert [m["mode"] for m in f["modes"]] == ["slowfake", "crash", "picky"]
    assert mods["pack"]["catalog"] and mods["needy"]["requires"] == ["fakeplug"]
    r = client.get("/plugins/fakeplug/fake.js")
    assert r.status_code == 200 and b"MP.register" in r.data


def test_switching_off_gates_routes_modes_and_dependents(fake):
    client, _ = fake
    assert client.get("/api/fakeplug").status_code == 200
    assert client.get(f"/api/plan?{QS}&mode=slowfake").status_code == 200
    mods = client.post("/api/modules/fakeplug", json={"enabled": False}).get_json()
    needy = next(m for m in mods if m["name"] == "needy")
    assert needy["enabled"] and not needy["active"] and needy["waiting_on"] == "fakeplug"
    assert client.get("/api/fakeplug").status_code == 404
    off = client.get(f"/api/plan?{QS}&mode=slowfake")
    assert off.status_code == 400 and "switched off" in off.get_json()["error"]
    assert client.get("/api/maneuvers/budget?alt1=300&inc1=28.5&alt2=400&inc2=0").status_code == 200
    client.post("/api/modules/needy", json={"enabled": True})  # cascades to fakeplug
    assert client.get("/api/fakeplug").status_code == 200


def test_a_crashing_propagator_is_a_500_naming_its_plugin_and_mode(fake):
    client, _ = fake
    r = client.get(f"/api/plan?{QS}&mode=crash")
    assert r.status_code == 500
    assert r.get_json()["error"] == (
        "PluginError: mode 'crash' (plugin 'fakeplug') failed: KeyError: 'state'"
    )
    # ... while a ValueError is the user's problem, a plain 400.
    r = client.get(f"/api/plan?{QS}&mode=picky")
    assert r.status_code == 400 and r.get_json()["error"] == "beta too low for this mode"


def test_nested_blueprint_routes_are_gated_too(app_with):
    parent = Blueprint("outer", __name__)
    child = Blueprint("inner", __name__, url_prefix="/inner")

    @child.route("/ping")
    def _ping():
        return jsonify({"ok": True})

    parent.register_blueprint(child)
    client, reg = app_with({"name": "nested", "blueprint": parent})
    assert client.get("/inner/ping").status_code == 200
    reg.set_enabled("nested", False)
    assert client.get("/inner/ping").status_code == 404


def test_unregistrable_blueprint_fails_its_plugin_and_its_dependents_not_the_server(app_with):
    class Broken:
        name = "broken"

        def register(self, app, options):
            raise RuntimeError("no routes for you")

    client, reg = app_with(
        {"name": "bad", "blueprint": Broken()}, {"name": "needs_bad", "requires": ["bad"]}
    )
    mods = {m["name"]: m for m in client.get("/api/modules").get_json()}
    assert mods["bad"]["status"] == "failed" and "no routes for you" in mods["bad"]["error"]
    # Failing after load re-resolves the chain: the dependent is unavailable,
    # not merely waiting, and can't be switched on.
    assert mods["needs_bad"]["status"] == "unavailable" and "'bad'" in mods["needs_bad"]["error"]
    assert not reg.active("needs_bad")
    r = client.post("/api/modules/needs_bad", json={"enabled": True})
    assert r.status_code == 409 and "unavailable" in r.get_json()["error"]


def test_toggle_rejects_bad_requests(fake):
    client, _ = fake
    assert client.post("/api/modules/nope", json={"enabled": False}).status_code == 404
    assert client.post("/api/modules/fakeplug", json={"enabled": "no"}).status_code == 400
    assert client.post("/api/modules/passes", json={"enabled": False}).status_code == 409


def test_slow_mode_runs_as_a_plan_job(fake, wait_job):
    client, _ = fake
    job = client.post(f"/api/plan_job?{QS}&mode=slowfake").get_json()
    res = wait_job(lambda: client.get(f"/api/plan_job/{job['job_id']}").get_json())
    assert res["status"] == "done" and len(res["track"]["lat"]) > 10
    assert res["args"]["mode"] == "slowfake"
    assert client.post(f"/api/plan_job?{QS}&mode=nope").status_code == 400


def test_orbit_ground_track_reaches_plugin_modes(fake):
    orb = Orbit.circular(400.0, 51.6, epoch=EPOCH)
    gt = orb.ground_track(3600.0, 60.0, mode="slowfake")
    assert len(gt.lat) == 61 and gt.t[-1] == 3600.0


# ---------------------------------------------------------------- trajectory sources


def test_modules_endpoint_lists_sources_and_what_modules_work_with(fake):
    client, _ = fake
    mods = {m["name"]: m for m in client.get("/api/modules").get_json()}
    assert mods["fakeplug"]["sources"] == [
        {"id": "fakeorb", "label": "Fake orbit", "kind": "orbit", "slow": False},
        {"id": "faketrack", "label": "Fake track", "kind": "trajectory", "slow": False},
    ]
    assert mods["passes"]["works_with"] == ["orbit", "trajectory"]
    assert mods["maneuvers"]["works_with"] == ["orbit"]  # the default


def test_orbit_source_is_propagated_like_a_core_orbit(fake):
    client, _ = fake
    res = client.get("/api/plan?source=fakeorb&alt=600&hours=1&dt=60&mode=slowfake").get_json()
    s = res["summary"]
    assert s["source"] == "fakeorb" and s["kind"] == "orbit" and s["title"] == "fake orbit"
    assert round(s["alt_km"]) == 600 and len(res["track"]["t"]) == 61


def test_trajectory_source_comes_finished(fake):
    client, _ = fake
    res = client.get("/api/plan?source=faketrack&n=21&hours=99&mode=nope").get_json()
    assert res["summary"] == {"source": "faketrack", "kind": "trajectory", "title": "fake track"}
    assert len(res["track"]["lat"]) == 21 and "apsides" not in res["track"]
    assert res["track"]["epoch_utc"] == "2026-08-23T00:00:00+00:00"  # the naive epoch, as UTC
    # modules that only need a track work on it ...
    win = client.get("/api/passes?source=faketrack&tgt_lat=5&tgt_lon=0&within_km=50").get_json()
    assert win["n"] == 1
    # ... and anything asking it for an orbit gets a reason, not a crash
    from mission_planner.planning import orbit_from_args

    with pytest.raises(ValueError, match="finished trajectory, not an orbit"):
        orbit_from_args({"source": "faketrack"})


def test_sources_follow_the_switch(fake):
    client, _ = fake
    client.post("/api/modules/fakeplug", json={"enabled": False})
    off = client.get("/api/plan?source=faketrack")
    assert off.status_code == 400 and "switched off" in off.get_json()["error"]
    assert client.post("/api/plan_job?source=faketrack").status_code == 400
    unknown = client.get("/api/plan?source=nope").get_json()["error"]
    assert "unknown source 'nope'" in unknown and "site|preset" in unknown


def test_trajectory_source_runs_as_a_plan_job_without_a_mode(fake, wait_job):
    client, _ = fake
    job = client.post("/api/plan_job?source=faketrack&mode=nope").get_json()
    res = wait_job(lambda: client.get(f"/api/plan_job/{job['job_id']}").get_json())
    assert res["status"] == "done" and res["summary"]["kind"] == "trajectory"


def test_builtin_sources_are_the_modules_package_only():
    names = {name for name, builtin, _ in builtin_sources()}
    assert {"passes", "maneuvers", "decay", "files", "sso"} <= names
    assert all(builtin for _, builtin, _ in builtin_sources())


def test_a_helper_file_without_a_spec_is_not_a_module():
    reg = Registry([("helper", True, lambda: None), src({"name": "a"})])
    assert list(reg.records) == ["a"]
    assert reg.owner_of("sources", "nope") is None and reg.static_dir("nope") is None
