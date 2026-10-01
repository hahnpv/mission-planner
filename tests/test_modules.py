"""Built-in modules: always active, served like plugins."""

from mission_planner.plugins import CORE_MCP_TOOLS

BUILTINS = ("passes", "maneuvers", "decay", "files", "sso", "kml")


def test_builtins_are_loaded_and_always_active(core_reg):
    for name in BUILTINS:
        rec = core_reg.records[name]
        assert rec.builtin and rec.status == "loaded" and core_reg.active(name)


def test_builtin_tool_names_are_distinct_from_the_core_tools(core_reg):
    names = [fn.__name__ for r in core_reg.records.values() for fn in r.get("mcp_tools", [])]
    assert len(names) == len(set(names)) and not set(names) & set(CORE_MCP_TOOLS)


def test_builtins_are_listed_with_what_they_add(core_client):
    mods = {m["name"]: m for m in core_client.get("/api/modules").get_json()}
    assert set(BUILTINS) <= set(mods) and all(mods[n]["builtin"] for n in BUILTINS)
    passes = mods["passes"]
    assert passes["js_url"] == "/plugins/passes/passes.js" and passes["routes"]
    assert passes["mcp_tools"] == ["find_passes"]
    assert passes["works_with"] == ["orbit", "trajectory"]
    assert mods["maneuvers"]["mcp_tools"] == ["maneuver_budget"]
    assert (
        mods["files"]["mcp_tools"] == ["load_file"] and mods["files"]["sources"][0]["id"] == "file"
    )
    assert mods["sso"]["js_url"] == "/plugins/sso/sso.js" and not mods["sso"]["routes"]
    assert mods["kml"]["file_readers"] == [{"id": "kml", "label": "KML track"}]


def test_budget_endpoint(core_client):
    res = core_client.get("/api/maneuvers/budget?alt1=300&inc1=28.5&alt2=35786&inc2=0&lead=")
    b = res.get_json()
    assert res.status_code == 200
    assert abs(b["hohmann"]["dv_total_ms"] - 3893) < 40
    assert "phasing" not in b


def test_budget_endpoint_rejects_bad_input(core_client):
    res = core_client.get("/api/maneuvers/budget?alt1=400&inc1=0&alt2=400&inc2=0&lead=360")
    assert res.status_code == 400 and "lead_deg" in res.get_json()["error"]
    res = core_client.get("/api/maneuvers/budget?alt1=abc")
    assert res.status_code == 400 and "alt1 must be a number" in res.get_json()["error"]


def test_module_js_served(core_reg, core_client):
    with_js = [n for n in BUILTINS if core_reg.records[n].get("js")]
    assert with_js == [n for n in BUILTINS if n != "kml"]  # a reader-only module needs no UI code
    for name in with_js:
        res = core_client.get(f"/plugins/{name}/{core_reg.records[name].get('js')}")
        assert res.status_code == 200, name
        assert b"MP.register" in res.data
