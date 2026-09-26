"""Make core/skills/solar-state/scripts importable and give each test a ready runtime."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[3]
_SCRIPTS = _CORE / "skills" / "solar-state" / "scripts"
_SUPPORT = _CORE / "tests" / "support"
for _path in (_SCRIPTS, _SUPPORT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import solar_state  # noqa: E402
from runtime_owner import claim_test_owner  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    """An empty runtime root; nothing is initialised."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(runtime))
    monkeypatch.delenv("SOLAR_WORKSPACE", raising=False)
    return runtime


@pytest.fixture
def ready(root, tmp_path, monkeypatch):
    """A runtime root with an owner, the base created and the format set to sqlite."""
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("SOLAR_WORKSPACE", str(workspace))
    claim_test_owner(root, workspace, monkeypatch=monkeypatch)
    with solar_state.cutover(root) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    return root
