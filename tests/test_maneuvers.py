import pytest

from mission_planner.modules.maneuvers import (
    budget,
    combined,
    deorbit,
    hohmann,
    phasing,
    plane_change,
)

GEO_ALT = 35786.0


def test_hohmann_leo_to_geo_textbook():
    h = hohmann(300.0, GEO_ALT)
    assert h["dv1_ms"] == pytest.approx(2426, abs=15)
    assert h["dv2_ms"] == pytest.approx(1467, abs=15)
    assert h["transfer_time_s"] == pytest.approx(5.25 * 3600, rel=0.01)


def test_hohmann_symmetric_dv():
    up, down = hohmann(300.0, 800.0), hohmann(800.0, 300.0)
    assert up["dv_total_ms"] == pytest.approx(down["dv_total_ms"], abs=0.2)


def test_plane_change_28p5_at_400km():
    v = plane_change(400.0, 28.5)["dv_ms"]
    assert v == pytest.approx(2 * 7668.6 * 0.24615, rel=0.01)  # 2 v sin(14.25)


def test_combined_cheaper_than_separate():
    sep = hohmann(300.0, GEO_ALT)["dv_total_ms"] + plane_change(300.0, 28.5)["dv_ms"]
    comb = combined(300.0, GEO_ALT, 28.5)["dv_total_ms"]
    assert comb < 0.65 * sep
    # zero-dinc combined reduces to plain Hohmann
    assert combined(300.0, 800.0, 0.0)["dv_total_ms"] == pytest.approx(
        hohmann(300.0, 800.0)["dv_total_ms"], abs=0.2
    )


def test_phasing_basics():
    assert phasing(400.0, 0.0)["dv_total_ms"] == 0.0
    ahead = phasing(400.0, 30.0)
    behind = phasing(400.0, -30.0)
    assert ahead["phasing_alt_km"] < 400.0 < behind["phasing_alt_km"]
    # Vis-viva is nonlinear: catching up (lower/faster) costs more than
    # dropping back (higher/slower) for the same |lead| — but same ballpark.
    assert ahead["dv_total_ms"] > behind["dv_total_ms"] > 0
    assert ahead["dv_total_ms"] == pytest.approx(behind["dv_total_ms"], rel=0.3)
    # more revs -> gentler phasing orbit, less dv
    assert phasing(400.0, 30.0, n_revs=5)["dv_total_ms"] < ahead["dv_total_ms"]
    # a huge single-rev catch-up from LEO digs below the atmosphere
    assert not phasing(200.0, 120.0)["feasible"]


def test_deorbit_400km():
    d = deorbit(400.0)
    assert 80.0 < d["dv_ms"] < 100.0
    assert d["coast_time_s"] == pytest.approx(2750, rel=0.05)  # ~half period


def test_budget_composes():
    b = budget(400.0, 51.6, 800.0, 98.6, lead_deg=45.0)
    assert b["hohmann"]["dv_total_ms"] == pytest.approx(hohmann(400.0, 800.0)["dv_total_ms"])
    assert b["plane_change_only"]["dv_ms"] == pytest.approx(plane_change(400.0, 47.0)["dv_ms"])
    assert b["phasing"]["dv_total_ms"] > 0
    assert "deorbit_from_target" in b
