"""Built-in modules: always active, served like plugins."""

from mission_planner.plugins import CORE_MCP_TOOLS

BUILTINS = ("passes", "maneuvers", "decay")


def test_builtins_are_loaded_and_always_active(core_reg):
    for name in BUILTINS:
        rec = core_reg.records[name]
        assert rec.builtin and rec.status == "loaded" and core_reg.active(name)


def test_builtin_tool_names_are_distinct_from_the_core_tools(core_reg):
    names = [fn.__name__ for r in core_reg.records.values() for fn in r.get("mcp_tools", [])]
    assert len(names) == len(set(names)) and not set(names) & set(CORE_MCP_TOOLS)


def test_budget_endpoint(core_client):
    res = core_client.get("/api/maneuvers/budget?alt1=300&inc1=28.5&alt2=35786&inc2=0&lead=")
    b = res.get_json()
    assert res.status_code == 200
    assert abs(b["hohmann"]["dv_total_ms"] - 3893) < 40
    assert "phasing" not in b


def test_budget_endpoint_rejects_an_impossible_phasing(core_client):
    res = core_client.get("/api/maneuvers/budget?alt1=400&inc1=0&alt2=400&inc2=0&lead=360")
    assert res.status_code == 400 and "lead_deg" in res.get_json()["error"]


def test_module_js_served(core_client):
    for name in BUILTINS:
        res = core_client.get(f"/plugins/{name}/{name}.js")
        assert res.status_code == 200, name
        assert b"MP.register" in res.data
