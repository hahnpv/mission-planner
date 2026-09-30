# Python library

Everything the UI and the MCP server do is ordinary Python you can script.
The library needs only numpy, scipy and pyyaml.

```python
from mission_planner import Orbit, GroundTrack, LaunchSite, SITES, launch_azimuth, Scene
from mission_planner import RE, MU, J2, OMEGA_E    # WGS-84 / IERS constants, SI units
```

!!! note "Units"
    The API edge speaks the units people use — kilometres and degrees —
    while everything inside is SI: metres, seconds, radians. `Orbit`
    attributes and `GroundTrack` arrays are therefore in metres and radians;
    constructors, `summary()` and `passes()` are in km and degrees.

## Orbits

An `Orbit` holds classical elements at a UTC epoch: `a` (m), `e`, `inc`,
`raan`, `argp`, `m0` (radians) and `epoch`. Build one with a constructor.

### Over a launch site

```python
from datetime import datetime, timezone
from mission_planner import Orbit, SITES, LaunchSite

epoch = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
orb = Orbit.from_launch_site(SITES["Cape Canaveral / KSC"], alt_km=400, inc_deg=51.6, epoch=epoch)

# a site of your own, the descending leg, an ellipse with perigee 90 deg downrange
home = LaunchSite("home", 52.0, 4.4)
ell = Orbit.from_launch_site(home, inc_deg=60, epoch=epoch, ascending=False,
                             perigee_km=300, apogee_km=1200, perigee_offset_deg=90)
```

The orbit's plane contains the site at the epoch, so the vehicle is overhead
at t = 0. `ascending=True` puts the site on the northeast-going leg.
`perigee_offset_deg` places perigee that many degrees downrange of the site
crossing (0 = perigee over the site, 180 = apogee over it). An inclination
below the site's latitude raises `ValueError`.

### From elements

```python
molniya = Orbit.from_elements(500, 39868, 63.4, epoch, node_lon_deg=65, argp_deg=270)
geo = Orbit.from_elements(35786, 35786, 0.0, epoch, node_lon_deg=-100)   # station at 100 W
```

`from_elements(perigee_km, apogee_km, inc_deg, epoch, node_lon_deg=0,
argp_deg=0, nu0_deg=None)` anchors the orbit to the Earth by the longitude of
its ascending node at the epoch — no launch site. Propagation starts at the
node unless `nu0_deg` (true anomaly at the epoch) is given. For GEO the node
longitude is the station longitude.

`Orbit.circular(alt_km, inc_deg, raan_deg=0, u0_deg=0, epoch=None)` builds a
circular orbit from an inertial RAAN and an argument of latitude.

Epochs are timezone-aware UTC; a naive `datetime` is taken as UTC, and a
missing epoch means now.

### What an orbit tells you

```python
orb.summary()
```

| key | meaning |
|---|---|
| `alt_km`, `perigee_km`, `apogee_km`, `a_km`, `e` | size and shape |
| `inc_deg`, `raan_deg`, `argp_deg`, `nu0_deg` | orientation and phase at the epoch |
| `period_s` | anomalistic period (perigee to perigee), J2-corrected |
| `nodal_period_s`, `revs_per_day` | node to node — the period ground-track repeats are quoted in |
| `raan_drift_deg_per_day`, `argp_drift_deg_per_day` | J2 secular drift |
| `epoch_utc` | ISO 8601 |

Other methods:

| method | returns |
|---|---|
| `launch_azimuth_deg(site_lat_deg, ascending=True)` | the azimuth to launch into this orbit, with the rotating-Earth correction |
| `subpoints(t)` | sub-satellite latitude, longitude (radians, Earth-fixed) and radius (m) at seconds-past-epoch `t` |
| `eci_positions(t)` | ECI positions, shape (N, 3), m |
| `eci_state(t=0)` | ECI position (m) and velocity (m/s) — good for seeding a higher-fidelity propagator |
| `argument_of_latitude(t)` | where the vehicle is along the orbit, from the ascending node |
| `apsis_times()` | the first perigee and apogee times after the epoch, s |
| `j2_rates()` | secular (RAAN, argument of perigee, mean anomaly) rates, rad/s |

## Propagation

```python
gt = orb.ground_track(duration_s=24 * 3600, dt_s=30.0)                      # kepler + J2
gt = orb.ground_track(14 * 86400, 60.0, mode="decay", beta=300.0)          # drag decay
```

| mode | physics | stops at |
|---|---|---|
| `"kepler"` | two-body plus J2 secular drift of the node, perigee and mean motion | never |
| `"decay"` | averaged King-Hele drag decay in a co-rotating US 1976 atmosphere; needs `beta` = m / (C<sub>d</sub>A), kg/m², and a near-circular orbit (e ≤ 0.05) | the 100 km entry interface |
| a plugin's mode | whatever that plugin flies | — |

A decay track carries `gt.extra["decay_profile"]` (a decimated
altitude-vs-time series for plotting) and `gt.extra["entry"]` — the UTC,
time and subpoint of the entry-interface crossing, or `None` if the orbit
survives the horizon. See [Models and assumptions](models.md) for what the
decay model leaves out.

## Ground tracks

A `GroundTrack` is one vehicle's samples: `epoch`, and arrays `t` (seconds
past the epoch), `lat`, `lon` (radians) and `alt` (metres), plus `extra` for
mode-specific payloads. `id`, `label`, `parent` and `color` tell tracks apart
when a plan holds several.

```python
for p in gt.passes(40.0, -105.0, within_km=500):
    print(p["ca_utc"], p["min_dist_km"], p["heading_deg"], p["direction"])
# 2026-10-01T15:11:00+00:00 380.5 57.1 ascending
```

`passes(tgt_lat_deg, tgt_lon_deg, within_km=500, max_passes=200)` finds every
window in which the subpoint comes within `within_km` of the target. Each
window has `aos_utc` / `los_utc` (entering and leaving the circle), `ca_utc`
and `ca_t_s` (closest approach), `min_dist_km`, `heading_deg`, `direction`
(`"ascending"` or `"descending"`) and `alt_km`. This is ground-track
proximity, not line of sight.

`gt.heading` gives the ground-track heading at each sample, and
`gt.to_json()` the plain-JSON form the UI draws (degrees, km).

## Launch sites

`SITES` is a live, read-only mapping of the catalog's launch sites: the core's
plus any a data pack adds (see [Catalog data](catalog.md)). A site of your own
needs no catalog entry — just `LaunchSite(name, lat_deg, lon_deg)`.

`launch_azimuth(lat_deg, inc_deg, ascending=True, v_orbit=None)` is the bare
geometry: the inertial azimuth to reach an inclination from a latitude, or,
with an orbital speed in m/s, the azimuth corrected for the Earth's rotation.

## Plans as the UI makes them

`mission_planner.planning` turns request arguments into orbits and plans, and
is what the web server, the MCP server and plugins all share:

```python
from mission_planner import planning

args = {"source": "site", "site": "Vandenberg", "hp": 550, "inc": 97.6,
        "epoch": "2026-10-01T12:00:00Z", "hours": 24}
plan = planning.plan_from_args(args)      # the /api/plan JSON: summary + track
orb, meta = planning.orbit_from_args(args)
```

`args_from_params(...)` converts the MCP tools' keyword style into these
arguments. Bad input raises `ValueError` with a message meant for a person.

## Scenes

A `Scene` is a small drawing document for the UI — tracks, markers, polygons,
labels and tables, and optionally a whole plan — that an agent or a script
pushes to the running server. See [Agents — MCP and REST](agents.md#scenes).
