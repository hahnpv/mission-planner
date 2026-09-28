# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`mission-planner` is the generic, **public-bound** core (numpy/scipy/pyyaml, optional flask UI +
MCP server). Private capabilities live in a separate plugins repo and attach through the plugin
API; the core must never import from it.

## Running & testing

- Use the conda `dev` env (Python 3.12, on PATH; installed editable: `pip install -e ".[dev]"`).
  `/usr/bin/python3` has no numpy.
- Tests: `python -m pytest -q` (~3 s); they run against fake plugins, so they pass with no plugin
  package installed. Run the plugins repo's tests too after changing the plugin API.
- Web UI: `python -m mission_planner.server` → http://127.0.0.1:3030 (port hard-coded).
  MCP server: `python -m mission_planner.mcp_server`.

## Public / private boundary

- Nothing deployment-specific or proprietary goes in this repo: no private project, client,
  simulator or range names in code, comments, tests, data or docs. The plugins repo has a leak
  guard that scans this tree for known private names — run its tests before committing here. Private work goes in a plugin; private data goes in a data pack.
- Sites, presets and overlays are catalog data (`catalog.py`, `data/catalog/*.yaml`); overlays
  ship only in data packs.

## Architecture: everything is modular

- Plugin API: `plugins.py` (spec keys, dependency chains: `requires`, `available()`, statuses
  loaded / failed / unavailable, live switches). Built-in features (`modules/passes.py`,
  `modules/maneuvers.py`) use the same spec and are always active; plugins arrive via the
  `mission_planner.plugins` entry-point group.
- New core capability → a built-in module; anything private or optional → a plugin. Don't grow
  `server.py`, `mcp_server.py` or `static/index.html` with feature code — core gets generic hooks
  (propagation modes, trajectory sources, catalog packs, menu items, map layers). Reusable math belongs in the
  core library (e.g. `GroundTrack.passes()`), with the module as the UI/REST/MCP skin over it.
- Trajectory sources: a plan comes from a source (`source=` arg; core `site`/`preset`, plugins
  via spec key `sources` + `ctx.addSource`). Kind `orbit` returns an Orbit that gets propagated;
  kind `trajectory` returns a finished GroundTrack. Modules declare `works_with` (default
  `["orbit"]`) and go inert in the UI on plans of another kind; `orbit_from_args` raises
  ValueError for a trajectory source.
- Plugins import only the public core surface: `planning` (request args → orbit/track/payload),
  `jobs` (background work), `orbit.wrap_pi`, constants, groundtrack, timebase. Keep those stable;
  treat `_`-prefixed names as private.
- A plugin that fails to import or whose requirement is missing never raises — it shows in the
  UI's Plugins menu with the reason. JS hooks must go through `ctx.*` (never straight onto `MP._*`)
  so they go inert with their plugin. Map-drawing modules gate on `ctx.isOpen()`; `marker()` keys
  must be stable across redraws.
- `server.create_app()` builds the app over `plugins.registry()`; tests swap in a fake registry
  by monkeypatching `plugins._REGISTRY` (see `tests/test_plugins.py`).
- Much of the code is early-prototype. When you meet prototype leftovers (feature logic in core,
  duplicated helpers, ad-hoc globals), flag them and propose cleanup rather than copying the pattern.

## Domain gotchas

- "Passes" = ground-track subpoint proximity (`within_km`), **not** line of sight; that's the
  horizon footprint in the View menu.
- Naive datetimes are treated as UTC (`timebase.as_utc`).
- `atmosphere_1976_1000km.py` is a vendored copy kept in sync by a test in the plugins repo.

## Conventions

- Lint/format: `ruff check .` / `ruff format .` (config: `ruff.toml`; a hook formats edited files).
- Commit and push only at the user's direction.
