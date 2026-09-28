"""Built-in modules: always active, served like plugins."""

import mission_planner.server as server
from mission_planner.plugins import registry


def test_builtins_are_loaded_and_always_active():
    reg = registry()
    for name in ("passes", "maneuvers"):
        assert reg.records[name].builtin and reg.active(name)


def test_budget_endpoint():
    res = server.app.test_client().get(
        "/api/maneuvers/budget?alt1=300&inc1=28.5&alt2=35786&inc2=0&lead="
    )
    b = res.get_json()
    assert res.status_code == 200
    assert abs(b["hohmann"]["dv_total_ms"] - 3893) < 40
    assert "phasing" not in b


def test_module_js_served():
    res = server.app.test_client().get("/plugins/maneuvers/maneuvers.js")
    assert res.status_code == 200
    assert b"MP.register" in res.data
