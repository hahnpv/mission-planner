"""Built-in capability modules — core features on the plugin contract.

Each file here exposes a `MODULE` spec (full key list in plugins.py) and is
always active; external plugins use the same contract but arrive through the
`mission_planner.plugins` entry-point group and can be switched live.

The UI side of a module is its `js` asset, which calls
`MP.register({title, html, open?, init(ctx)})`.  `ctx` carries
`api`/`status`/`redraw`, `getPlan()`/`planArgs()`, `onPlan(cb)`,
`isOpen()`/`onToggle(cb)` for the module's own collapsible panel,
`onDraw(fn)`/`onDrawOver(fn)` for map layers under/over the ground track,
`onClick(fn)` for map clicks, `addDisplayToggle(label, checked, cb)` for a
row in the core display menu, and `seek(t_s)` to move playback.  A module
that draws on the map gates on `isOpen()`: a closed panel (or a switched-off
plugin) puts nothing on the map and makes no requests.  Hooks registered
through `ctx` go inert automatically while their plugin is inactive.
"""
