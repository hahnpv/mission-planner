"""Sun-synchronous presets (built in) -- the preset family whose elements
follow from the user's other choices instead of being fixed numbers.

UI only (static/modules/sso.js), over the form hooks (ctx.onPreset /
onShapeChange / getShape / setShape / presetControls).  For a catalog preset
with `sun_synchronous: true` it keeps the inclination at the exact SSO value
for the current perigee/apogee (J2 nodal regression of +0.9856 deg/day),
turns a local time of ascending node (LTAN) into the node longitude at the
epoch (mean sun), and offers the repeat-ground-track family (12-16 revs per
day) as variants.  It works on the form, not on a plan, so it stays live
whatever kind of plan is on screen: a source with presets of its own (a
constellation's, say) can mark one `sun_synchronous` too.
"""

MODULE = {
    "api": 1,
    "name": "sso",
    "title": "sun-synchronous presets",
    "js": "sso.js",
    "works_with": ["orbit", "trajectory"],
}
