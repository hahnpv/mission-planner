"""Contact windows: when a vehicle is above a ground station's elevation mask.

Pure math over a GroundTrack's public arrays (seconds-past-epoch `t`,
`lat`/`lon` in radians, `alt` in metres), so it works for any track: a
planned orbit, a satellite from a file, one track of a constellation.

Geometry on the core's spherical Earth: from the central angle psi between
the station and the vehicle's subpoint and the vehicle's radius r,

    elevation = atan2(cos(psi) - RE / r, sin(psi))

which is 0 exactly on the horizon footprint's edge.  The station sits on the
sphere (no station altitude, no terrain, no refraction).
"""

from __future__ import annotations

import math

import numpy as np

from mission_planner.constants import RE
from mission_planner.groundtrack import bearing
from mission_planner.timebase import add_seconds


def look_angles(gt, lat_deg: float, lon_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """(elevation, azimuth) [deg] of the vehicle from the station, per sample."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    c = np.sin(lat) * np.sin(gt.lat) + np.cos(lat) * np.cos(gt.lat) * np.cos(gt.lon - lon)
    psi = np.arccos(np.clip(c, -1.0, 1.0))
    r = RE + np.maximum(np.asarray(gt.alt, dtype=float), 0.0)
    el = np.degrees(np.arctan2(np.cos(psi) - RE / r, np.sin(psi)))
    az = np.degrees(bearing(lat, lon, gt.lat, gt.lon)) % 360.0
    return el, az


def mask_ring_deg(alt_km: float, min_el_deg: float) -> float:
    """Ground range [deg of arc] from the station inside which a vehicle at
    `alt_km` is above `min_el_deg`: the ring the plugin draws on the map."""
    r = RE + max(alt_km, 0.0) * 1e3
    el = math.radians(min_el_deg)
    return math.degrees(math.acos(min(1.0, RE / r * math.cos(el))) - el)


def _crossing(t, el, i: int, mask: float) -> float:
    """Time where elevation crosses `mask` between samples i and i+1 (linear)."""
    d = el[i + 1] - el[i]
    f = 0.0 if d == 0 else (mask - el[i]) / d
    return float(t[i] + min(max(f, 0.0), 1.0) * (t[i + 1] - t[i]))


def contacts(gt, lat_deg: float, lon_deg: float, min_el_deg: float = 10.0) -> list[dict]:
    """Every window in which the vehicle is at or above `min_el_deg` as seen
    from the station.  Each window: `aos_utc` / `los_utc` (acquisition and
    loss of signal, interpolated between samples), `aos_t_s` / `los_t_s`,
    `duration_s`, `max_el_deg` with `max_el_utc` / `max_el_t_s`, and the
    azimuths at AOS, maximum and LOS.  A window already open at the start of
    the track, or still open at its end, is cut there and flagged `partial`.
    """
    if not -90.0 < min_el_deg < 90.0:
        raise ValueError("min_el_deg must be between -90 and 90 degrees")
    t = np.asarray(gt.t, dtype=float)
    if len(t) < 2:
        return []
    el, az = look_angles(gt, lat_deg, lon_deg)
    up = el >= min_el_deg
    padded = np.r_[False, up, False]
    starts = np.flatnonzero(padded[1:] & ~padded[:-1])
    ends = np.flatnonzero(~padded[1:] & padded[:-1]) - 1
    out = []
    for i0, i1 in zip(starts, ends):
        t_aos = t[i0] if i0 == 0 else _crossing(t, el, i0 - 1, min_el_deg)
        t_los = t[i1] if i1 == len(t) - 1 else _crossing(t, el, i1, min_el_deg)
        k = i0 + int(np.argmax(el[i0 : i1 + 1]))
        out.append(
            {
                "aos_utc": add_seconds(gt.epoch, t_aos).isoformat(),
                "los_utc": add_seconds(gt.epoch, t_los).isoformat(),
                "aos_t_s": round(t_aos, 1),
                "los_t_s": round(t_los, 1),
                "duration_s": round(t_los - t_aos, 1),
                "max_el_deg": round(float(el[k]), 2),
                "max_el_utc": add_seconds(gt.epoch, t[k]).isoformat(),
                "max_el_t_s": float(t[k]),
                "aos_az_deg": round(float(az[i0]), 1),
                "max_el_az_deg": round(float(az[k]), 1),
                "los_az_deg": round(float(az[i1]), 1),
                "partial": bool(i0 == 0 or i1 == len(t) - 1),
            }
        )
    return out


def coverage(windows: list[dict], span_s: float) -> dict:
    """Summary of a station's contact windows over a span: how many, total
    and mean contact time, the fraction of the span in contact, and the
    longest gap without contact (including before the first and after the
    last window)."""
    if span_s <= 0:
        return {"n": 0, "total_s": 0.0, "mean_s": 0.0, "fraction": 0.0, "longest_gap_s": 0.0}
    spans = sorted((w["aos_t_s"], w["los_t_s"]) for w in windows)
    # Windows from several tracks may overlap: merge them for the time in contact.
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    total = sum(b - a for a, b in merged)
    edges = [0.0] + [x for ab in merged for x in ab] + [span_s]
    gaps = [edges[i + 1] - edges[i] for i in range(0, len(edges), 2)]
    return {
        "n": len(windows),
        "total_s": round(total, 1),
        "mean_s": round(total / len(merged), 1) if merged else 0.0,
        "fraction": round(total / span_s, 4),
        "longest_gap_s": round(max(gaps), 1),
    }
