---
name: verify
description: Verify mission-planner changes — lint, core + plugins tests, the public/private leak guard, and a check that every built-in and plugin loaded (failures are reported, not raised). Use after editing anything in mission_planner/ or before reporting work done.
---

Run from the repo root in the conda `dev` env:

1. `ruff check .` and `ruff format --check .`.
2. `python -m pytest -q`.
3. Plugin load check — failures never raise, so read the registry:

   ```bash
   python - <<'PY'
   from mission_planner.plugins import registry
   reg = registry()
   for r in reg.records.values():
       print(f"{r.name:12} {'builtin' if r.builtin else 'plugin':8} {r.status:12} {r.error or ''}")
   bad = {r.name: r.error for r in reg.records.values() if r.status == "failed"}
   assert not bad, f"failed to load: {bad}"
   PY
   ```

   `unavailable` is expected where a plugin's external dependency is absent; report it, don't fail.
4. If anything under `mission_planner/` changed and the plugins repo is checked out alongside,
   run its tests too (`python -m pytest -q` there) — they include the public/private leak guard.

Report each step's result plainly with the failing output. Don't fix unrelated pre-existing issues.
