# Catalog data

Launch sites, orbit presets and map overlays are **data**, not code. The core
ships a small catalog of well-known public sites and textbook orbits;
**data packs** add more, and the lists in the UI, the REST API and the MCP
tools are always the core's items plus those of every active pack.

## What the core ships

**Launch sites** — Cape Canaveral / KSC, Vandenberg, Wallops, Kodiak,
Boca Chica, Kourou, Baikonur, Mahia.

**Orbit presets** — anchored by elements, not a launch site:

| preset | perigee × apogee (km) | inclination | notes |
|---|---|---|---|
| ISS | 400 circular | 51.6° | |
| Sun-synchronous | 700 circular | 98.2° | the SSO rules apply: exact inclination, LTAN, repeat-track variants |
| GPS / MEO | 20180 circular | 55° | |
| GTO | 250 × 35786 | 28.5° | argument of perigee 180° |
| Molniya | 500 × 39868 | 63.4° | argument of perigee 270°, node at 65° E |
| GEO | 35786 circular | 0° | station at 100° W |

**Map overlays** — none. Overlays are always data-pack content.

## The formats

A catalog directory holds any of these files:

```text
my_catalog/
├── sites.yaml
├── presets.yaml
└── overlays/
    ├── test_area.geojson
    └── test_area.yaml
```

### `sites.yaml`

```yaml
- {name: "Home field", lat: 52.0, lon: 4.4}      # degrees, geocentric
```

### `presets.yaml`

```yaml
- {name: Polar 600, perigee_km: 600, inc_deg: 90}
- {name: Tundra, perigee_km: 24000, apogee_km: 47000, inc_deg: 63.4, argp_deg: 270, node_lon_deg: -90}
- {name: Dawn-dusk SSO, perigee_km: 750, inc_deg: 98.4, sun_synchronous: true}
```

| key | required | meaning |
|---|---|---|
| `name` | yes | the label in the preset list |
| `perigee_km`, `inc_deg` | yes | |
| `apogee_km` | no | default: circular |
| `argp_deg` | no | argument of perigee, default 0 |
| `node_lon_deg` | no | longitude of the ascending node at the epoch (GEO: the station), default 0 |
| `sun_synchronous` | no | `true` hands the preset to the sun-synchronous rules |

A preset can instead be a **file preset**, `{name, file_from: <route>}`: a
plugin route that stores a file and answers with its upload. Choosing it
opens that file in the File source and plans it — a way to offer, for
instance, a live satellite constellation from an element-set service.

### Overlays

`overlays/<id>.geojson` is the shape (polygons and multipolygons, in
longitude/latitude); `overlays/<id>.yaml` beside it describes it:

```yaml
title: Test area
style: {color: "#d03b3b", opacity: 0.16}
source: {name: "where the data came from", url: "https://example.org"}
```

Each overlay gets its own tick in **View → map overlays**, and **Hide all
overlays** hides them all at once. The choices are kept in the browser.

## Making a data pack

A data pack is a plugin whose spec has only a `catalog` key — no code:

```python
# my_pack/__init__.py
from pathlib import Path

MODULE = {"api": 1, "name": "my_pack", "title": "my sites and presets",
          "catalog": Path(__file__).parent / "catalog"}
```

Register it under the `mission_planner.plugins` entry point and install it
(see the [Plugin guide](../plugins.md)). Its items join the lists while it is
switched on, each tagged with the pack's name, and a later pack's item
replaces an earlier one of the same name. The files are re-read when they
change on disk, so you can edit a YAML file while the server runs.
