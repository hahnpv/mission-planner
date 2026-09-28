# mission-planner

Generic orbital mission planning: design an orbit over a known launch site at a
real UTC epoch, propagate it (two-body + J2, or drag-decay from a ballistic
coefficient), search overflights of a target, and display everything on a slick
local map UI that both humans and AI agents can drive.  Capabilities beyond the
core attach as **plugins**; sites, presets and map overlays are **data**.

## Install

```bash
pip install -e ".[dev]"        # numpy, scipy, pyyaml + flask, pytest
```

## Library

```python
from mission_planner import Orbit, SITES

orb = Orbit.from_launch_site(SITES["Cape Canaveral / KSC"], alt_km=400, inc_deg=51.6)
orb.summary()                          # period, revs/day, RAAN drift, ...
gt = orb.ground_track(24 * 3600)       # kepler + J2
gt.passes(28.5, -80.6, within_km=500)  # overflight windows, UTC

# Low orbits that decay in days/weeks: give a ballistic coefficient
gt = orb.ground_track(14 * 86400, mode="decay", beta=300.0)  # m/(Cd*A) kg/m^2
gt.extra["entry"]                      # predicted entry epoch + subpoint (or None)
```

| mode | physics | cost | stops at |
|---|---|---|---|
| `kepler` | two-body + J2 secular | ms | never |
| `decay` | averaged King-Hele, US76 extended to 1000 km | ms | 100 km interface |
| *plugin* | whatever a plugin's propagator flies | — | — |

Decay mode uses a static atmosphere, so lifetimes are nominal, not predictions
(real thermospheric density swings by factors of a few over the solar cycle).
Higher-fidelity propagators plug in as extra modes (see Plugins).

## Web UI

```bash
python -m mission_planner.server       # -> http://127.0.0.1:3030
```

Launch-site / preset / altitude / inclination / epoch controls, propagation
mode with a β input and altitude-decay sparkline, a pan/zoom map, a time
scrubber with play/pause, and a **display-window** control (1 rev / 90 min /
24 h / all, or drag the span handles).  The **display** menu switches between
a flat **map** (drag sideways to scroll endlessly), a **globe** (the map
projected on a sphere; drag to rotate) and an **orbit** view (the orbit drawn
in space around the earth, scaled to fit — most telling for high orbits), and
toggles the horizon footprint at the playback position, day/night shading, and each map
overlay.  Built in: **target passes** (click the map for overflight windows;
*subpoint proximity*, not line of sight — the horizon footprint answers that)
and **maneuvers** (Hohmann, plane change, phasing, deorbit-to-interface
budgets).  Zero external assets.

**Every marker on the map is a clickable entity**: core pins, module pins and
agent-pushed scene markers all go through `marker(lat, lon, color, symbol,
name, info)`.  Pass an `info` `{key, title, alt_km?, gamma_deg?, rows?}` and
a click toggles a readout of lat / lon / altitude / **γ** (earth-relative
flight path angle) plus your rows.  `key` must be stable across redraws.

## Catalog: sites, presets, overlays

Data, not code (`mission_planner/catalog.py`).  The core ships well-known
launch sites and textbook orbit presets in `mission_planner/data/catalog/`;
**data packs** add more.  A catalog directory holds any of `sites.yaml`,
`presets.yaml`, and `overlays/<id>.geojson` with an `overlays/<id>.yaml`
sidecar (`title`, `style: {color, opacity}`, `source`).

## Plugins

A plugin is an installed package that registers a spec under the
`mission_planner.plugins` entry-point group:

```toml
[project.entry-points."mission_planner.plugins"]
example = "my_plugins.example:MODULE"
```

The spec can add REST routes (a flask blueprint), a UI panel, MCP tools,
propagation modes, and a data-pack catalog, and can **require** other
plugins.  The full key list and the dependency-chain rules are in
`mission_planner/plugins.py`; the UI contract (`MP.register`, `ctx`) is in
`mission_planner/modules/__init__.py`.  Built-in features use the same
contract from `mission_planner/modules/`.

The UI's **plugins** box lists every installed plugin with what it adds, its
status (active, off, waiting on a requirement, unavailable, failed — with the
reason), and a live on/off switch: panels, map layers, routes, modes and data
switch without a reload.  `MP_DISABLE_MODULES=a,b` sets the starting
switches; MCP tools are fixed when the MCP server starts.

## Agent access

REST: everything the UI does is a GET (`/api/plan`, `/api/passes`), and
`POST /api/scene` pushes a Scene document (tracks / markers / polygons /
window tables — see `mission_planner/scene.py`) that renders live in the open
browser tab via SSE.

MCP: `python -m mission_planner.mcp_server` exposes `plan_orbit`,
`find_passes`, `list_launch_sites`, `show_scene`, `show_plan` (plan + display
in one call), and `maneuver_budget`, plus any active plugin's tools.

## Tests

```bash
python -m pytest -q
```
