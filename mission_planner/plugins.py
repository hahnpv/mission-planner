"""Plugin API v1 — how capability code and data packs attach to the core.

The authoring guide is docs/plugins.md; this docstring is the reference.

Two sources, one spec format:

- **built-ins**: files in `mission_planner/modules/`.  Core features built on
  the same contract; always active, never listed in the UI's Plugins menu.
- **plugins**: installed packages that declare an entry point in the
  `mission_planner.plugins` group, e.g. in their pyproject.toml::

      [project.entry-points."mission_planner.plugins"]
      example = "my_plugins.example:MODULE"

A spec is a dict (conventionally `MODULE`); every key but `name` is optional::

    api          int    plugin API version targeted (default 1; > API_VERSION fails)
    name         str    slug: the dependency handle and MP_DISABLE_MODULES key
    title        str    UI label
    description  str    one line for the Plugins menu
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
    sources      {id: {"fn": fn(args) -> (Orbit | GroundTrack, meta dict),
                       "label": str, "kind": "orbit" | "trajectory", "slow": bool}}
                        trajectory sources beside the core's site/preset: where a
                        plan comes from.  An "orbit" source returns an Orbit that
                        is then propagated (mode/hours/dt); a "trajectory" source
                        returns a finished GroundTrack.  `args` are the request's
                        query args (`source=<id>` plus whatever its UI sends); meta
                        joins the plan summary; a "slow" trajectory source runs as
                        a background job in the UI.  The UI half is ctx.addSource.
    file_readers {id: {"label": str, "extensions": [str],
                       "detect": fn(path) -> bool,
                       "inspect": fn(path) -> dict,
                       "read": fn(path, args) -> (GroundTrack, meta dict)}}
                        file formats a plan can come from (the built-in "File"
                        source, modules/files.py; library side filekinds.py).
                        `detect` answers "is this mine?" cheaply (headers, not
                        data) and is run once per upload; `inspect` feeds the
                        source panel (summary, warning, epoch default, option
                        choices: see docs/plugins.md); `read` makes the plan,
                        `args` being the request's query args
    works_with   [kind] trajectory kinds the module's UI and routes make sense for
                        (default ["orbit"]); against any other plan it goes inert
                        in the UI as if switched off

Every key is type-checked at load; a bad spec makes the plugin **failed**
with the reason, never a crash.  Names that must be unique across the core
and every plugin — mode ids, source ids, file reader ids, blueprint names and
MCP tool names —
are checked in load order: a later plugin that reuses one fails, naming the
earlier owner.

Dependency chains
-----------------
- Load time: a plugin is **failed** if it didn't import or its spec is invalid
  (every member of a `requires` cycle is failed), and **unavailable** if a
  requirement is missing / failed / unavailable, or its own `available()`
  returns a reason.  The reason always names the broken link.
- Run time: a plugin is **active** when it loaded, its own switch is on, and
  every requirement is active (transitively).  Switching a plugin on also
  switches on its requirements; switching one off leaves dependents' switches
  alone — they go inactive and report which requirement they're waiting on.
- MP_DISABLE_MODULES=a,b sets the starting switches (an unknown name is
  reported on stderr and ignored).  Built-ins can't be switched off.
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
CORE_SOURCES = ("site", "preset")  # launch site / element-anchored preset (planning.py)
CORE_MCP_TOOLS = ("plan_orbit", "list_launch_sites", "show_scene", "show_plan")  # mcp_server.py
KINDS = ("orbit", "trajectory")

# (key, builtin, loader) — loader returns the spec, or None for a helper file.
Source = tuple[str, bool, Callable[[], dict | None]]


class PluginError(RuntimeError):
    """A plugin's own code raised while serving a request (the servers report
    it as a 500 that names the plugin, unlike a ValueError from bad input)."""


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

    def fail(self, error: str):
        self.status, self.error = "failed", error


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


def _is_path(x) -> bool:
    return isinstance(x, (str, os.PathLike))


def _spec_error(spec) -> str | None:
    """Why `spec` is not a valid plugin spec, or None."""
    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str) or not spec["name"]:
        return "spec must be a dict with a non-empty string 'name'"
    api = spec.get("api", 1)
    if not isinstance(api, int) or api > API_VERSION:
        return f"targets plugin API {api!r}; this core provides {API_VERSION}"
    for key in ("title", "description", "js"):
        if key in spec and not isinstance(spec[key], str):
            return f"'{key}' must be a string"
    req = spec.get("requires", [])
    if not isinstance(req, (list, tuple)) or not all(isinstance(r, str) for r in req):
        return "'requires' must be a list of plugin names"
    if "available" in spec and not callable(spec["available"]):
        return "'available' must be a callable returning a reason or None"
    bp = spec.get("blueprint")
    if bp is not None and not (
        isinstance(getattr(bp, "name", None), str) and hasattr(bp, "register")
    ):
        return "'blueprint' must be a flask Blueprint"
    for key in ("static_dir", "catalog"):
        if key in spec and not _is_path(spec[key]):
            return f"'{key}' must be a path"
    tools = spec.get("mcp_tools", [])
    if not isinstance(tools, (list, tuple)) or not all(callable(t) for t in tools):
        return "'mcp_tools' must be a list of functions"
    ww = spec.get("works_with", ["orbit"])
    if not isinstance(ww, (list, tuple)) or not set(ww) <= set(KINDS):
        return f"'works_with' must be a list of {'/'.join(KINDS)}"
    props = spec.get("propagators", {})
    if not isinstance(props, dict):
        return "'propagators' must be a dict of mode -> propagator spec"
    for mode, pp in props.items():
        if not isinstance(mode, str) or mode in CORE_MODES:
            return f"mode {mode!r} is not a valid plugin mode id (core: {'/'.join(CORE_MODES)})"
        if not isinstance(pp, dict) or not callable(pp.get("fn")):
            return f"mode '{mode}' needs a callable 'fn'"
    sources = spec.get("sources", {})
    if not isinstance(sources, dict):
        return "'sources' must be a dict of id -> source spec"
    for sid, sp in sources.items():
        if not isinstance(sid, str) or sid in CORE_SOURCES:
            return (
                f"source {sid!r} is not a valid plugin source id (core: {'/'.join(CORE_SOURCES)})"
            )
        if not isinstance(sp, dict) or not callable(sp.get("fn")):
            return f"source '{sid}' needs a callable 'fn'"
        if sp.get("kind") not in KINDS:
            return f"source '{sid}' kind must be one of {'/'.join(KINDS)}"
    readers = spec.get("file_readers", {})
    if not isinstance(readers, dict):
        return "'file_readers' must be a dict of id -> reader spec"
    for rid, rp in readers.items():
        if not isinstance(rid, str) or not rid:
            return f"file reader id {rid!r} must be a non-empty string"
        if not isinstance(rp, dict):
            return f"file reader '{rid}' must be a dict"
        for fn in ("detect", "inspect", "read"):
            if not callable(rp.get(fn)):
                return f"file reader '{rid}' needs a callable '{fn}'"
        if not isinstance(rp.get("label", ""), str):
            return f"file reader '{rid}' label must be a string"
        exts = rp.get("extensions", [])
        if not isinstance(exts, (list, tuple)) or not all(
            isinstance(e, str) and e.startswith(".") for e in exts
        ):
            return f"file reader '{rid}' extensions must be a list like ['.h5']"
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
        self._check_unique()
        self._resolve()
        off = disabled_by_env()
        for unknown in sorted(off - set(self.records)):
            print(
                f"[mission_planner.plugins] MP_DISABLE_MODULES: no plugin '{unknown}'",
                file=sys.stderr,
            )
        for r in self.records.values():
            r.enabled = r.builtin or r.name not in off

    def _add(self, rec: Record):
        if rec.name in self.records:
            base, n = rec.name, 1
            while f"{base}#dup{n}" in self.records:
                n += 1
            rec = Record(f"{base}#dup{n}", rec.builtin, "failed", f"duplicate name '{base}'")
        self.records[rec.name] = rec

    def _check_unique(self):
        """Ids that must be unique across the core and all plugins: the first
        loaded owner keeps them; a later plugin reusing one is failed."""
        owners: dict[tuple[str, str], str] = {}
        for mode in CORE_MODES:
            owners[("mode", mode)] = "core"
        for sid in CORE_SOURCES:
            owners[("source", sid)] = "core"
        for tool in CORE_MCP_TOOLS:
            owners[("MCP tool", tool)] = "core"
        for r in self.records.values():
            if r.status != "loaded":
                continue
            claims = [("mode", m) for m in r.get("propagators") or {}]
            claims += [("source", s) for s in r.get("sources") or {}]
            claims += [("file reader", f) for f in r.get("file_readers") or {}]
            claims += [("MCP tool", fn.__name__) for fn in r.get("mcp_tools", [])]
            if r.get("blueprint") is not None:
                claims.append(("blueprint", r.get("blueprint").name))
            for claim in claims:
                owner = owners.get(claim)
                if owner is not None:
                    r.fail(f"{claim[0]} '{claim[1]}' is already provided by {owner}")
                    break
            else:
                for claim in claims:
                    owners[claim] = f"plugin '{r.name}'"

    def _resolve(self):
        done: set[str] = set()

        def check(name: str, stack: tuple[str, ...]):
            r = self.records[name]
            if name in done or r.status != "loaded":
                return
            for dep in r.requires:
                chain = stack + (name,)
                if dep in chain:
                    members = chain[chain.index(dep) :]
                    cycle = " -> ".join(members + (dep,))
                    for m in members:  # every member of the cycle is broken
                        self.records[m].fail(f"dependency cycle: {cycle}")
                    break
                d = self.records.get(dep)
                if d is None:
                    r.status, r.error = "unavailable", f"requires '{dep}', which is not installed"
                    break
                check(dep, chain)
                if r.status != "loaded":  # failed as a member of a cycle found below
                    break
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
                    r.status, r.error = "unavailable", str(reason)
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

    def _provided(self, key: str, item: str, what: str, core: tuple[str, ...]) -> dict:
        """The spec for `item` under plugin spec key `key`, if its plugin is active;
        otherwise a ValueError naming the plugin and why (or the known items)."""
        for r in self.records.values():
            sp = (r.get(key) or {}).get(item)
            if sp is None:
                continue
            if self.active(r.name):
                return sp
            why = r.error or (
                f"waiting on '{self.waiting_on(r.name)}'" if r.enabled else "switched off"
            )
            raise ValueError(f"{what} {item!r} comes from plugin '{r.name}', which is {why}")
        known = list(core) + [x for r in self.active_records() for x in r.get(key) or {}]
        raise ValueError(f"unknown {what} {item!r} ({'|'.join(known)})")

    def propagator(self, mode: str) -> dict:
        """The propagator spec for a plugin-provided mode, if its plugin is active."""
        return self._provided("propagators", mode, "mode", CORE_MODES)

    def source(self, sid: str) -> dict:
        """The spec for a plugin-provided trajectory source, if its plugin is active."""
        return self._provided("sources", sid, "source", CORE_SOURCES)

    def file_readers(self) -> dict[str, dict]:
        """{reader id: spec} of every active plugin's file readers, in load order."""
        return {
            rid: rp
            for r in self.active_records()
            for rid, rp in (r.get("file_readers") or {}).items()
        }

    def file_reader(self, rid: str) -> dict:
        """The spec for file reader `rid`, if its plugin is active."""
        return self._provided("file_readers", rid, "file reader", ())

    def owner_of(self, key: str, item: str) -> str | None:
        """Name of the plugin providing `item` under spec key `key`, if any."""
        for r in self.records.values():
            if item in (r.get(key) or {}):
                return r.name
        return None

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
