"""The catalog: the core's generic data, data packs merged over it, and the
cache that re-reads a pack when one of its files changes."""

import os

import pytest
from helpers import write_pack

from mission_planner import SITES
from mission_planner.catalog import merged
from mission_planner.plugins import CORE_CATALOG


def test_core_catalog_is_generic():
    cat = merged([("core", CORE_CATALOG)])
    assert "Cape Canaveral / KSC" in [s["name"] for s in cat["sites"]]
    # SITES is a live mapping view of the same data.
    assert len(SITES) == len(list(SITES)) == len(cat["sites"]) >= 5
    assert SITES["Kourou"].lat_deg == pytest.approx(5.2, abs=0.1)
    assert {p["name"] for p in cat["presets"]} >= {"ISS", "GEO", "Molniya", "Sun-synchronous"}
    assert cat["overlays"] == []  # overlays come from data packs


def test_packs_merge_override_and_carry_overlay_sidecars(tmp_path):
    cat = merged([("core", CORE_CATALOG), ("pk", write_pack(tmp_path))])
    sites = {s["name"]: s for s in cat["sites"]}
    assert sites["Test Range"]["pack"] == "pk"
    assert sites["Kodiak"]["lat"] == 57.5 and sites["Kodiak"]["pack"] == "pk"  # later wins
    (ov,) = cat["overlays"]
    assert ov["name"] == "A box" and ov["style"]["color"] == "#123456" and ov["pack"] == "pk"


def test_data_pack_switches_the_catalog(app_with, tmp_path):
    client, _ = app_with({"name": "pack", "catalog": write_pack(tmp_path)})
    names = lambda: [s["name"] for s in client.get("/api/sites").get_json()]  # noqa: E731
    assert "Test Range" in names() and "Test Range" in SITES
    assert [o["name"] for o in client.get("/api/overlays").get_json()] == ["A box"]
    client.post("/api/modules/pack", json={"enabled": False})
    assert "Test Range" not in names() and "Test Range" not in SITES
    assert client.get("/api/overlays").get_json() == []


def test_a_changed_pack_file_is_re_read(app_with, tmp_path):
    pack = write_pack(tmp_path)
    client, _ = app_with({"name": "pack", "catalog": pack})
    names = lambda: {s["name"] for s in client.get("/api/sites").get_json()}  # noqa: E731
    assert "Test Range" in names() and "Later" not in names()
    f = pack / "sites.yaml"
    f.write_text(f.read_text() + "- {name: Later, lat: 1.0, lon: 2.0}\n")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))  # a visibly newer file
    assert "Later" in names()
