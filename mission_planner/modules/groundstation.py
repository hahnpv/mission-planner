"""Ground station: a place on the ground to watch the vehicles from.

UI only (static/modules/groundstation.js): place the station on the map (an
explicit "place on map", then a click; or type lat/lon), see which vehicles
have it inside their horizon footprint right now and at what elevation, and
— a View menu toggle — show the horizon footprints of exactly those vehicles
(through the core's footprint filter hook).  Visibility is geometric, 0 deg
elevation on the spherical Earth: the footprint the map draws.  The station
is kept in the viewer's browser.
"""

MODULE = {
    "api": 1,
    "name": "groundstation",
    "title": "ground station",
    "js": "groundstation.js",
    "works_with": ["orbit", "trajectory"],
}
