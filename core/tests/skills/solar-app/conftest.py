import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "support"))

import console_harness  # noqa: E402
import port_watch  # noqa: E402


@pytest.fixture
def harness(tmp_path, console_port_baseline):
    """Isolated workspace, runtime, app data and private port, plus cleanup.

    Depends on the session baseline, so the production-port listeners are recorded
    before any double exists. After each test the production port must be unchanged.
    """
    h = console_harness.Harness(tmp_path, console_port_baseline)
    try:
        yield h
    finally:
        h.cleanup()
        leaked = port_watch.new_listeners(console_port_baseline, port_watch.snapshot(port_watch.PRODUCTION_PORT))
        assert not leaked, f"test left listeners on :9000: {sorted(leaked)}"
