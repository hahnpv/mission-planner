"""Shared fixtures: the core's tests run over the built-in modules only, never
over whatever plugins happen to be installed.

The process-wide registry is replaced with a core-only one as soon as this
file is imported -- before any test module imports mission_planner.mcp_server,
which registers the active plugins' MCP tools at import time -- so installed
plugins can't reach the suite even outside the fixtures below."""

import time

import pytest
from helpers import core_registry

import mission_planner.plugins as plugins
import mission_planner.server as server

plugins._REGISTRY = core_registry()


@pytest.fixture
def core_reg(monkeypatch):
    """A registry of the built-ins alone, installed as the process registry."""
    reg = core_registry()
    monkeypatch.setattr(plugins, "_REGISTRY", reg)
    return reg


@pytest.fixture
def core_client(core_reg):
    """A test client for the web app over `core_reg`."""
    return server.create_app().test_client()


@pytest.fixture
def app_with(monkeypatch):
    """`app_with(*specs)` -> (test client, registry) for the web app over the
    built-ins plus the given plugin spec dicts, as if they were installed."""

    def make(*specs):
        reg = core_registry(*specs)
        monkeypatch.setattr(plugins, "_REGISTRY", reg)
        return server.create_app().test_client(), reg

    return make


@pytest.fixture
def wait_job():
    """`wait_job(poll)` calls the zero-argument `poll` until the job report it
    returns is no longer running (at most 5 s) and returns that report."""

    def wait(poll, timeout_s=5.0):
        deadline = time.monotonic() + timeout_s
        while True:
            out = poll()
            if out["status"] != "running":
                return out
            assert time.monotonic() < deadline, f"job still running after {timeout_s} s"
            time.sleep(0.02)

    return wait


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    """Every test gets its own upload store, never the user's cache."""
    d = tmp_path / "uploads"
    monkeypatch.setenv("MP_UPLOAD_DIR", str(d))
    return d
