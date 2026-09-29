# Writing a mission-planner plugin

A plugin is an installed Python package that hands the core a **spec**: a
dict describing what it adds. The core discovers specs through an entry
point, loads them once at start-up, and wires each capability into the
right surface: REST routes into the web server, a JavaScript asset into the
side panel and map, functions into the MCP server, propagation modes and
trajectory sources into planning, and a catalog directory into the sites /
presets / overlays lists.

Built-in features (`mission_planner/modules/`) use exactly the same contract,
so every pattern below has a working example in the core:

| pattern | built-in example |
|---|---|
| REST route + UI panel + MCP tool over a core function | `modules/passes.py`, `static/modules/passes.js` |
| pure math + REST route + MCP tool | `modules/maneuvers.py`, `static/modules/maneuvers.js` |
| UI-only panel reacting to plans | `modules/decay.py`, `static/modules/decay.js` |
| propagators, sources, data packs, `requires`, `available` | the fake plugins in `tests/test_plugins.py` |

The reference for spec keys is the docstring of `mission_planner/plugins.py`;
this guide is the tutorial.

## 1. The minimum

A package, an entry point, a spec.

```
my_plugins/
  pyproject.toml
  my_plugins/
    __init__.py
    hello/
      __init__.py
```

```toml
# pyproject.toml
[project]
name = "my-plugins"
version = "0.1.0"
dependencies = ["mission-planner"]

[project.entry-points."mission_planner.plugins"]
hello = "my_plugins.hello:MODULE"      # entry-point name == spec "name"
```

```python
# my_plugins/hello/__init__.py
MODULE = {
    "api": 1,
    "name": "hello",
    "title": "hello world",
    "description": "does nothing yet, but shows up in the Plugins menu",
}
```

Install it next to the core (`pip install -e .`), start the UI, open the
**Plugins** menu: the plugin is listed as active with a live on/off switch.

Everything else is optional keys on that dict. The rules that never change:

- **Importing the spec must not fail.** The core catches an import error and
  shows the plugin as *failed* with the message, but nothing of the plugin
  works. Keep heavy or optional imports inside functions, or guard them (the
  `available` key below is for a missing external tool).
- **Import only the public core surface**: `mission_planner.planning`,
  `jobs`, `orbit` (`Orbit`, `wrap_pi`, the element helpers), `groundtrack`,
  `timebase`, `constants`, `catalog`, `scene`, `uploads`. Never `server`, `mcp_server`,
  or a `_`-prefixed name. If you need something the core does not expose,
  add a generic hook to the core rather than reaching in.
- **Reusable math belongs in a library, the plugin is the skin.** A route,
  a panel and a tool that wrap one function stay small and testable.

## 2. How a plugin is loaded and switched

At start-up the core builds a **registry** (`plugins.registry()`): every
built-in and every entry point, in load order. Each record has a status:

| status | meaning | shown as |
|---|---|---|
| `loaded` | imported and valid | switch in the Plugins menu |
| `failed` | import raised, spec invalid, name or id already taken, or part of a `requires` cycle | red detail with the reason |
| `unavailable` | a requirement is missing / failed / unavailable, or `available()` returned a reason | grey detail with the reason |

Validity is checked key by key (types, callables, core ids), so a typo is
reported as *failed: 'propagators' must be a dict…* instead of a 500 later.
Ids that must be unique across the core and all plugins — propagation mode
ids, source ids, blueprint names and MCP tool function names — are checked
in load order: the later plugin that reuses one is failed, naming the owner.

At run time a loaded plugin is **active** when its own switch is on and every
plugin it `requires` is active. Switching a plugin on switches its
requirements on; switching one off leaves its dependents' switches alone,
they go inactive and report *waiting on X*. `MP_DISABLE_MODULES=a,b` sets the
starting switches. Built-ins are always on.

Being inactive is thorough: the server answers the plugin's routes with 404,
its modes, sources and catalog disappear from planning, and in the browser
its panel hides and every hook it registered through `ctx` stops being
called. MCP tools are the one exception: the MCP server reads the switches
once when it starts.

## 3. Capabilities

Each subsection is one spec key or a pair that go together. Combine freely.

### 3.1 REST routes — `blueprint`

A flask Blueprint. Register routes on it as usual; the core registers the
blueprint at app creation and gates every request on the plugin being
active (nested blueprints included). Keep flask optional so the package
imports as a library without it:

```python
from mission_planner.planning import req_float, track_from_args

def altitude_stats(gt):
    """Min / max / mean altitude of a track [km]."""
    alt = gt.alt * 1e-3
    return {"min_km": round(alt.min(), 1), "max_km": round(alt.max(), 1),
            "mean_km": round(alt.mean(), 1)}

try:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("altstats", __name__, url_prefix="/api/altstats")

    @bp.route("/")
    def _stats_route():
        _, _, gt = track_from_args(request.args)   # ValueError -> the core answers 400
        return jsonify(altitude_stats(gt))
except ImportError:
    bp = None

MODULE = {"api": 1, "name": "altstats", "title": "altitude stats", "blueprint": bp}
```

Two things the core does for you:

- **Reading the plan from the request.** `planning.track_from_args(args)`
  gives `(orbit, meta, GroundTrack)` for whatever the UI is currently
  showing — any source, any mode — and `orbit_from_args(args)` gives just
  the orbit (a ValueError for a trajectory source, which has none). The UI
  sends the same query string to your route that it sent to `/api/plan`
  (`ctx.planArgs()` below), so the panel always talks about the orbit on
  screen. `opt_float(args, key, default)` / `req_float(args, key, default)`
  parse numbers with a clean error.
- **Errors.** Raise `ValueError` for bad input and the core turns it into
  `{"error": …}` with HTTP 400; anything else becomes a JSON 500 with the
  traceback on stderr. You only need your own `try/except` when you want a
  different status.

Blueprint names must be unique across plugins; the URL prefix is yours to
choose, `/api/<plugin name>/…` by convention.

### 3.2 A UI panel and map layers — `js` and `static_dir`

`js` names a script in `static_dir` (a `pathlib.Path`, usually
`Path(__file__).parent / "static"`). The core loads it after the page boots.
The script registers a side-panel section:

```js
"use strict";
MP.register({
  title: "altitude stats",
  open: false,                 // start collapsed (default)
  html: `<div id="as_out" class="hint">plan an orbit</div>`,
  init(ctx) {
    async function refresh() {
      const r = await ctx.api("/api/altstats/?" + ctx.planArgs());
      if (r.error) { ctx.status("altstats: " + r.error, true); return; }
      document.getElementById("as_out").textContent =
        `${r.min_km} – ${r.max_km} km, mean ${r.mean_km} km`;
    }
    ctx.onPlan(() => { if (ctx.isOpen()) refresh(); });
    ctx.onToggle(open => { if (open && ctx.getPlan()) refresh(); });
  },
});
```

`html` is the panel body (leave it empty for a plugin with no panel of its
own, say one that only adds a source: no box is shown, and `isOpen()`
follows the plugin's switch); give element ids a short prefix (`as_`) so panels
never collide. Everything the panel needs from the core comes through the
`ctx` object passed to `init` — never reach for `MP._*` or the core's DOM
directly, because hooks registered through `ctx` are what go inert when the
plugin is switched off.

**`ctx` reference**

| member | what it does |
|---|---|
| `api(path)` | `fetch` + JSON; resolves to the body, which has an `error` field on a 4xx/5xx; throws on a network failure or a non-JSON error |
| `status(msg, isErr?)` | the status line under the plan button |
| `redraw()` | redraw the map (call after your layer's data changed) |
| `getPlan()` | the current `{summary, track}` from `/api/plan`, or `null` |
| `planArgs()` | `URLSearchParams` of the request that produced the current plan (source, shape, epoch, mode, beta, hours, dt) |
| `isOpen()` | the panel is open **and** the plugin is active |
| `onToggle(cb)` | `cb(open)` when the user opens or closes the panel |
| `onPlan(cb)` | `cb(plan)` after every new plan (and once when the plugin is switched on while a plan is showing) |
| `onDraw(fn)` / `onDrawOver(fn)` | map layers under / over the ground track; `fn(d)` gets the draw context below |
| `onClick(fn)` | `fn(lat, lon)` for a click on the map or globe |
| `seek(t_s)` | move playback to seconds past the plan epoch |
| `addDisplayToggle(label, checked, cb)` | a checkbox row in the View menu's layers section; returns the `<input>` holding the state |
| `addMenuItem(menu, item)` | an item in a menu-bar menu (created if new); item types in `static/ui/menubar.js` |
| `addSource(spec)` / `updateSource()` | a trajectory source's UI half (section 3.5) |
| `filePicker(opts)` | a file input over the server's upload store (section 3.5); returns `{el, value, info, select(id), refresh()}` |

Panels, menu items, display toggles and every hook above are hidden or
skipped while the plugin is inactive, and while the current plan is of a
kind the plugin does not `works_with` (section 3.7).

**Map layers.** `onDraw` / `onDrawOver` callbacks run on every redraw (every
drag frame), so keep them cheap and gate them on `ctx.isOpen()`: a closed
panel puts nothing on the map. The draw context `d`:

| member | what it does |
|---|---|
| `d.plan`, `d.tCur` | the plan and the playback time [s past epoch] |
| `d.polyline(pts, attrs)` | `pts = [[lat, lon], …]` degrees; splits at the map seam / clips at the globe limb |
| `d.polygon(lats, lons, attrs)` | filled ring, seam- and limb-safe |
| `d.marker(lat, lon, color, symbol, name, info)` | `symbol` = `"dot"`, `"target"` or `"site"`; `info = {key, title, alt_km?, gamma_deg?, rows?}` makes it clickable with a readout |
| `d.project(lat, lon)` | `{x, y, vis}` if you must place your own SVG element |
| `d.C` | the palette (`blue orange green red muted grid`) |
| `d.idxAtTime(t_s, track?)` | sample index nearest a time |
| `d.fpa(track, k)` | earth-relative flight path angle [deg] at sample `k` |
| `d.globe`, `d.view` | `true` off the flat map; `"map"`, `"globe"` or `"orbit"` |

Everything drawn through `d.*` works in all three views unchanged. Marker
`key`s must be stable across redraws (`"as:burn"`, not a counter): the map
is rebuilt from scratch on every frame and the key is how an open readout
survives that.

Module CSS goes inline in `html` (a `<style>` block scoped by your prefix),
and no external assets: the UI is fully local.

### 3.3 MCP tools — `mcp_tools`

A list of plain functions. The MCP server registers each one as a tool
when it starts, so the signature and docstring are the schema an agent
sees: type-annotate every parameter, give defaults, return a dict.

```python
from mission_planner.planning import default_dt, orbit_from_params

def altitude_stats_tool(
    site: str = "Cape Canaveral / KSC",
    alt_km: float = 400.0,
    inc_deg: float = 51.6,
    epoch_utc: str | None = None,
    hours: float = 24.0,
    perigee_km: float | None = None,
    apogee_km: float | None = None,
) -> dict:
    """Min / max / mean altitude over the horizon for a planned orbit
    (parameters as plan_orbit)."""
    orb, _ = orbit_from_params(site=site, alt_km=alt_km, inc_deg=inc_deg,
                               epoch_utc=epoch_utc, perigee_km=perigee_km,
                               apogee_km=apogee_km)
    return altitude_stats(orb.ground_track(hours * 3600.0, default_dt(hours)))

MODULE = {..., "mcp_tools": [altitude_stats_tool]}
```

`orbit_from_params` takes the same keywords as the core's `plan_orbit` tool
and reads them exactly as `/api/plan` would, so an agent and the UI agree.
Tool names (the function `__name__`) are unique across the core and all
plugins; a collision fails the plugin at load.

### 3.4 Propagation modes — `propagators`

A mode is a function that turns an orbit into a `GroundTrack`:

```python
import numpy as np
from mission_planner.constants import RE
from mission_planner.groundtrack import GroundTrack

def two_body(orbit, beta, duration_s, dt_s):
    """Two-body only: the core's kepler mode without the J2 secular drift."""
    t = np.arange(0.0, duration_s + 0.5 * dt_s, dt_s)
    frozen = orbit.__class__(orbit.a, orbit.e, orbit.inc, orbit.raan,
                             orbit.argp, orbit.m0, orbit.epoch)
    ...  # your own propagation of `frozen` to lat/lon/r arrays [rad, m]
    return GroundTrack(epoch=orbit.epoch, t=t, lat=lat, lon=lon, alt=r - RE)

MODULE = {..., "propagators": {
    "twobody": {"fn": two_body, "label": "two-body (no J2)",
                "needs_beta": False, "slow": False},
}}
```

The mode appears in the UI's propagation-mode select and is accepted by
`/api/plan?mode=twobody`, `Orbit.ground_track(mode="twobody")` and every
MCP tool with a `mode` parameter. `beta` is the ballistic coefficient the
user entered (or `None`); set `needs_beta` so the UI shows the input. Set
`slow` for anything that takes more than a second: the UI then runs the
plan as a background job (`POST /api/plan_job`, polled) instead of blocking.

Put anything mode-specific for the UI into `extra` on the track: the core
already understands `entry` (`{epoch_utc, t_s, lat_deg, lon_deg}`),
`impact` (the same plus `last_alt_km`) and `decay_profile` (`{t, alt_km}`
lists) and draws them; other keys ride along in the plan JSON for your own
panel. Raise `ValueError` for inputs the mode cannot take (an eccentric
orbit, a missing beta); the message reaches the user.

### 3.5 Trajectory sources — `sources` and `ctx.addSource`

A source is *where a plan comes from*. The core has two: a launch site and
an element-anchored preset. A plugin adds one by giving both halves:

- the Python half in the spec: `fn(args)` returns `(Orbit, meta)` for
  kind `"orbit"` (the core then propagates it with the usual mode / hours /
  dt) or `(GroundTrack, meta)` for kind `"trajectory"` (a finished track,
  say from a file or a simulator). `meta` joins the plan summary; a `title`
  there is what the status line shows.
- the JavaScript half: `ctx.addSource({id, label, html, init(panel),
  ready(), args(q), planLabel})` in the plugin's `js`. It adds a button to
  the source row and a panel of the source's own inputs; `args(q)` copies
  those inputs into the request as query args (`fn` receives them), and
  `ready()` says whether the plan button should be enabled. Call
  `ctx.updateSource()` when `ready()` may have changed.

```python
def from_state_vector(a):
    """An orbit from an ECI position/velocity typed into the panel."""
    from mission_planner.planning import parse_epoch, req_float
    r = [req_float(a, k, 0.0) for k in ("rx", "ry", "rz")]   # km
    v = [req_float(a, k, 0.0) for k in ("vx", "vy", "vz")]   # km/s
    orb = orbit_from_rv(r, v, parse_epoch(a.get("epoch")))  # your conversion
    return orb, {"title": "state vector"}

MODULE = {..., "js": "sv.js", "static_dir": Path(__file__).parent / "static",
          "sources": {"sv": {"fn": from_state_vector, "label": "State vector",
                             "kind": "orbit", "slow": False}}}
```

```js
MP.register({
  title: "state vector", html: "",
  init(ctx) {
    ctx.addSource({
      id: "sv", label: "State vector",
      html: `<div class="lbl">ECI r (km), v (km/s)</div>
             <div class="row"><input id="sv_rx"><input id="sv_ry"><input id="sv_rz"></div>
             <div class="row"><input id="sv_vx"><input id="sv_vy"><input id="sv_vz"></div>`,
      args(q) { for (const k of ["rx","ry","rz","vx","vy","vz"])
                  q.set(k, document.getElementById("sv_" + k).value || 0); },
    });
  },
});
```

The id must exist on both sides, and cannot be `site` or `preset`. A
`"trajectory"` source has no orbit, so modules that need one (`works_with`
`["orbit"]`, the default) go inert while it is showing, and
`orbit_from_args` raises for it.

**Sources that read a file.** A file can't ride in a query string, so it
goes into the server's upload store once and the args carry its id
(`upload=<id>`). The id is a prefix of the content's SHA-256, so a plan's
args stay reproducible and the same file never gets stored twice. The UI
half is `ctx.filePicker(opts)`, the core's file input. It lists the files
already stored (filtered by extension), uploads a new one from *browse…* or
a drop, deletes the chosen one from the server with its ✕ button (after a
confirm), and calls `onChange(info)` with `{id, name, size, uploaded_utc}` or
`null`:

```js
const picker = ctx.filePicker({ accept: ".csv", placeholder: "choose a track…",
                                onChange: () => ctx.updateSource() });
ctx.addSource({
  id: "csv", label: "CSV track", html: `<div id="csv_pick"></div>`,
  init(panel) { panel.querySelector("#csv_pick").appendChild(picker.el); },
  ready: () => !!picker.value,
  args(q) { q.set("upload", picker.value); },
});
```

On the Python side, `mission_planner.uploads.path(a.get("upload"))` is the
file on disk (a ValueError, so a 400, for a bad or unknown id) and
`uploads.info(id)["name"]` its original name. An MCP tool that takes a local
path can call `uploads.put_file(path)` and hand back the id, so the UI can
open the same file. The store is `MP_UPLOAD_DIR`, else
`~/.cache/mission-planner/uploads`. Routes: `POST /api/uploads` (multipart
`file`), `GET /api/uploads?ext=.csv`, `GET` / `DELETE /api/uploads/<id>`
(`uploads.delete(id)` from Python). A deleted file's id stops resolving; the
same content uploaded again gets the same id back.

### 3.6 Data packs — `catalog`

A directory with any of `sites.yaml`, `presets.yaml` and
`overlays/<id>.geojson` + `overlays/<id>.yaml` (formats in
`mission_planner/catalog.py`). Its items join the core's lists while the
plugin is active, tagged with the plugin name; a later pack's item replaces
an earlier one of the same name. A pack needs no code at all:

```python
from pathlib import Path
MODULE = {"api": 1, "name": "mysites", "title": "my launch sites",
          "catalog": Path(__file__).parent / "catalog"}
```

Ship the directory in the wheel (`package-data`). The catalog is cached on
file modification times, so editing a YAML while the server runs is picked
up on the next request.

### 3.7 Dependencies and preconditions — `requires`, `available`, `works_with`

- `requires: ["sim"]` — this plugin imports from, or only makes sense with,
  plugin `sim`. Declare it for every plugin you import from: the registry
  then loads, switches and reports them as a chain, and the Plugins menu
  shows *needs sim*.
- `available: fn` — a callable run once at load that returns a reason
  string when a runtime precondition is unmet (an external simulator not on
  this machine), or `None`. The plugin is *unavailable* with that reason,
  everything requiring it follows, and nothing raises.
- `works_with: ["orbit", "trajectory"]` — which plan kinds the plugin's UI
  and routes make sense for. Default `["orbit"]`; a pass search that only
  needs a track lists both.

## 4. Testing a plugin

The core's test fixtures show the pattern; the essentials for a plugin repo:

```python
import mission_planner.plugins as plugins
import mission_planner.server as server
from mission_planner.plugins import Registry, builtin_sources
from my_plugins.altstats import MODULE

def client(monkeypatch):
    reg = Registry([*builtin_sources(), ("altstats", False, lambda: MODULE)])
    monkeypatch.setattr(plugins, "_REGISTRY", reg)   # the registry the app is built over
    return server.create_app().test_client(), reg

def test_loads_and_serves(monkeypatch):
    c, reg = client(monkeypatch)
    assert reg.records["altstats"].status == "loaded"
    assert c.get("/api/altstats/?hours=1").status_code == 200
    reg.set_enabled("altstats", False)
    assert c.get("/api/altstats/?hours=1").status_code == 404   # gated with the switch
```

Test the math directly (it is a plain function), the route through the test
client, the MCP tool by calling it, and — if the plugin has a `js` — that
`/plugins/<name>/<file>` serves it. A plugin that needs an external tool
should skip those tests when `available()` returns a reason, not fail.

Run the core's own suite too after any change to the plugin API; it runs
over the built-ins alone, so an installed plugin cannot break it.

## 5. Checklist

- [ ] entry point name == spec `name`, package reinstalled (`pip install -e .`)
- [ ] the spec module imports with nothing optional at top level; `available` for external tools
- [ ] `requires` lists every plugin you import from
- [ ] flask imports guarded; blueprint name and URL prefix are your plugin's
- [ ] JS goes through `ctx.*` only; map layers gate on `ctx.isOpen()`; marker keys stable; element ids prefixed
- [ ] `ValueError` for bad input, with a message a user can act on
- [ ] MCP tools: annotated parameters, docstring, dict result, unique names
- [ ] `slow: true` on anything that takes more than a second
- [ ] static and catalog directories in `package-data`
- [ ] tests: loads as `loaded`, routes answer, switching off 404s them
- [ ] nothing private goes into the core: a plugin is where deployment-specific code and data live
