"""Maneuver calculator module — impulsive circular-orbit budgets.

Pure math up top (importable with no flask installed); the flask blueprint
and MCP tool wrap it.  All circular-orbit v1: Hohmann transfer, plane change
(separate and combined into the far burn), co-orbital phasing, deorbit to
the entry interface.  SI internally, km/deg at the API edge.
"""

from __future__ import annotations

import math

from ..constants import MU, RE


def _r(alt_km: float) -> float:
    return RE + alt_km * 1e3


def _vc(r: float) -> float:
    return math.sqrt(MU / r)


def hohmann(alt1_km: float, alt2_km: float) -> dict:
    """Two-impulse coplanar transfer between circular orbits."""
    r1, r2 = _r(alt1_km), _r(alt2_km)
    at = 0.5 * (r1 + r2)
    vt1 = math.sqrt(MU * (2.0 / r1 - 1.0 / at))
    vt2 = math.sqrt(MU * (2.0 / r2 - 1.0 / at))
    dv1 = abs(vt1 - _vc(r1))
    dv2 = abs(_vc(r2) - vt2)
    return {
        "dv1_ms": round(dv1, 1),
        "dv2_ms": round(dv2, 1),
        "dv_total_ms": round(dv1 + dv2, 1),
        "transfer_time_s": round(math.pi * math.sqrt(at**3 / MU), 1),
        "a_transfer_km": round((at - RE) * 1e-3, 1),
    }


def plane_change(alt_km: float, dinc_deg: float) -> dict:
    """Pure rotation of the orbit plane at circular speed."""
    dv = 2.0 * _vc(_r(alt_km)) * math.sin(math.radians(abs(dinc_deg)) / 2.0)
    return {"dv_ms": round(dv, 1)}


def combined(alt1_km: float, alt2_km: float, dinc_deg: float) -> dict:
    """Hohmann with the plane change folded into the burn at the larger
    radius (where speed is lowest) — the standard cheaper option."""
    r1, r2 = _r(alt1_km), _r(alt2_km)
    at = 0.5 * (r1 + r2)
    vt1 = math.sqrt(MU * (2.0 / r1 - 1.0 / at))
    vt2 = math.sqrt(MU * (2.0 / r2 - 1.0 / at))
    di = math.radians(abs(dinc_deg))
    if r2 >= r1:  # rotate at the arrival (slow) end
        dv1 = abs(vt1 - _vc(r1))
        dv2 = math.sqrt(_vc(r2) ** 2 + vt2**2 - 2 * _vc(r2) * vt2 * math.cos(di))
    else:  # rotate at the departure (slow) end
        dv1 = math.sqrt(_vc(r1) ** 2 + vt1**2 - 2 * _vc(r1) * vt1 * math.cos(di))
        dv2 = abs(_vc(r2) - vt2)
    return {"dv1_ms": round(dv1, 1), "dv2_ms": round(dv2, 1), "dv_total_ms": round(dv1 + dv2, 1)}


def phasing(alt_km: float, lead_deg: float, n_revs: int = 1) -> dict:
    """Co-orbital catch-up: enter a phasing orbit for `n_revs`, re-circularize.

    Positive lead = target ahead (fly lower/faster); negative = behind.
    Flags the result when the phasing perigee dips below 120 km.
    """
    r1 = _r(alt_km)
    t0 = 2.0 * math.pi * math.sqrt(r1**3 / MU)
    tp = t0 * (1.0 - lead_deg / (360.0 * n_revs))
    ap = (MU * (tp / (2.0 * math.pi)) ** 2) ** (1.0 / 3.0)
    vp = math.sqrt(max(MU * (2.0 / r1 - 1.0 / ap), 0.0))
    dv = abs(vp - _vc(r1))
    extreme_alt = ((2.0 * ap - r1) - RE) * 1e-3  # other apsis of phasing orbit
    return {
        "dv_total_ms": round(2.0 * dv, 1),
        "phasing_alt_km": round(extreme_alt, 1),
        "time_s": round(n_revs * tp, 1),
        "n_revs": n_revs,
        "feasible": extreme_alt > 120.0 or lead_deg <= 0,
    }


def deorbit(alt_km: float, perigee_km: float = 100.0) -> dict:
    """Retro burn dropping perigee to the entry interface + coast time."""
    r1, rp = _r(alt_km), _r(perigee_km)
    a = 0.5 * (r1 + rp)
    v_apo = math.sqrt(MU * (2.0 / r1 - 1.0 / a))
    return {
        "dv_ms": round(_vc(r1) - v_apo, 1),
        "coast_time_s": round(math.pi * math.sqrt(a**3 / MU), 1),
    }


def budget(
    alt1_km: float, inc1_deg: float, alt2_km: float, inc2_deg: float, lead_deg: float | None = None
) -> dict:
    """Composite maneuver budget between two circular orbits.

    Returns Hohmann legs, plane-change options (separate at departure vs
    combined into the far burn), optional co-orbital phasing, and the
    deorbit-to-interface line for the target orbit.
    """
    dinc = inc2_deg - inc1_deg
    out = {
        "from": {"alt_km": alt1_km, "inc_deg": inc1_deg},
        "to": {"alt_km": alt2_km, "inc_deg": inc2_deg},
        "hohmann": hohmann(alt1_km, alt2_km),
        "plane_change_only": plane_change(alt1_km, dinc),
        "combined": combined(alt1_km, alt2_km, dinc),
        "deorbit_from_target": deorbit(alt2_km),
    }
    if lead_deg is not None:
        out["phasing"] = phasing(alt2_km, lead_deg)
    return out


# ---------------------------------------------------------------- module glue
try:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("maneuvers", __name__, url_prefix="/api/maneuvers")

    @bp.route("/budget")
    def _budget_route():
        a = request.args
        try:
            lead = float(a["lead"]) if a.get("lead") not in (None, "") else None
            return jsonify(
                budget(
                    float(a.get("alt1", 400.0)),
                    float(a.get("inc1", 51.6)),
                    float(a.get("alt2", 400.0)),
                    float(a.get("inc2", 51.6)),
                    lead_deg=lead,
                )
            )
        except (ValueError, KeyError) as e:
            return jsonify({"error": str(e)}), 400
except ImportError:  # library use without flask
    bp = None


def maneuver_budget(
    alt1_km: float = 400.0,
    inc1_deg: float = 51.6,
    alt2_km: float = 400.0,
    inc2_deg: float = 51.6,
    lead_deg: float | None = None,
) -> dict:
    """Impulsive maneuver budget between two circular orbits.

    Hohmann transfer legs, plane-change options (separate vs combined into
    the far burn), optional co-orbital phasing for a target leading by
    `lead_deg`, and the deorbit-to-100km line.  All dv in m/s, times in s.
    """
    return budget(alt1_km, inc1_deg, alt2_km, inc2_deg, lead_deg)


MODULE = {
    "api": 1,
    "name": "maneuvers",
    "title": "maneuver planner",
    "blueprint": bp,
    "js": "maneuvers.js",
    "mcp_tools": [maneuver_budget],
}
