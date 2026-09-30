# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`mission-planner` is the generic, **public-bound** core (numpy/scipy/pyyaml, optional flask UI +
MCP server). Private capabilities live in a separate plugins repo and attach through the plugin
API; the core must never import from it.

## Running & testing

- Use the conda `dev` env (Python 3.12; installed editable: `pip install -e ".[dev]"`, which
  brings flask, mcp, pytest and ruff). Check `which python` first: a non-activated shell may
  resolve `python` to the conda base env, which also has an editable install, so mistakes pass
  silently there and `ruff` is missing. `/usr/bin/python3` has no numpy.
- Tests: `python -m pytest -q` (~4 s). `tests/conftest.py` builds the app over the built-in
  modules only (`core_reg` / `core_client` fixtures), so installed plugins can't affect the
  core's suite. Run the plugins repo's tests too after changing the plugin API.
- Web UI: `python -m mission_planner.server` → http://127.0.0.1:3030 (port hard-coded).
  MCP server: `python -m mission_planner.mcp_server`.

## Public / private boundary

- Nothing deployment-specific or proprietary goes in this repo: no private project, client,
  simulator or range names in code, comments, tests, data or docs; no references to a predecessor
  codebase. The plugins repo has a leak guard that scans this tree for known private names — run
  its tests before committing here. Private work goes in a plugin; private data goes in a data pack.
- Sites, presets and overlays are catalog data (`catalog.py`, `data/catalog/*.yaml`); overlays
  ship only in data packs.

## Architecture: everything is modular

- Plugin API: `plugins.py` (spec keys, validation, uniqueness of mode/source/blueprint/tool ids,
  dependency chains: `requires`, `available()`, statuses loaded / failed / unavailable, live
  switches). The authoring guide is `docs/plugins.md` — keep it in step with any API change.
  Built-in features (`modules/passes.py`, `maneuvers.py`, `decay.py`, `files.py`,
  `groundstation.py`) use the same spec and are always active; plugins arrive via the
  `mission_planner.plugins` entry-point group.
- New core capability → a built-in module; anything private or optional → a plugin. Don't grow
  `server.py`, `mcp_server.py` or `static/ui/*.js` with feature code — core gets generic hooks
  (propagation modes, trajectory sources, catalog packs, menu items, map layers). Reusable math
  belongs in the core library (e.g. `GroundTrack.passes()`), with the module as the UI/REST/MCP
  skin over it (`modules/passes.py` carries the `find_passes` MCP tool, not `mcp_server.py`).
- Trajectory sources: a plan comes from a source (`source=` arg; core `site`/`preset`, plugins
  via spec key `sources` + `ctx.addSource`). Kind `orbit` returns an Orbit that gets propagated;
  kind `trajectory` returns a finished GroundTrack. Modules declare `works_with` (default
  `["orbit"]`) and go inert in the UI on plans of another kind; `orbit_from_args` raises
  ValueError for a trajectory source.
- File input is generic: `uploads.py` is a content-addressed store (`MP_UPLOAD_DIR`, default
  `~/.cache/mission-planner/uploads`; tests get a tmp one via an autouse fixture), plans carry
  `upload=<id>`, and the UI's picker is `static/ui/files.js` (`ctx.filePicker` for plugins).
  File *formats* come from plugins' `file_readers` (detect / inspect / read); `filekinds.py`
  routes a file to the one reader that claims it (cached per upload), and the built-in
  `modules/files.py` is the single "File" source with a panel drawn from `inspect()`. A new
  format is a reader, not a new source; don't add per-feature upload code.
- Multi-track plans: a source/reader may return a list of `GroundTrack`s (`id`, `label`,
  `parent`); `planning.track_set_payload` adds `tracks` + `primary` and keeps `track` = the
  primary. In the UI `plan.track` is the focused track (`setFocus`, the track picker, a click
  on a vehicle); `planTracks()` / `planEnd()` (state.js) span them all, and onPlan hooks rerun
  on a focus change. A catalog preset may be a file preset (`file_from`: a plugin route that
  stores a file; the UI opens it in the File source via `openFile`).
- Request reading lives in `planning.py` only: `orbit_from_args` / `track_from_args` for query
  args, `orbit_from_params` (MCP keywords) delegates to them. Bad input is a ValueError; the web
  app's error handler turns it into a JSON 400, anything else into a JSON 500. Point count is
  capped (`MAX_TRACK_POINTS`); `default_dt` picks the step for a horizon.
- Plugins import only the public core surface: `planning`, `jobs`, `orbit` (`Orbit`, `wrap_pi`,
  `kepler_E` & co.), constants, groundtrack, timebase, catalog, scene, uploads, filekinds. Keep
  those stable; treat
  `_`-prefixed names as private.
- A plugin that fails to import, whose spec is invalid, or whose requirement is missing never
  raises — it shows in the UI's Plugins menu with the reason; `create_app()` never raises for a
  plugin's sake either. JS hooks must go through `ctx.*` (never straight onto `MP._*` or the
  core's DOM) so they go inert with their plugin. Map-drawing modules gate on `ctx.isOpen()`;
  `marker()` keys must be stable across redraws.
- Frontend: `static/index.html` is markup only; the code is plain scripts in `static/ui/`
  (state → projection → sun → map → timeline → form → menus → files → plugins), sharing one global
  scope — not ES modules, because module scripts rely on `MP` and `document.currentScript`.
- State that used to be module globals lives on the app: `SceneStore` on
  `app.extensions["mp_scene"]` (SSE waits on its condition, with heartbeats); jobs in a `JobStore`
  (`jobs.start`/`poll` share one). `server.app` is built lazily on first attribute access.
- The SSO preset family (`ssoInclination`, LTAN → node longitude) still lives in `static/ui/form.js`
  because it needs form hooks no module has; it's the known remaining piece of feature logic in core.

## Domain gotchas

- "Passes" = ground-track subpoint proximity (`within_km`), **not** line of sight; that's the
  horizon footprint in the View menu.
- Naive datetimes are treated as UTC (`timebase.as_utc`). The Earth is a sphere: site latitudes
  are geocentric.
- `Orbit.period` is the anomalistic period; `nodal_period` (used for `revs_per_day`) adds the
  J2 perigee drift. Decay mode starts from the true anomaly at epoch so it lines up with the
  Kepler track, and includes the atmosphere co-rotation factor.
- `atmosphere_1976_1000km.py` is a vendored copy kept in sync by a test in the plugins repo;
  `atmosphere.density` extrapolates log-linearly above its 1000 km table.

## Conventions

- Lint/format: `ruff check .` / `ruff format .` (config: `ruff.toml`; a hook formats edited files).
- Commit and push only at the user's direction.
