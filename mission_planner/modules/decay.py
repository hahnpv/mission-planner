"""Drag-decay panel (built in) — the altitude-vs-time sparkline and the entry
/ impact line for a plan flown in a drag mode.

The physics is the core's `decay` propagation mode (decay.py); this module is
only its UI skin: a side-panel section that redraws from `track.decay_profile`,
`track.entry` and `track.impact` on every plan, so plugin modes that fly to
the ground get the same readout for free.
"""

from __future__ import annotations

MODULE = {
    "api": 1,
    "name": "decay",
    "title": "drag decay",
    "js": "decay.js",
}
