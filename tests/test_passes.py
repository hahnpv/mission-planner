"""Target-pass module: the capability is the module's, not the core's."""

import mission_planner.server as server

QS = "site=Cape+Canaveral+%2F+KSC&hp=400&inc=51.6&hours=24&epoch=2026-08-23T00:00:00%2B00:00"


def test_module_is_listed_as_builtin():
    mods = {m["name"]: m for m in server.app.test_client().get("/api/modules").get_json()}
    assert mods["passes"]["builtin"] and mods["passes"]["js_url"] == "/plugins/passes/passes.js"


def test_module_serves_the_passes_endpoint():
    """/api/passes keeps its URL; it is now the module's blueprint."""
    r = server.app.test_client().get(f"/api/passes?{QS}&tgt_lat=28.5&tgt_lon=-80.6&within_km=800")
    assert r.status_code == 200
    body = r.get_json()
    assert body["n"] == len(body["passes"]) > 0
    p = body["passes"][0]
    assert {"aos_utc", "los_utc", "ca_utc", "ca_t_s", "min_dist_km", "direction", "alt_km"} <= set(
        p
    )
    assert p["min_dist_km"] <= 800.0


def test_passes_endpoint_needs_a_target():
    r = server.app.test_client().get(f"/api/passes?{QS}")
    assert r.status_code == 400


def test_endpoint_is_not_registered_by_the_core():
    """It must come from the module's blueprint, so disabling the module
    takes the route with it."""
    rule = next(r for r in server.app.url_map.iter_rules() if str(r) == "/api/passes")
    assert rule.endpoint.startswith("passes.")


def test_panel_js_served():
    res = server.app.test_client().get("/static/modules/passes.js")
    assert res.status_code == 200
    assert b"MP.register" in res.data
    # Map click and map graphics are the module's, and both gate on isOpen.
    assert b"ctx.onClick" in res.data and b"ctx.onDrawOver" in res.data
    assert res.data.count(b"ctx.isOpen()") >= 3


def test_core_ui_no_longer_owns_the_target():
    """The core keeps the hooks (onClick / seek / onDrawOver) but none of the
    pass-search UI — that all moved into the module."""
    html = (server.app.test_client().get("/").data).decode()
    for gone in ('id="passtable"', 'id="tgt"', "doPasses", "setTarget("):
        assert gone not in html, gone
    for hook in ("onClick:", "onDrawOver:", "seek:", "function seekTo"):
        assert hook in html, hook


def test_core_markers_are_clickable_entities():
    """Every marker carries an info payload and goes through pinGroup, which
    wraps it in a click-to-toggle group with its own hit target."""
    html = server.app.test_client().get("/").data.decode()
    for piece in (
        "function fpaDeg(",
        "function pinGroup(",
        "function drawPin(",
        'r:11, fill:"transparent"',
        "pinOpen = pinOpen === info.key",
    ):
        assert piece in html, piece
    for key in (
        'key:"site"',
        'key:"sat"',
        'key:"apsis:"',
        'key:"entry"',
        'key:"impact"',
        'key:"scene:"',
    ):
        assert key in html, key
    # A marker press must not also read as a map pan or a map click.
    assert 'g.addEventListener("mousedown", ev => ev.stopPropagation());' in html


def test_module_markers_carry_gamma():
    body = server.app.test_client().get("/plugins/passes/passes.js").data.decode()
    for k in ('key:"pa:target"', 'key:"pa:ca"'):
        assert k in body, k
    assert "d.fpa(" in body
