"""Shared fixtures: the core's tests run over the built-in modules only, never
over whatever plugins happen to be installed."""

import pytest

import mission_planner.plugins as plugins
import mission_planner.server as server
from mission_planner.plugins import Registry, builtin_sources


@pytest.fixture
def core_reg(monkeypatch):
    """A registry of the built-ins alone, installed as the process registry."""
    reg = Registry(list(builtin_sources()))
    monkeypatch.setattr(plugins, "_REGISTRY", reg)
    return reg


@pytest.fixture
def core_client(core_reg):
    """A test client for the web app over `core_reg`."""
    return server.create_app().test_client()
