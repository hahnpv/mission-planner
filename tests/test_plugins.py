"""Plugin API: dependency chains, live switches, catalog packs, server gating.

Runs against fake plugins so the core's tests never need a real plugin
package installed.
"""

import textwrap

import pytest
from flask import Blueprint, jsonify

import mission_planner.plugins as plugins
import mission_planner.server as server
from mission_planner import SITES, Orbit
from mission_planner.catalog import merged
from mission_planner.plugins import API_VERSION, CORE_CATALOG, Registry, builtin_sources


def src(spec, name=None, builtin=False):
    return (name or spec["name"], builtin, lambda: spec)


def reg_of(*specs, **kw):
    return Registry([src(s) for s in specs], **kw)


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


def test_cycle_fails_its_members():
    reg = reg_of({"name": "a", "requires": ["b"]}, {"name": "b", "requires": ["a"]})
    statuses = {reg.records[n].status for n in "ab"}
    assert "failed" in statuses and "loaded" not in statuses
    assert any("cycle" in (reg.records[n].error or "") for n in "ab")


@pytest.mark.parametrize(
    "spec, why",
    [
        ({"name": "a", "api": API_VERSION + 1}, "plugin API"),
        ({"name": "a", "requires": "b"}, "list of plugin names"),
        ({"title": "no name"}, "string 'name'"),
    ],
)
def test_invalid_specs_fail(spec, why):
    (r,) = Registry([("a", False, lambda: spec)]).records.values()
    assert r.status == "failed" and why in r.error


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


# ---------------------------------------------------------------- catalog


def test_core_catalog_is_generic():
    cat = merged([("core", CORE_CATALOG)])
    assert "Cape Canaveral / KSC" in [s["name"] for s in cat["sites"]]
    assert {p["name"] for p in cat["presets"]} >= {"ISS", "GEO", "Molniya", "Sun-synchronous"}
    assert cat["overlays"] == []  # overlays come from data packs


def write_pack(path):
    (path / "overlays").mkdir(parents=True)
    (path / "sites.yaml").write_text(
        "- {name: Test Range, lat: 22.0, lon: -159.8}\n- {name: Kodiak, lat: 57.5, lon: -152.0}\n"
    )
    (path / "overlays" / "box.geojson").write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},'
        ' "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}}]}'
    )
    (path / "overlays" / "box.yaml").write_text(
        textwrap.dedent("""\
            title: A box
            style: {color: "#123456", opacity: 0.2}
            source: {dataset: unit test}
        """)
    )
    return path


def test_packs_merge_override_and_carry_overlay_sidecars(tmp_path):
    cat = merged([("core", CORE_CATALOG), ("pk", write_pack(tmp_path))])
    sites = {s["name"]: s for s in cat["sites"]}
    assert sites["Test Range"]["pack"] == "pk"
    assert sites["Kodiak"]["lat"] == 57.5 and sites["Kodiak"]["pack"] == "pk"  # later wins
    (ov,) = cat["overlays"]
    assert ov["name"] == "A box" and ov["style"]["color"] == "#123456" and ov["pack"] == "pk"


# ---------------------------------------------------------------- server over a fake registry

fake_bp = Blueprint("fakeplug", __name__)


@fake_bp.route("/api/fakeplug")
def _fake_route():
    return jsonify({"ok": True})


def _slow_mode(orbit, beta, duration_s, dt_s):
    return orbit.ground_track(duration_s, dt_s)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    specs = [
        {
            "name": "fakeplug",
            "title": "fake plugin",
            "blueprint": fake_bp,
            "js": "fake.js",
            "static_dir": tmp_path,
            "propagators": {"slowfake": {"fn": _slow_mode, "label": "slow fake", "slow": True}},
        },
        {"name": "pack", "catalog": write_pack(tmp_path / "pack")},
        {"name": "needy", "requires": ["fakeplug"]},
    ]
    (tmp_path / "fake.js").write_text("MP.register({title: 'fake', html: '', init() {}});")
    reg = Registry([*builtin_sources(), *(src(s) for s in specs)])
    monkeypatch.setattr(plugins, "_REGISTRY", reg)
    return server.create_app().test_client(), reg


QS = "site=Cape+Canaveral+%2F+KSC&hp=400&inc=51.6&hours=2&epoch=2026-08-23T00:00:00%2B00:00"


def test_modules_endpoint_lists_builtins_and_plugins(fake):
    client, _ = fake
    mods = {m["name"]: m for m in client.get("/api/modules").get_json()}
    assert mods["passes"]["builtin"] and mods["maneuvers"]["builtin"]
    f = mods["fakeplug"]
    assert not f["builtin"] and f["active"] and f["routes"]
    assert f["js_url"] == "/plugins/fakeplug/fake.js"
    assert f["modes"] == [
        {"mode": "slowfake", "label": "slow fake", "needs_beta": False, "slow": True}
    ]
    assert mods["pack"]["catalog"] and mods["needy"]["requires"] == ["fakeplug"]
    assert client.get("/plugins/fakeplug/fake.js").status_code == 200


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


def test_toggle_rejects_bad_requests(fake):
    client, _ = fake
    assert client.post("/api/modules/nope", json={"enabled": False}).status_code == 404
    assert client.post("/api/modules/fakeplug", json={"enabled": "no"}).status_code == 400
    assert client.post("/api/modules/passes", json={"enabled": False}).status_code == 409


def test_data_pack_switches_the_catalog(fake):
    client, _ = fake
    names = lambda: [s["name"] for s in client.get("/api/sites").get_json()]  # noqa: E731
    assert "Test Range" in names() and "Test Range" in SITES
    assert [o["name"] for o in client.get("/api/overlays").get_json()] == ["A box"]
    client.post("/api/modules/pack", json={"enabled": False})
    assert "Test Range" not in names() and "Test Range" not in SITES
    assert client.get("/api/overlays").get_json() == []


def test_slow_mode_runs_as_a_plan_job(fake):
    import time

    client, _ = fake
    job = client.post(f"/api/plan_job?{QS}&mode=slowfake").get_json()
    for _ in range(100):
        res = client.get(f"/api/plan_job/{job['job_id']}").get_json()
        if res["status"] != "running":
            break
        time.sleep(0.05)
    assert res["status"] == "done" and len(res["track"]["lat"]) > 10
    assert client.post(f"/api/plan_job?{QS}&mode=nope").status_code == 400


def test_orbit_ground_track_reaches_plugin_modes(fake):
    orb = Orbit.circular(400.0, 51.6)
    assert len(orb.ground_track(3600.0, 60.0, mode="slowfake").lat) == 61
