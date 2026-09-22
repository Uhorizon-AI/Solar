"""Make core/skills/solar-state/scripts importable and give each test a ready runtime."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[3]
_SCRIPTS = _CORE / "skills" / "solar-state" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import solar_state  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    """An empty runtime root; nothing is initialised."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(runtime))
    return runtime


@pytest.fixture
def ready(root):
    """A runtime root with the base created and the format set to sqlite."""
    with solar_state.cutover(root) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    return root
