"""Plugin API v1 — how capability code and data packs attach to the core.

Two sources, one spec format:

- **built-ins**: files in `mission_planner/modules/`.  Core features built on
  the same contract; always active, never listed in the UI's plugins box.
- **plugins**: installed packages that declare an entry point in the
  `mission_planner.plugins` group, e.g. in their pyproject.toml::

      [project.entry-points."mission_planner.plugins"]
      example = "my_plugins.example:MODULE"

A spec is a dict (conventionally `MODULE`); every key but `name` is optional::

    api          int    plugin API version targeted (default 1; > API_VERSION fails)
    name         str    slug: the dependency handle and MP_DISABLE_MODULES key
    title        str    UI label
    description  str    one line for the plugins box
    requires     [str]  names of plugins this one needs (dependency chains, below)
    available    () -> str | None
                        runtime precondition, checked once at load; returns the
                        reason it's unmet (e.g. an external binary is missing)
    blueprint    flask.Blueprint   REST routes (gated live on the plugin being active)
    js           str    UI asset in `static_dir`, calling MP.register (see modules/)
    static_dir   path   where `js` lives (built-ins default to core static/modules/)
    mcp_tools    [fn]   functions the MCP server exposes as tools
    propagators  {mode: {"fn": fn(orbit, beta, duration_s, dt_s) -> GroundTrack,
                         "label": str, "needs_beta": bool, "slow": bool}}
                        extra propagation modes beside the core's kepler/decay;
                        "slow" ones run as background jobs in the UI
    catalog      path   data-pack directory (sites/presets/overlays; see catalog.py)

Dependency chains
-----------------
- Load time: a plugin is **failed** if it didn't import or its spec is invalid
  (including being part of a `requires` cycle), and **unavailable** if a
  requirement is missing / failed / unavailable, or its own `available()`
  returns a reason.  The reason always names the broken link.
- Run time: a plugin is **active** when it loaded, its own switch is on, and
  every requirement is active (transitively).  Switching a plugin on also
  switches on its requirements; switching one off leaves dependents' switches
  alone — they go inactive and report which requirement they're waiting on.
- MP_DISABLE_MODULES=a,b sets the starting switches.  Built-ins can't be
  switched off.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

API_VERSION = 1
GROUP = "mission_planner.plugins"
CORE_STATIC = Path(__file__).parent / "static" / "modules"
CORE_CATALOG = Path(__file__).parent / "data" / "catalog"
CORE_MODES = ("kepler", "decay")

# (key, builtin, loader) — loader returns the spec, or None for a helper file.
Source = tuple[str, bool, Callable[[], dict | None]]


@dataclass
class Record:
    name: str
    builtin: bool
    status: str  # "loaded" | "failed" | "unavailable"
    error: str | None = None
    spec: dict | None = None
    enabled: bool = True

    def get(self, key, default=None):
        return (self.spec or {}).get(key, default)

    @property
    def requires(self) -> list[str]:
        return list(self.get("requires", []))


def disabled_by_env() -> set[str]:
    return {s.strip() for s in os.environ.get("MP_DISABLE_MODULES", "").split(",") if s.strip()}


def builtin_sources() -> Iterable[Source]:
    from . import modules

    for info in pkgutil.iter_modules(modules.__path__):
        name = f"{modules.__name__}.{info.name}"
        yield info.name, True, lambda n=name: getattr(importlib.import_module(n), "MODULE", None)


def entry_point_sources() -> Iterable[Source]:
    for ep in entry_points(group=GROUP):
        yield ep.name, False, ep.load


def _spec_error(spec) -> str | None:
    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
        return "spec must be a dict with a string 'name'"
    api = spec.get("api", 1)
    if not isinstance(api, int) or api > API_VERSION:
        return f"targets plugin API {api!r}; this core provides {API_VERSION}"
    req = spec.get("requires", [])
    if not isinstance(req, (list, tuple)) or not all(isinstance(r, str) for r in req):
        return "'requires' must be a list of plugin names"
    return None


class Registry:
    def __init__(self, sources: Iterable[Source]):
        self.records: dict[str, Record] = {}
        for key, builtin, load in sources:
            try:
                spec = load()
            except Exception as e:  # never let one plugin break the core
                print(f"[mission_planner.plugins] skipping {key}: {e}", file=sys.stderr)
                self._add(Record(key, builtin, "failed", f"{type(e).__name__}: {e}"))
                continue
            if spec is None:
                continue  # a helper file in modules/, not a module
            err = _spec_error(spec)
            name = spec["name"] if err is None else key
            self._add(Record(name, builtin, "failed" if err else "loaded", err, spec))
        self._resolve()
        off = disabled_by_env()
        for r in self.records.values():
            r.enabled = r.builtin or r.name not in off

    def _add(self, rec: Record):
        if rec.name in self.records:
            rec = Record(rec.name + "#dup", rec.builtin, "failed", f"duplicate name '{rec.name}'")
        self.records[rec.name] = rec

    def _resolve(self):
        done: set[str] = set()

        def check(name: str, stack: tuple[str, ...]):
            r = self.records[name]
            if name in done or r.status != "loaded":
                return
            for dep in r.requires:
                if dep in stack + (name,):
                    cycle = " -> ".join(stack[stack.index(dep) :] + (name, dep))
                    r.status, r.error = "failed", f"dependency cycle: {cycle}"
                    break
                d = self.records.get(dep)
                if d is None:
                    r.status, r.error = "unavailable", f"requires '{dep}', which is not installed"
                    break
                check(dep, stack + (name,))
                if d.status != "loaded":
                    r.status, r.error = "unavailable", f"requires '{dep}' ({d.status}: {d.error})"
                    break
            else:
                avail = r.get("available")
                try:
                    reason = avail() if avail else None
                except Exception as e:
                    reason = f"availability check raised {type(e).__name__}: {e}"
                if reason:
                    r.status, r.error = "unavailable", reason
            done.add(name)

        for name in list(self.records):
            check(name, ())

    # ------------------------------------------------------------ run time
    def active(self, name: str) -> bool:
        r = self.records.get(name)
        return (
            r is not None
            and r.status == "loaded"
            and r.enabled
            and all(self.active(d) for d in r.requires)
        )

    def waiting_on(self, name: str) -> str | None:
        """First requirement keeping an enabled, loaded plugin inactive."""
        r = self.records[name]
        if r.status != "loaded" or not r.enabled:
            return None
        return next((d for d in r.requires if not self.active(d)), None)

    def set_enabled(self, name: str, on: bool):
        r = self.records.get(name)
        if r is None:
            raise KeyError(name)
        if r.builtin:
            raise ValueError(f"'{name}' is built in and always on")
        if r.status != "loaded":
            raise ValueError(f"plugin '{name}' is {r.status}: {r.error}")
        r.enabled = on
        if on:
            for dep in r.requires:
                if not self.records[dep].builtin:
                    self.set_enabled(dep, True)

    def active_records(self) -> list[Record]:
        return [r for r in self.records.values() if self.active(r.name)]

    def propagator(self, mode: str) -> dict:
        """The propagator spec for a plugin-provided mode, if its plugin is active."""
        for r in self.records.values():
            p = (r.get("propagators") or {}).get(mode)
            if p is None:
                continue
            if self.active(r.name):
                return p
            why = r.error or (
                f"waiting on '{self.waiting_on(r.name)}'" if r.enabled else "switched off"
            )
            raise ValueError(f"mode {mode!r} comes from plugin '{r.name}', which is {why}")
        known = list(CORE_MODES) + [
            m for r in self.active_records() for m in r.get("propagators") or {}
        ]
        raise ValueError(f"unknown mode {mode!r} ({'|'.join(known)})")

    def catalog_dirs(self) -> list[tuple[str, Path]]:
        """(pack name, dir) in load order: the core's own catalog first."""
        dirs = [("core", CORE_CATALOG)]
        for r in self.active_records():
            if r.get("catalog"):
                dirs.append((r.name, Path(r.get("catalog"))))
        return dirs

    def static_dir(self, name: str) -> Path | None:
        r = self.records.get(name)
        if r is None or r.status != "loaded":
            return None
        return Path(r.get("static_dir") or CORE_STATIC)


_REGISTRY: Registry | None = None


def registry() -> Registry:
    """The process-wide registry: built-ins plus installed plugins, loaded once."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry([*builtin_sources(), *entry_point_sources()])
    return _REGISTRY
