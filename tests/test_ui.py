"""UI smoke tests: the web app served for real, driven in headless Chromium.

They catch what the Python suite can't — a script that throws, a layer that
stops drawing, a panel that won't open — not pixel-level changes.  Skipped
without the `playwright` package and its browser
(`python -m playwright install chromium`); `-m "not ui"` leaves them out.
"""

import threading

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from mp_groundstation import MODULE as GROUNDSTATION  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

import mission_planner.plugins as plugins  # noqa: E402
import mission_planner.server as server  # noqa: E402
from mission_planner.plugins import Registry, builtin_sources  # noqa: E402

pytestmark = pytest.mark.ui

EPOCH = "2026-10-01T12:00"


@pytest.fixture(scope="module")
def base_url():
    """The app over the built-ins and the ground-station example (never the
    installed plugins), on a free port: never the user's :3030."""
    with pytest.MonkeyPatch.context() as mp:
        reg = Registry([*builtin_sources(), ("groundstation", False, lambda: GROUNDSTATION)])
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
    pg.wait_for_function("() => MP.mods.groundstation && MP.mods.passes")
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


def drawn(page):
    """How many shapes the main pane holds."""
    return page.evaluate("() => document.querySelectorAll('#map path, #map polyline').length")


def test_page_loads_with_every_module_and_the_example_plugin(page):
    mods = page.evaluate(
        "() => Object.fromEntries(Object.values(MP.mods).map(m => [m.name, m.status]))"
    )
    assert {"passes", "maneuvers", "decay", "files", "sso", "groundstation"} <= set(mods)
    assert set(mods.values()) == {"loaded"}


def test_a_plan_draws_in_every_view(page):
    assert plan(page) > 100
    for mode in ("map", "globe", "orbit"):
        page.evaluate(f"() => setProj('{mode}')")
        assert drawn(page) > 0, mode
    assert page.inner_text("#summary")


def test_every_module_panel_opens(page):
    plan(page)
    for box in page.query_selector_all("details.modbox"):
        box.evaluate("b => { b.open = true; b.dispatchEvent(new Event('toggle')); }")
    page.evaluate("() => redraw()")
    assert drawn(page) > 0


def test_elliptic_decay_draws_the_perigee_apogee_band(page):
    page.select_option("#mode", "decay")
    plan(page, peri=160, apo=600, hours=240)
    assert page.evaluate("() => plan.track.decay_profile.apogee_km.length") > 10
    assert page.query_selector("#dc_spark polygon") is not None


def test_camera_views_and_screenshot(page, browser):
    plan(page)
    for cam in page.query_selector_all("#camerabar button[data-cam]"):
        cam.click()
        assert drawn(page) > 0
    page.check("#camfollow")
    page.evaluate("() => { tCur = plan.track.t[40]; redraw(); }")
    page.click("#camshot")
    page.wait_for_function("() => /screenshot/.test(document.getElementById('status').textContent)")
    kind = page.evaluate(
        "async () => (await navigator.clipboard.read()).flatMap(i => i.types).join(',')"
    )
    assert "image/png" in kind
