"""Keep a test's runtime root from leaking into the next test."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _restore_runtime_root(monkeypatch):
    import queue_mirror
    previous = os.environ.get("SOLAR_RUNTIME_ROOT")
    queue_mirror.bind_test_env(monkeypatch)
    yield
    queue_mirror.bind_test_env(None)
    if previous is None:
        os.environ.pop("SOLAR_RUNTIME_ROOT", None)
    else:
        os.environ["SOLAR_RUNTIME_ROOT"] = previous


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A temporary workspace and runtime for the supervisor tests; its processes end with the test."""
    import supervisor_support
    supervisor_support.pretend_profile_is_verified(monkeypatch)
    made = supervisor_support.Rig(tmp_path, monkeypatch)
    try:
        yield made
    finally:
        made.cleanup()
