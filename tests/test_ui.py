"""UI smoke tests: the web app served for real, driven in headless Chromium.

They catch what the Python suite can't — a script that throws, a layer that
stops drawing, a panel that won't open, a module rule that stops firing — not
pixel-level changes.  Skipped without the `playwright` package and its browser
(`python -m playwright install chromium`); `-m "not ui"` leaves them out.
"""

import threading

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from helpers import PAIR_BODY, TOY, TOY_PAIR  # noqa: E402
from mp_groundstation import MODULE as GROUNDSTATION  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

import mission_planner.plugins as plugins  # noqa: E402
import mission_planner.server as server  # noqa: E402
from mission_planner.plugins import Registry, builtin_sources  # noqa: E402

pytestmark = pytest.mark.ui

EPOCH = "2026-10-01T12:00"
GREEN = "#1baf7a"  # C.green: the ground station's ring
NIGHT = "#1c2733"  # the night-side shade


@pytest.fixture(scope="module")
def base_url():
    """The app over the built-ins, the ground-station example and the toy
    file readers (never the installed plugins), on a free port: never the
    user's :3030."""
    with pytest.MonkeyPatch.context() as mp:
        reg = Registry(
            [
                *builtin_sources(),
                ("groundstation", False, lambda: GROUNDSTATION),
                ("toy", False, lambda: TOY),
                ("toypair", False, lambda: TOY_PAIR),
            ]
        )
        mp.setattr(plugins, "_REGISTRY", reg)
        srv = make_server("127.0.0.1", 0, server.create_app(), threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{srv.server_port}"
        srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # the package without its browser
            pytest.skip(f"no Chromium for playwright ({e.__class__.__name__})")
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    """A loaded page whose script errors, console errors and failed requests
    fail the test at teardown."""
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)
    pg = ctx.new_page()
    problems = []
    pg.on("pageerror", lambda e: problems.append(f"script error: {e}"))
    pg.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    pg.on("response", lambda r: r.status >= 400 and problems.append(f"{r.status} {r.url}"))
    pg.goto(base_url)
    # Module scripts are appended dynamically and run in load order: wait
    # until every one has registered (or failed), not just for the inventory.
    pg.wait_for_function(
        "() => MP.mods.groundstation && Object.values(MP.mods)"
        ".every(m => !m.js_url || m.box || m.jsError)"
    )
    yield pg
    ctx.close()
    assert not problems, problems


def plan(page, **fields):
    """Fill the orbit form and plan; returns the number of track samples."""
    page.fill("#epoch", EPOCH)
    for sel, value in fields.items():
        page.fill(f"#{sel}", str(value))
    page.evaluate("() => { plan = null; }")
    page.click("#plan")
    page.wait_for_function("() => plan && plan.track.t.length > 1")
    return page.evaluate("() => plan.track.t.length")


def count(page, selector):
    return page.evaluate(f"() => document.querySelectorAll({selector!r}).length")


def drawn(page):
    """How many shapes the main pane holds (the coastline alone is many)."""
    return count(page, "#map path, #map polyline")


def track_drawn(page):
    """The ground track in focus: the emphasised current revolution (map.js)."""
    return count(page, '#map [stroke-width="2.2"]')


def test_page_loads_with_every_module_and_the_example_plugin(page):
    mods = page.evaluate(
        "() => Object.fromEntries(Object.values(MP.mods).map(m => [m.name, m.status]))"
    )
    assert {"passes", "maneuvers", "decay", "files", "sso", "groundstation"} <= set(mods)
    assert set(mods.values()) == {"loaded"}
    # Every module that ships a script registered a panel, without a JS error.
    unregistered = page.evaluate(
        "() => Object.values(MP.mods).filter(m => m.jsError || (m.js_url && !m.box))"
        ".map(m => m.name + ': ' + (m.jsError || 'no panel registered'))"
    )
    assert unregistered == []
    # Nothing to play yet: the button does nothing rather than run a dead loop.
    page.click("#play")
    assert page.evaluate("() => !playing && tCur === 0")


def test_a_plan_draws_in_every_view(page):
    base = drawn(page)
    assert base > 0 and track_drawn(page) == 0  # the coastline, no track yet
    assert plan(page) > 100
    assert drawn(page) > base  # the track, its markers, the footprint
    for mode in ("map", "globe", "orbit"):
        page.evaluate(f"() => setProj('{mode}')")
        assert track_drawn(page) > 0, mode
    # The side panel describes the plan: the site block and the elements.
    assert "Cape Canaveral / KSC" in page.inner_text("#summary")
    elements = page.inner_text("#elements")
    assert "i\t51.6°" in elements and "e\t0.00000" in elements and " min" in elements


def test_every_module_panel_opens_and_the_station_draws(page):
    plan(page)
    for box in page.query_selector_all("details.modbox"):
        box.evaluate("b => { b.open = true; b.dispatchEvent(new Event('toggle')); }")
    page.evaluate("() => redraw()")
    assert track_drawn(page) > 0
    # A typed-in station puts its mask ring on the map (the plugin's onDraw).
    rings = lambda: count(page, f'#map polygon[fill="{GREEN}"]')  # noqa: E731
    assert rings() == 0
    page.fill("#gs_lat", "40")
    page.fill("#gs_lon", "-105")
    page.dispatch_event("#gs_lon", "change")
    assert rings() > 0
    page.wait_for_function(
        "() => /contact|no contacts/.test(document.getElementById('gs_cov').textContent)"
    )
    page.click("#gs_clear")
    assert rings() == 0


def test_elliptic_decay_draws_the_perigee_apogee_band(page):
    page.select_option("#mode", "decay")
    plan(page, peri=160, apo=600, hours=240)
    assert page.evaluate("() => plan.track.decay_profile.apogee_km.length") > 10
    assert page.query_selector("#dc_spark polygon") is not None


def test_sun_synchronous_preset_follows_the_altitude_and_the_ltan(page):
    page.fill("#epoch", EPOCH)  # 12:00 UTC: the mean sun is over 0 deg E
    page.evaluate("() => setSource('preset')")
    page.select_option("#preset", "Sun-synchronous")
    assert not page.evaluate("() => document.getElementById('sso_rows').hidden")
    assert float(page.input_value("#peri")) == 700 and float(page.input_value("#inc")) == 98.19
    assert page.input_value("#nodelon") == "-22.5"  # LTAN 10.5 h, 12 UTC
    page.fill("#sso_ltan", "6")
    page.dispatch_event("#sso_ltan", "input")
    assert page.input_value("#nodelon") == "-90.0" and float(page.input_value("#inc")) == 98.19
    # A repeat-track variant moves the altitude, and the inclination with it.
    page.select_option("#sso_variant", "0")
    peri, inc = float(page.input_value("#peri")), float(page.input_value("#inc"))
    assert 150 < peri < 700 and 96 < inc < 98.19 and page.input_value("#apo") == ""
    # Another preset switches the rules off.
    page.select_option("#preset", "ISS")
    assert page.evaluate("() => document.getElementById('sso_rows').hidden")
    assert float(page.input_value("#inc")) == 51.6


def upload(page, body: bytes, name: str) -> str:
    return page.evaluate(
        """async ([text, name]) => {
            const fd = new FormData();
            fd.append("file", new Blob([text]), name);
            const r = await fetch("/api/uploads", { method: "POST", body: fd });
            return (await r.json()).id;
        }""",
        [body.decode(), name],
    )


def test_a_trajectory_plan_makes_orbit_only_modules_inert(page):
    plan(page)
    assert not page.evaluate("() => MP.mods.maneuvers.box.hidden")
    uid = upload(page, PAIR_BODY, "pair.txt")
    page.evaluate(f"() => openFile('{uid}', {{plan: true}})")
    page.wait_for_function("() => plan && plan.summary.kind === 'trajectory'")
    assert page.evaluate("() => plan.tracks.length === 2 && plan.track.id === 'b'")
    hidden = page.evaluate(
        "() => Object.fromEntries(Object.values(MP.mods).filter(m => m.box).map(m => [m.name, m.box.hidden]))"
    )
    assert hidden["maneuvers"] and not hidden["passes"] and not hidden["groundstation"]
    assert page.evaluate("() => MP.on('passes') && !MP.on('maneuvers')")
    assert track_drawn(page) > 0
    # A focused track that lies outside the display window draws nothing, quietly.
    page.evaluate("() => { setWindow(0.75, 1); setFocus('a'); redraw(); }")
    assert page.evaluate("() => plan.track.id === 'a'") and track_drawn(page) == 0
    page.evaluate("() => { setWindow(0, 1); redraw(); }")
    assert track_drawn(page) > 0


def test_camera_views_and_screenshot(page, browser):
    plan(page)
    for cam in page.query_selector_all("#camerabar button[data-cam]"):
        cam.click()
        assert track_drawn(page) > 0, cam.get_attribute("data-cam")
    # From the sun the whole disc is lit: no night shade at all.
    page.click('#camerabar button[data-cam="sun"]')
    assert count(page, f'#map [fill="{NIGHT}"]') == 0
    page.check("#camfollow")
    page.evaluate("() => { tCur = plan.track.t[40]; redraw(); }")
    page.click("#camshot")
    page.wait_for_function("() => /screenshot/.test(document.getElementById('status').textContent)")
    kind = page.evaluate(
        "async () => (await navigator.clipboard.read()).flatMap(i => i.types).join(',')"
    )
    assert "image/png" in kind


def test_map_gestures_pan_zoom_pinch_tap_and_labels(page):
    """The map's pointer handling: one pointer pans, a wheel and two fingers
    zoom, a tap is a map click, a double click resets -- mouse or touch."""
    plan(page)
    box = page.locator("#map").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    view = lambda: page.evaluate("() => [lonC, view.w]")  # noqa: E731
    lon0, w0 = view()
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 120, cy, steps=4)
    page.mouse.up()
    assert view()[0] != lon0 and view()[1] == w0  # panned, not zoomed
    page.mouse.wheel(0, -120)
    assert view()[1] < w0
    page.dblclick("#map")
    assert view()[1] == w0
    # Two touch pointers moving apart zoom in; the browser's own gestures are
    # off (touch-action: none), so the page handles them.
    page.evaluate(
        """([cx, cy]) => {
            const svg = document.getElementById("map");
            const ev = (type, id, x, y, target) => target.dispatchEvent(new PointerEvent(type,
                { pointerId: id, pointerType: "touch", clientX: x, clientY: y, bubbles: true }));
            ev("pointerdown", 1, cx - 50, cy, svg);
            ev("pointerdown", 2, cx + 50, cy, svg);
            ev("pointermove", 2, cx + 150, cy, window);
            ev("pointerup", 1, cx - 50, cy, window);
            ev("pointerup", 2, cx + 150, cy, window);
        }""",
        [cx, cy],
    )
    assert view()[1] < w0
    # A tap (no movement) is a map click for the modules.
    page.evaluate(
        """([cx, cy]) => {
            window._tap = null;
            MP._clicks.push({ mod: "passes", fn: (lat, lon) => { window._tap = [lat, lon]; } });
            const svg = document.getElementById("map");
            const ev = (type, target) => target.dispatchEvent(new PointerEvent(type,
                { pointerId: 3, pointerType: "touch", clientX: cx, clientY: cy, bubbles: true }));
            ev("pointerdown", svg);
            ev("pointerup", window);
        }""",
        [cx, cy],
    )
    tap = page.evaluate("() => window._tap")
    assert tap is not None and abs(tap[0]) <= 90 and abs(tap[1]) <= 180
    # The timeline's controls say what they are to a screen reader.
    for sel in ("#play", "#scrub", "#win0", "#win1"):
        assert page.get_attribute(sel, "aria-label")
