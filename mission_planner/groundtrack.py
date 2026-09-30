"""GroundTrack container and overflight (pass) search."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .constants import RE
from .timebase import add_seconds


def bearing(lat1, lon1, lat2, lon2):
    """Great-circle initial bearing [rad] from point 1 to point 2 (arrays ok)."""
    dlon = lon2 - lon1
    y = np.sin(dlon) * np.cos(lat2)
    x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    return np.arctan2(y, x)


def gc_distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance [km] (haversine, spherical Earth, arrays ok)."""
    s1 = np.sin((lat2 - lat1) / 2.0) ** 2
    s2 = np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    return 2.0 * (RE * 1e-3) * np.arcsin(np.sqrt(np.clip(s1 + s2, 0.0, 1.0)))


@dataclass
class GroundTrack:
    """Sub-satellite track: seconds-past-epoch `t`, lat/lon [rad], alt [m].

    `extra` carries mode-specific payloads that `to_json` merges into the
    track (e.g. `decay_profile`, `entry`, `impact`).

    One track is one vehicle.  A plan may hold several (a constellation, a
    branched trajectory): sources and readers then return a list, and `id`
    (unique within the plan), `label` and `parent` ({"id", "t_s"}: where this
    track split off another) tell them apart.  Time must not run backwards.
    """

    epoch: datetime
    t: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    alt: np.ndarray
    extra: dict = field(default_factory=dict)
    id: str | None = None
    label: str | None = None
    parent: dict | None = None

    def __post_init__(self):
        n = len(self.t)
        if not (len(self.lat) == len(self.lon) == len(self.alt) == n):
            raise ValueError("t, lat, lon and alt must have the same length")
        if n > 1 and np.any(np.diff(np.asarray(self.t, dtype=float)) < 0):
            which = f"track {self.label or self.id}" if (self.label or self.id) else "track"
            raise ValueError(
                f"{which} runs backwards in time — several vehicles or branches "
                "merged into one track?"
            )

    @property
    def heading(self) -> np.ndarray:
        """Earth-relative track heading [rad], finite-differenced (NaN for a
        single-sample track)."""
        if len(self.lat) < 2:
            return np.full(len(self.lat), np.nan)
        h = bearing(self.lat[:-1], self.lon[:-1], self.lat[1:], self.lon[1:])
        return np.append(h, h[-1])

    def passes(
        self,
        tgt_lat_deg: float,
        tgt_lon_deg: float,
        within_km: float = 500.0,
        max_passes: int = 200,
    ) -> list[dict]:
        """Overflight windows where the subpoint comes within `within_km`
        (inclusive).  Each window reports UTC entry/exit/closest-approach
        times, the minimum ground distance, approach heading, and leg
        direction.  A track with fewer than two samples has no passes.
        """
        if len(self.t) < 2:
            return []
        tgt_lat = np.radians(tgt_lat_deg)
        tgt_lon = np.radians(tgt_lon_deg)
        d = gc_distance_km(self.lat, self.lon, tgt_lat, tgt_lon)
        inside = d <= within_km
        if not inside.any():
            return []
        # Contiguous runs of `inside` -> (first, last) sample index pairs.
        padded = np.r_[False, inside, False]
        starts = np.flatnonzero(padded[1:] & ~padded[:-1])
        ends = np.flatnonzero(~padded[1:] & padded[:-1]) - 1
        runs = list(zip(starts, ends))

        hdg = self.heading
        out = []
        for i0, i1 in runs[:max_passes]:
            k = i0 + int(np.argmin(d[i0 : i1 + 1]))
            k2 = min(k, len(self.lat) - 2)
            ascending = bool(self.lat[k2 + 1] > self.lat[k2])
            out.append(
                {
                    "aos_utc": add_seconds(self.epoch, self.t[i0]).isoformat(),
                    "los_utc": add_seconds(self.epoch, self.t[i1]).isoformat(),
                    "ca_utc": add_seconds(self.epoch, self.t[k]).isoformat(),
                    "ca_t_s": float(self.t[k]),
                    "min_dist_km": round(float(d[k]), 1),
                    "heading_deg": round(float(np.degrees(hdg[k])) % 360.0, 1) % 360.0,
                    "direction": "ascending" if ascending else "descending",
                    "alt_km": round(float(self.alt[k]) * 1e-3, 1),
                }
            )
        return out

    def to_json(self, decimals: int = 5) -> dict:
        """Track as plain JSON.  5 decimals of arc (~1 m) and metre altitude:
        the UI differentiates this track to get flight path angle, and at the
        old 3 decimals (~111 m) the horizontal step in a near-vertical
        terminal descent rounded to zero, pinning gamma at exactly -90 deg."""
        d = {
            "epoch_utc": self.epoch.isoformat(),
            "t": self.t.tolist(),
            "lat": np.degrees(self.lat).round(decimals).tolist(),
            "lon": np.degrees(self.lon).round(decimals).tolist(),
            "alt_km": (self.alt * 1e-3).round(3).tolist(),
        }
        d.update(self.extra)
        for key in ("id", "label", "parent"):
            if getattr(self, key) is not None:
                d[key] = getattr(self, key)
        return d
