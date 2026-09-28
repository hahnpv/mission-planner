---
name: new-module
description: Scaffold a new mission-planner capability — a built-in module in the public core, or a plugin in a separate plugins repo — with spec, JS panel and tests. Use when adding any feature to the planner UI, REST API, MCP tools, propagation modes or catalog data.
disable-model-invocation: true
---

Create a capability module named `$ARGUMENTS` (a slug, e.g. `downlink`). Ask what it should do if
that wasn't given.

1. Decide where it lives. Generic and public → built-in in `mission_planner/modules/`.
   Private, deployment-specific or optional → a plugin package in the plugins repo, registered
   under the `mission_planner.plugins` entry-point group in that repo's `pyproject.toml` (then
   `pip install -e .` there; follow that repo's own CLAUDE.md). Data only (sites/presets/overlays) → a data
   pack: a plugin whose spec has just `catalog`. Ask if unclear.
2. Read the spec keys and dependency rules in `mission_planner/plugins.py` and the UI contract in
   `mission_planner/modules/__init__.py`, then pick the closest existing module as a template:
   - REST route over a core-library function → `modules/passes.py` + `static/modules/passes.js`
   - backend + MCP tools → `modules/maneuvers.py` + `maneuvers.js`
   - for `requires`, `static_dir`, `propagators`, `available` and `catalog`, follow the spec
     docs in plugins.py and the fake plugins in `tests/test_plugins.py`
   Put reusable computation in the core library (or reuse what's there), not in the module.
3. Create the module file:
   - module docstring saying what it does and what it deliberately doesn't
   - flask imports inside `try/except ImportError` → `bp = None` (library use without flask)
   - orbit/track from request args via `mission_planner.planning`; slow work via `mission_planner.jobs`
   - `MODULE = {"api": 1, "name": "<slug>", "title": ..., "requires": [...], "blueprint": bp, "js": "<slug>.js", ...}`
     (plugins also set `static_dir`)
4. Create the JS asset (`static/modules/<slug>.js`, or the plugin's static dir) calling `MP.register({title, html, init(ctx)})`;
   map drawing gates on `ctx.isOpen()` and uses stable `marker()` keys. No external assets.
5. Add `tests/test_<slug>.py` in the repo it lives in: it loads with status `loaded` in
   `plugins.registry()`, its routes respond via `server.app.test_client()`, and (plugins) switching it
   off 404s them.
6. Do not edit `server.py`, `mcp_server.py` or `index.html` unless a generic hook is genuinely
   missing — if so, stop and propose the core hook first.
7. Run `/verify`.
