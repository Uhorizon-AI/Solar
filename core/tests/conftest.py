"""Suite-wide guard: the console port must look the same after the suite as before.

The snapshot is taken before the first test, hence before any test double exists.
Real listeners that were already there (a developer's live console) are part of
the baseline and are never touched; only NEW listeners fail the run.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))

import port_watch  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def console_port_baseline():
    before = port_watch.snapshot(port_watch.PRODUCTION_PORT)
    yield before
    leaked = port_watch.new_listeners(before, port_watch.snapshot(port_watch.PRODUCTION_PORT))
    assert not leaked, f"the test run left new listeners on :{port_watch.PRODUCTION_PORT}: {sorted(leaked)}"
