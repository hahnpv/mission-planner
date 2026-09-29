"""Request parameters -> Orbit / GroundTrack / map payload.

Shared by the web server, the MCP server and plugins, so every surface reads
an orbit from its parameters the same way: `orbit_from_args` is the one
reader (query-string style args), and `orbit_from_params` (MCP-tool style
keywords) builds the same args and delegates to it.  No flask here: plugins
import it at module scope.

Bad input is a ValueError with a message meant for the user (the servers
turn it into HTTP 400 / a tool error).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from .constants import RE
from .launch_site import SITES, LaunchSite
from .orbit import Orbit
from .plugins import CORE_SOURCES, PluginError
from .timebase import now_utc

DEFAULT_SITE = "Cape Canaveral / KSC"
# Ceiling on samples per track: 200k points is ~20 MB of JSON and a few
# hundred ms to compute; anything beyond that is a mistake in hours/dt.
MAX_TRACK_POINTS = 200_000
# The UI's rule for a sample step that keeps long horizons at a sane point count.
TARGET_POINTS = 20_000


def parse_epoch(s: str | None) -> datetime:
    if not s:
        return now_utc()
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"epoch {s!r} is not an ISO 8601 date-time (e.g. 2026-08-23T00:00:00Z)")


def opt_float(a, key: str, default: float | None = None) -> float | None:
    """`a[key]` as a float; a missing or empty value gives `default`."""
    v = a.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number, not {v!r}")


def req_float(a, key: str, default: float) -> float:
    return opt_float(a, key, default)


def default_dt(hours: float, floor: float = 30.0) -> float:
    """Sample step [s] for a horizon: `floor` until the track would exceed
    TARGET_POINTS samples, then coarser (the UI's rule)."""
    return max(floor, round(hours * 3600.0 / TARGET_POINTS / 10.0) * 10.0)


def source_of(a) -> str:
    """The trajectory source a request names: `source=`, else the pre-source
    convention (anchor=elements for a preset, a launch site otherwise)."""
    return a.get("source") or ("preset" if a.get("anchor") == "elements" else "site")


def _plugin_source(sid: str) -> dict:
    from .plugins import registry

    return registry().source(sid)


def _call_plugin(sid: str, sp: dict, a):
    try:
        return sp["fn"](a)
    except ValueError:
        raise
    except Exception as e:  # the plugin's bug: a 500 that names it, not a bare traceback
        from .plugins import registry

        owner = registry().owner_of("sources", sid)
        raise PluginError(
            f"source {sid!r} (plugin '{owner}') failed: {type(e).__name__}: {e}"
        ) from e


def resolve_site(a) -> LaunchSite:
    """The launch site a request names: `site=<catalog name>` (an unknown name
    is an error), or `lat`/`lon` for a custom site (`site` then labels it),
    or the default site when neither is given."""
    name = a.get("site") or ""
    lat = opt_float(a, "lat")
    if lat is not None:
        return LaunchSite(name or "custom", lat, opt_float(a, "lon", 0.0))
    if not name:
        name = DEFAULT_SITE
    site = SITES.get(name)
    if site is None:
        raise ValueError(f"unknown launch site {name!r}; pass lat/lon or one of {list(SITES)}")
    return site


def orbit_from_args(a) -> tuple[Orbit, dict]:
    """Orbit from the web UI's query args: a core source (site: hp/ha/inc/epoch/
    site|lat,lon/leg/pofs; preset: the same shape plus node_lon/argp) or a
    plugin's orbit source.  A trajectory source has no orbit: ValueError."""
    sid = source_of(a)
    if sid not in CORE_SOURCES:
        sp = _plugin_source(sid)
        if sp["kind"] != "orbit":
            raise ValueError(f"source {sid!r} gives a finished trajectory, not an orbit")
        orb, meta = _call_plugin(sid, sp, a)
        return orb, {"source": sid, "kind": "orbit", **meta}
    hp = opt_float(a, "hp", opt_float(a, "alt", 400.0))
    ha = opt_float(a, "ha", hp)
    pofs = req_float(a, "pofs", 0.0)
    inc = req_float(a, "inc", 51.6)
    epoch = parse_epoch(a.get("epoch"))
    if sid == "preset":
        # No launch site: anchored by ascending-node (or GEO station) longitude.
        node_lon = req_float(a, "node_lon", 0.0)
        orb = Orbit.from_elements(
            hp, ha, inc, epoch, node_lon_deg=node_lon, argp_deg=req_float(a, "argp", 0.0)
        )
        return orb, {
            "source": "preset",
            "kind": "orbit",
            "site": "— (elements)",
            "site_lat": None,
            "site_lon": None,
            "launch_azimuth_deg": None,
            "node_lon_deg": node_lon,
        }
    ascending = a.get("leg", "ascending") != "descending"
    site = resolve_site(a)
    orb = Orbit.from_launch_site(
        site,
        inc_deg=inc,
        epoch=epoch,
        ascending=ascending,
        perigee_km=hp,
        apogee_km=ha,
        perigee_offset_deg=pofs,
    )
    meta = {
        "source": "site",
        "kind": "orbit",
        "site": site.name,
        "site_lat": site.lat_deg,
        "site_lon": site.lon_deg,
        "launch_azimuth_deg": round(orb.launch_azimuth_deg(site.lat_deg, ascending=ascending), 1),
    }
    return orb, meta


def track_from_args(a):
    """(orbit, meta, GroundTrack) for any source; orbit is None for a
    trajectory source, whose track comes finished (no mode/hours/dt)."""
    sid = source_of(a)
    if sid not in CORE_SOURCES:
        sp = _plugin_source(sid)
        if sp["kind"] == "trajectory":
            gt, meta = _call_plugin(sid, sp, a)
            return None, {"source": sid, "kind": "trajectory", **meta}, gt
    orb, meta = orbit_from_args(a)
    hours = req_float(a, "hours", 24.0)
    dt = opt_float(a, "dt")
    if dt is None:
        dt = default_dt(hours)
    if hours < 0:
        raise ValueError("hours must not be negative")
    if dt <= 0:
        raise ValueError("dt must be positive")
    if hours * 3600.0 / dt > MAX_TRACK_POINTS:
        raise ValueError(
            f"hours={hours:g} at dt={dt:g} s is {hours * 3600 / dt:,.0f} samples; "
            f"the limit is {MAX_TRACK_POINTS:,} — raise dt or shorten the horizon"
        )
    mode = a.get("mode") or "kepler"
    beta = opt_float(a, "beta")
    gt = orb.ground_track(hours * 3600.0, dt, mode=mode, beta=beta)
    return orb, meta, gt


def plan_from_args(a) -> dict:
    """The /api/plan JSON for any trajectory source."""
    return plan_payload(*track_from_args(a))


def plan_payload(orb, meta, gt) -> dict:
    """The /api/plan JSON: summary + track.  For an orbit the summary carries its
    elements and the track its first-rev apsides (if elliptic); a finished
    trajectory (orb None) has only its source's meta."""
    track = gt.to_json()
    if orb is None:
        return {"summary": dict(meta), "track": track}
    if orb.e > 1e-4:
        apsides = []
        for kind, ts in zip("PA", orb.apsis_times()):
            la, lo, r = orb.subpoints(np.array([ts]))
            apsides.append(
                {
                    "kind": kind,
                    "t_s": round(float(ts), 1),
                    "lat_deg": round(float(np.degrees(la[0])), 3),
                    "lon_deg": round(float(np.degrees(lo[0])), 3),
                    "alt_km": round(float(r[0] - RE) * 1e-3, 1),
                }
            )
        track["apsides"] = apsides
    return {"summary": {**orb.summary(), **meta}, "track": track}


def orbit_from_params(
    site: str = DEFAULT_SITE,
    lat: float | None = None,
    lon: float | None = None,
    alt_km: float = 400.0,
    inc_deg: float = 51.6,
    epoch_utc: str | None = None,
    ascending: bool = True,
    perigee_km: float | None = None,
    apogee_km: float | None = None,
    perigee_offset_deg: float = 0.0,
    node_lon_deg: float | None = None,
    argp_deg: float = 0.0,
) -> tuple[Orbit, LaunchSite | None]:
    """Orbit from MCP-tool style keyword parameters (see mcp_server.plan_orbit).

    `site=""` with no `lat` means an element-anchored orbit (no launch site,
    RAAN from `node_lon_deg`); the LaunchSite is then None.  Everything else
    is the same reading as `orbit_from_args`.
    """
    hp = perigee_km if perigee_km is not None else alt_km
    args = {
        "hp": hp,
        "ha": apogee_km if apogee_km is not None else hp,
        "inc": inc_deg,
        "epoch": epoch_utc,
        "leg": "ascending" if ascending else "descending",
        "pofs": perigee_offset_deg,
    }
    if not site and lat is None:
        args.update(source="preset", node_lon=node_lon_deg or 0.0, argp=argp_deg)
    else:
        args.update(source="site", site=site)
        if lat is not None:
            args.update(lat=lat, lon=lon if lon is not None else 0.0)
    orb, meta = orbit_from_args(args)
    ls = None
    if meta["site_lat"] is not None:
        ls = LaunchSite(meta["site"], meta["site_lat"], meta["site_lon"])
    return orb, ls
