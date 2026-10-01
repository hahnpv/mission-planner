# Getting started

## Install

mission-planner needs Python 3.12 or newer. From a checkout:

```bash
git clone https://github.com/hahnpv/mission-planner.git
cd mission-planner
pip install -e ".[ui,mcp]"
```

The library itself needs only numpy, scipy and pyyaml. The extras add the
rest:

| extra | adds | for |
|---|---|---|
| `ui` | flask | the web UI and its REST API |
| `mcp` | mcp | the MCP server for AI agents |
| `dev` | `ui` + `mcp`, pytest, ruff, playwright | working on mission-planner itself |
| `docs` | mkdocs-material | building this documentation |

## Plan an orbit in the web UI

```bash
python -m mission_planner.server
```

Open <http://127.0.0.1:3030>. The side panel starts on an **Orbit** anchored
by a **launch site**:

1. Pick a site, type a latitude and longitude, or **pick on map** and click.
2. Set the perigee altitude — untick **circular** for an apogee — and the
   inclination, or fill them from a preset with the **orbit** picker. The
   inclination can't be less than the site's latitude; the slider stops
   there and the form raises it for you when you pick a site.
3. Set the launch epoch (UTC) and how long to propagate (hours, days or
   revolutions).
4. Press **plan orbit**; the line under the button says what it will plan.

The ground track appears on the map, the orbit's elements and rates appear
below the panels, and the **status bar** along the bottom says what was
planned. Press ▶ to play it back; use **1 rev / 90 min / 24 h / all** to
choose how much of the track is drawn.

Try the **Molniya** preset (it anchors itself by node longitude instead of
a site), then **View → Orbit** to see the orbit in space. [The web UI](guide/web-ui.md) walks through everything else.

## Plan an orbit in Python

```python
from datetime import datetime, timezone
from mission_planner import Orbit, SITES

epoch = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
orb = Orbit.from_launch_site(SITES["Vandenberg"], alt_km=550, inc_deg=97.6, epoch=epoch)

s = orb.summary()
s["period_s"], s["revs_per_day"], s["raan_drift_deg_per_day"]

gt = orb.ground_track(24 * 3600)                 # a day at 30 s steps
for p in gt.passes(40.0, -105.0, within_km=300):  # overflights of a target
    print(p["ca_utc"], p["min_dist_km"], p["direction"])
```

[Python library](guide/library.md) covers orbits, propagation modes, ground
tracks and the catalog.

## Connect an AI agent

The MCP server exposes the planner as tools. Register it with your MCP
client; for Claude Code:

```bash
claude mcp add mission-planner -- python -m mission_planner.mcp_server
```

or, for a client configured with JSON:

```json
{
  "mcpServers": {
    "mission-planner": {
      "command": "python",
      "args": ["-m", "mission_planner.mcp_server"]
    }
  }
}
```

Use the Python that has mission-planner installed (a full path if your client
doesn't run in that environment). With the web UI running, `show_plan` puts
the agent's orbit straight into your browser tab. See
[Agents — MCP and REST](guide/agents.md).

## Add plugins

Anything beyond the core arrives as a plugin: an installed Python package that
registers under the `mission_planner.plugins` entry point. Install one next to
mission-planner and it appears in the UI's **Plugins** menu the next time the
server starts. To write your own, see the [Plugin guide](plugins.md).
