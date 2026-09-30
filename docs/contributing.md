# Contributing

## Development setup

```bash
git clone https://github.com/hahnpv/mission-planner.git
cd mission-planner
pip install -e ".[dev,docs]"
```

## Tests and lint

```bash
python -m pytest -q                      # a few seconds
ruff check . && ruff format --check .    # config: ruff.toml
```

The tests run over the built-in modules only (the `core_reg` / `core_client`
fixtures in `tests/conftest.py`), so plugins installed in your environment
can't change the result. Every test gets its own upload store.

## Where things go

- **Reusable computation** belongs in the core library — `orbit.py`,
  `groundtrack.py`, `decay.py` — with a module as the UI, REST and MCP skin
  over it. `GroundTrack.passes()` and `modules/passes.py` are the pattern.
- **A new core capability** is a built-in module in `mission_planner/modules/`
  with its UI in `static/modules/`. It uses the same spec as a plugin; see the
  [Plugin guide](plugins.md).
- **Anything optional or specialised** is a plugin, in its own package.
  Don't grow `server.py`, `mcp_server.py` or `static/ui/*.js` with feature
  code: give the core a generic hook instead (a propagation mode, trajectory
  source, file reader, menu item, map layer or form hook).
- **Sites, presets and overlays** are catalog data, not code — see
  [Catalog data](guide/catalog.md).
- Reading request arguments happens in `planning.py` only; bad input is a
  `ValueError` with a message for a person, which the web app turns into a
  JSON 400.

The frontend is plain scripts sharing one global scope, loaded in order by
`static/index.html` (state → projection → sun → map → timeline → camera → form → menus
→ files → plugins) — not ES modules.

## Documentation

This site is built with [MkDocs](https://www.mkdocs.org/) and the
[Material](https://squidfunk.github.io/mkdocs-material/) theme from `docs/`
and `mkdocs.yml`:

```bash
mkdocs serve            # live preview on http://127.0.0.1:8000
mkdocs build --strict   # what CI runs: broken links and missing pages fail
```

Every push to `main` rebuilds and publishes it to GitHub Pages
(`.github/workflows/docs.yml`); a pull request only builds it. Keep
`docs/plugins.md` in step with any change to the plugin API.

## Licence

mission-planner is licensed under
[Apache-2.0](https://github.com/hahnpv/mission-planner/blob/main/LICENSE);
contributions are accepted under the same licence.
