# Agents — MCP and REST

mission-planner is built to be driven by software as well as by hand. An AI
agent can plan and analyse orbits through the **MCP server**, show its results
in your browser tab, and anything else can use the **REST API** the UI itself
runs on.

## The MCP server

```bash
python -m mission_planner.mcp_server
```

It speaks MCP over stdio; register it with your client as shown in
[Getting started](../getting-started.md#connect-an-ai-agent).

### Tools

| tool | what it does |
|---|---|
| `list_launch_sites()` | the launch-site catalog, each site tagged with the data pack it came from |
| `plan_orbit(...)` | plans an orbit and returns its summary: period, revs/day, RAAN drift, launch azimuth; drag modes add the entry epoch and subpoint and the final altitude |
| `track_samples(..., max_points=500, start_hours=0, end_hours=None)` | the ground track itself, as columns `t_s`, `lat_deg`, `lon_deg`, `alt_km`, evenly downsampled over a window (at most 5000 points) |
| `find_passes(tgt_lat, tgt_lon, ...)` | overflight windows of a target: UTC entry, exit and closest approach, miss distance, heading and leg |
| `maneuver_budget(alt1_km, inc1_deg, alt2_km, inc2_deg, lead_deg=None)` | impulsive Δv between two circular orbits: Hohmann, plane change separate or combined, optional phasing, deorbit to 100 km |
| `load_file(path, epoch_utc=None, options=None)` | stores a trajectory file for the UI's File source and returns what the plugin that reads it found |
| `show_plan(...)` | plans an orbit and shows it in the running UI as its plan — with a target, its passes are marked and listed too |
| `show_scene(scene)` | pushes a drawing (tracks, markers, polygons, labels, tables, optionally a plan) to the running UI |

Active plugins add their own tools. The tool set is fixed when the MCP server
starts, so restart it after switching plugins.

### Orbit parameters

`plan_orbit`, `track_samples`, `find_passes` and `show_plan` share one set of orbit keywords:

| keyword | default | meaning |
|---|---|---|
| `site` | `"Cape Canaveral / KSC"` | a catalog name; a label for a custom site given by `lat`/`lon`; or `""` (with no `lat`) for an element-anchored orbit |
| `lat`, `lon` | — | a custom launch site |
| `alt_km` | 400 | circular altitude |
| `perigee_km`, `apogee_km` | — | an ellipse instead of `alt_km` |
| `perigee_offset_deg` | 0 | perigee this many degrees downrange of the site crossing |
| `inc_deg` | 51.6 | inclination |
| `ascending` | true | the site on the northbound leg |
| `node_lon_deg`, `argp_deg` | 0, 0 | for `site=""`: the ascending node's longitude at the epoch (GEO: the station) and the argument of perigee |
| `epoch_utc` | now | ISO 8601 |
| `hours` | 24 (48 for passes) | horizon; the sample step coarsens with it |
| `mode`, `beta` | `"kepler"`, — | propagation mode; `beta` = m/(C<sub>d</sub>A) for drag modes |

Classic element-anchored orbits, for instance:

```text
plan_orbit(site="", perigee_km=500, apogee_km=39868, inc_deg=63.4, argp_deg=270)   # Molniya
plan_orbit(site="", alt_km=35786, inc_deg=0, node_lon_deg=-100)                     # GEO at 100 W
```

### Showing results to the user

`show_plan` and `show_scene` post to the web UI at `http://127.0.0.1:3030`, so
the UI must be running (`python -m mission_planner.server`). The open tab
updates at once, over server-sent events. `show_plan` puts a real plan on
screen — the timed track with playback, the display window and every panel —
exactly as if the user had planned it in the form; the plan carries the
`args` that made it, so the panels ask the server about that very plan.
Each scene version is taken up once: a reconnect that re-announces the
current version neither re-applies its plan nor brings back a scene that a
plan made in the form since has replaced.

## Scenes

A scene is a JSON document the UI knows how to draw:

```json
{
  "title": "Target over the Front Range",
  "layers": [
    {"kind": "marker", "name": "target", "lat": 40.0, "lon": -105.0, "symbol": "target", "color": "#eb6834"},
    {"kind": "track", "name": "survey leg", "lat": [38, 39, 40], "lon": [-107, -105.5, -104], "dash": "4 3"},
    {"kind": "polygon", "name": "zone", "lat": [39, 41, 41, 39], "lon": [-106, -106, -104, -104], "fill": "#2a78d6"},
    {"kind": "label", "text": "Denver", "lat": 39.7, "lon": -104.9},
    {"kind": "windows", "name": "passes", "columns": ["UTC", "km"], "rows": [["15:11", 380.5]]}
  ]
}
```

| layer | fields |
|---|---|
| `track` | `name, lat[], lon[]`, optional `color, width, dash` |
| `marker` | `name, lat, lon`, optional `color, symbol` (`dot`, `target` or `site`) |
| `polygon` | `name, lat[], lon[]`, optional `color, fill` |
| `label` | `text` (required), `lat, lon`, optional `color` |
| `windows` | `name, columns[], rows[][]` — drawn as a table in the legend |

Angles are degrees. Unknown fields pass through untouched, so newer scenes
still load on older servers; a malformed scene is rejected with a reason.

A scene may also carry **`plan`**: a whole `/api/plan` payload (its `track`,
and each of `tracks`, must have `t`, `lat`, `lon` and `alt_km` lists of two
or more samples). The UI then shows it as its own plan, with the layers as
annotations; they are cleared when the user plans something else. In Python:

```python
from mission_planner import Scene, planning

plan = planning.plan_from_args({"source": "site", "site": "Vandenberg", "hp": 550, "inc": 97.6})
sc = Scene(title="SSO from Vandenberg", plan=plan).marker("target", 40.0, -105.0, symbol="target")
sc.to_json()      # POST this to /api/scene
```

## The REST API

The web UI is a client of a small JSON API, and so can anything else. Every
error is JSON `{"error": "..."}`: 400 for bad input (with the reason), 404 or
409 for something missing or not switchable, 500 for a failure inside the
planner or a plugin (named in the message).

### Planning

`GET /api/plan?<args>` returns `{summary, track, args}` — and `tracks`,
`primary` for a plan with several tracks. `args` is the request's query args
as strings, so a client can ask the modules' routes about the same plan.

| arg | for | meaning |
|---|---|---|
| `source` | all | `site` (default), `preset`, `file`, or a plugin's source id |
| `site` or `lat`&`lon` | site | the launch site |
| `hp`, `ha`, `inc` | site, preset | perigee and apogee altitude (km), inclination |
| `leg`, `pofs` | site | `ascending` / `descending`; perigee offset (deg) |
| `node_lon`, `argp` | preset | node longitude at the epoch, argument of perigee |
| `upload` | file | a stored file's id (see uploads below) |
| `epoch` | all | ISO 8601 UTC |
| `hours`, `dt`, `mode`, `beta` | orbits | horizon, sample step (s), propagation mode, ballistic coefficient |

```bash
curl 'http://127.0.0.1:3030/api/plan?site=Vandenberg&hp=550&inc=97.6&hours=6'
```

`POST /api/plan_job?<args>` runs the same plan in the background (for slow
plugin modes) and answers `{job_id}`; poll `GET /api/plan_job/<id>` until its
`status` is `done` (the plan payload, plus `elapsed_s`, the run time) or
`error`. A track is capped at 200,000 samples; ask for fewer hours or a
larger `dt` beyond that.

### Built-in analysis

| route | returns |
|---|---|
| `GET /api/passes?<plan args>&tgt_lat=&tgt_lon=&within_km=` | `{n, passes}` for the plan; on a multi-track plan the passes of every track, in time order on the first track's clock, each with `track` (id) and `label` |
| `GET /api/maneuvers/budget?alt1=&inc1=&alt2=&inc2=&lead=` | the maneuver budget |

### Catalog, files, plugins, scenes

| route | purpose |
|---|---|
| `GET /api/sites`, `/api/presets`, `/api/overlays` | the catalog: core data plus active data packs |
| `POST /api/uploads` (multipart `file`) | store a file; answers its `id` and the plugin reader that claims it (`kind`) |
| `GET /api/uploads[?ext=.h5]`, `GET`/`DELETE /api/uploads/<id>` | list, describe, remove stored files |
| `GET /api/files/<id>/inspect` | what the File source panel shows for a stored file (404 for an unknown id) |
| `GET /api/modules`, `POST /api/modules/<name>` `{"enabled": bool}` | plugins: status and live switches |
| `POST /api/scene`, `GET /api/scene` | push or read the scene on display |
| `GET /api/events` | server-sent events: a message whenever a new scene arrives |

Plugins add routes of their own under `/api/`.
