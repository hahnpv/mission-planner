# The web UI

```bash
python -m mission_planner.server        # http://127.0.0.1:3030
```

A local, single-page app with no external assets. It has four parts: the
**menu bar** at the top (File, View, Plugins), the **side panel** on the left,
the **map** with its playback controls, and the **status bar** along the
bottom, where every message appears (errors in red; hover a long one to read
all of it).

## Where a plan comes from

The chips at the top of the side panel pick the **trajectory source**. The
core's source is an **orbit**; plugins add others (a file, a constellation,
…), whose chips appear in the same row while the plugin is on. Each source
has a panel of its own; the epoch and propagation block and the plan button
follow once the source is ready.

### Orbit

**Shape**
:   Perigee and apogee altitude and the inclination, each a number with a
    slider under it. The altitude sliders are log-scaled from 120 to
    50 000 km, so a low orbit keeps fine resolution and GEO is within reach;
    the box takes any value. Tick **circular** to tie the apogee to the
    perigee. The **orbit** picker fills the shape from a textbook preset —
    ISS, Sun-synchronous, GPS / MEO, GTO, Molniya and GEO in the core
    catalog, plus any a data pack adds; a badge then reads *preset*, or
    *modified* once you have moved away from it. The sun-synchronous preset
    keeps the inclination at the exact SSO value for the altitude, sets the
    node from a **local time of ascending node**, and offers the
    repeat-ground-track family (12–16 revs per day).

**Anchored by**
:   How the orbit is tied to the Earth at the epoch.

    *Launch site* — the orbit plane passes over the site at the launch
    epoch. Choose a site from the catalog, type coordinates, or **pick on
    map** and click the map (Esc cancels); the picker then reads *custom
    (lat, lon)*. Choose whether the site sits on the **ascending**
    (northbound) or **descending** leg. The inclination can't be below the
    site's latitude: the slider stops there, the hint says so, and picking a
    site raises it if needed. For an elliptic orbit **perigee position**
    places perigee that many degrees downrange of the site crossing.

    *Node longitude* — no site: the ascending node sits over that longitude
    at the epoch (for GEO it is the station longitude). A preset defined by
    its elements (GTO, Molniya, GEO) switches to this anchor when picked.

**File**
:   A finished trajectory from a file: choose a stored file or upload one
    (drag and drop works). The reader that recognises the format describes
    it, offers its options, and turns it into a plan. The core reads **KML
    and KMZ** itself — a Google Earth `gx:Track` (timed) or a `LineString`
    path (untimed, sampled at a step you choose), one track per Placemark —
    which is what most tools export; other formats come from plugins.

Plugins can add more sources; their chips appear in the same row while the
plugin is on.

## Epoch and propagation

For orbit sources the block under the source panel sets:

- **epoch** (UTC) as ISO text, `YYYY-MM-DD HH:MM` — a stamp from a log
  pastes straight in (a `T`, seconds or a `Z` are fine); **now** resets it
  and the calendar button opens the browser's picker;
- **propagate**: a number of hours, days or revolutions of the current
  orbit, or one of the quick spans (1 rev, 24 h, 7 d, 30 d);
- **propagation mode**: *kepler + J2* (no drag) or *drag decay*, which asks
  for a **ballistic coefficient** β = m / (C<sub>d</sub>A) in kg/m². Plugins
  can add modes; slow ones run in the background with progress in the status
  bar.

**plan orbit** computes it; the line under the button says what will be
planned, and the button stays at the bottom of the panel as it scrolls.
With **auto** ticked beside it (the default, remembered by the browser),
once there is a plan any change to the form replans it half a second later,
keeping the time, the shown window and the vehicle in focus; picking another
source, and slow background runs, still wait for the button. The
summary below the panels shows the launch site and azimuth (for a site), the
period, revs per day and RAAN drift, and the orbital elements at the epoch.

## The map

![The globe view](../assets/ui-globe.png)

The **View** menu switches the projection:

| view | what it shows | mouse |
|---|---|---|
| **Map** | a flat map that scrolls sideways without end | drag to pan, wheel zooms about the cursor |
| **Globe** | the map on a sphere | drag to rotate, wheel zooms |
| **Orbit** | the orbit in space around the Earth, scaled to fit — best for high orbits; in the **ECI** (inertial) or **ECEF** (Earth-fixed) frame, optionally with the ground trace | drag to rotate, wheel zooms |

Double-click resets the zoom in every view. On a touch screen a finger drags,
two fingers pinch-zoom and a double tap resets.

### Camera views

The **camera** buttons at the bottom of the side panel aim the globe and
orbit views along a direction that means something. From the flat map they
switch to the orbit view.

| view | looks |
|---|---|
| **N pole** / **S pole** | down on a pole |
| **face-on** | square to the orbit plane of the track in focus — the orbit's true shape, the Earth at a focus |
| **edge-on** | in the orbit plane, along the line of nodes — the plane as a line tilted by the inclination |
| **vehicle** | straight down on the vehicle (on the flat map: centres the map on its longitude) |
| **sun** | from the sun — the lit hemisphere |

With **follow** ticked, the view stays aimed as playback runs: the orbit
plane turns under the Earth's axes, and the vehicle view becomes a chase
camera. Dragging the map lets go of the view.

**take screenshot**, in the same bar, copies the map, globe or orbit pane
as a PNG to the clipboard — plugin layers included, but not the legend of an
agent scene, which is not part of the drawing — or downloads it where the
clipboard can't take images.

![Face-on to a Molniya orbit](../assets/ui-camera-face.png)

![The orbit view: a Molniya orbit](../assets/ui-orbit.png)

The **layers** section of the View menu toggles:

- **horizon footprint at playback time** — the ground that can see the
  vehicle (0° elevation);
- **night shading** — day and night at the playback time;
- **map overlays** from data packs, one by one or all at once with
  **Hide all overlays**.

Every marker is clickable. Clicking the vehicle, a perigee / apogee marker
(**P** / **A** on elliptic orbits), the entry point or a scene marker opens a
small readout with latitude, longitude, altitude and the Earth-relative
flight-path angle γ.

## Playback and the display window

The bar under the map plays the plan back: ▶ / ❚❚, a speed (60× to 14400×),
the time slider and the UTC clock.

The **show** row above it chooses how much of the track is drawn: **1 rev**,
**90 min**, **24 h** or **all**, or drag the two handles of the window slider
for any span. The vehicle marker and footprint follow the playback time.

## Plans with several tracks

A source can return several tracks at once — a satellite constellation, or a
vehicle whose trajectory branches. The **in focus** picker below the plan
button lists them. The panels, markers and modules work on the track in
focus; the others are drawn faintly. Click a vehicle on the map to focus it.
A track may carry a colour of its own (a branch drawn in red, say); it stays
plainly visible whether it's in focus or not. Each track exists only within
its own time span: outside it the vehicle's dot and footprint are gone, in
focus or not, and a focused track that lies wholly outside the display
window draws nothing.

## Built-in panels

The panels under the form are modules. They draw on the map only while open.

**Target passes**
:   Click the map (or type a latitude, longitude) to set a target and a miss
    distance; the table lists every overflight window with UTC times, the
    closest approach, heading and leg. Click a row to jump playback there.
    On a plan with several tracks it lists every vehicle's passes, with a
    **track** column. A *pass* here is the ground track coming within that
    distance of the target — not line of sight; the horizon footprint
    answers that.

**Maneuver planner**
:   Impulsive budgets between two circular orbits: Hohmann legs, the plane
    change separate or combined into the far burn, optional co-orbital
    phasing for a target that leads by some angle, and deorbit to the 100 km
    interface.

**Drag decay**
:   After a plan in a drag mode: an altitude-vs-time sparkline (for an
    elliptic orbit, the mean altitude inside a band from perigee to apogee
    that closes as drag circularizes the orbit), and the entry
    interface crossing (and impact, for modes that fly to the ground).

### The ground-station plugin

The ground station is a plugin that ships with mission-planner in
`examples/groundstation/` and is installed with it; it is
also the worked example of the [plugin tutorial](../tutorial.md).

**Ground station**
:   Place a station (**place on map**, then click; Esc cancels) or type its
    coordinates, and set an **elevation mask** (10° by default). The panel
    says which vehicles are above the mask now, sums up the coverage (number
    of contacts, time in contact with at least one vehicle, longest gap) and
    lists the contact windows — AOS, duration, maximum elevation, azimuth
    from AOS to LOS; click one to jump there. The map shows the station and
    a dashed ring: while the vehicle's subpoint is inside it, the vehicle is
    above the mask. A View-menu toggle limits the horizon footprints to the
    vehicles above the mask. The station is remembered in this browser. The
    panel follows whatever plan is on screen; the `ground_contacts` MCP tool
    plans a Kepler orbit of its own from the shared orbit keywords (no
    `mode`/`beta`).

## Menus

**File**
:   **Export track (CSV)** — the track in focus as `utc, t_s, lat_deg,
    lon_deg, alt_km`. **Export plan (JSON)** — the whole plan as the server
    returned it. Plugins may add items.

**View**
:   Projection, orbit-view frame, layers and overlays, as above.

**Plugins**
:   Every installed plugin with what it adds, its status — active, off,
    waiting on a plugin it requires, unavailable (a missing dependency) or
    failed (with the reason) — and an on/off switch that takes effect at once,
    without a reload. The switches live on the server, so every open tab sees
    them. `MP_DISABLE_MODULES=a,b` sets which plugins start switched off.

## Plans pushed by an agent

An agent can put a plan into the open tab (the MCP tool `show_plan`, or a
scene with a `plan` posted to `/api/scene`). It replaces what's on the map as
if you had planned it yourself, with any annotations the agent added (a target
marker, a table of passes) in a legend at the top right. Plan something else
and the annotations go with it. See [Agents — MCP and REST](agents.md).
