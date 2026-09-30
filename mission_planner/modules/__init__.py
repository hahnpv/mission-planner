"""Built-in capability modules — core features on the plugin contract.

Each file here exposes a `MODULE` spec (key reference in plugins.py) and is
always active; external plugins use the same contract but arrive through the
`mission_planner.plugins` entry-point group and can be switched live.

The UI side of a module is its `js` asset, which calls
`MP.register({title, html, open?, init(ctx)})`.  The full `ctx` and
draw-context reference, with examples of every capability, is the plugin
authoring guide, docs/plugins.md.  In short: `ctx` carries `api` / `status`
/ `redraw`, `getPlan()` / `planArgs()`, `onPlan(cb)`, `isOpen()` /
`onToggle(cb)` for the module's collapsible panel, `onDraw(fn)` /
`onDrawOver(fn)` for map layers under / over the ground track, `onClick(fn)`
for map clicks, `addDisplayToggle` / `addMenuItem` for menu rows, `seek(t_s)`
to move playback, `addSource` / `updateSource` for a trajectory source's
UI half, and `onPreset` / `onShapeChange` / `getShape` / `setShape` /
`presetControls` for a preset family with rules of its own.  A module that draws on the map gates on `isOpen()`, draws only
through the draw context (`d.polyline`, `d.polygon`, `d.marker`,
`d.project`), and uses stable `marker()` keys; hooks registered through
`ctx` go inert automatically while their plugin is inactive.

Modules here: passes (overflight windows), maneuvers (impulsive budgets),
decay (the drag-decay readout panel), files (the "File" trajectory source
over plugins' file readers), sso (sun-synchronous
presets: inclination from altitude, node from LTAN, repeat-track variants).
"""
