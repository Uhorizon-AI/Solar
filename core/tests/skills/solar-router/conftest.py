"""Pytest bootstrapping for solar-router: make core/skills/solar-router/scripts importable.

Also the containment wall for this directory. `route()` writes: it appends to
the router audit, rewrites the continuity record and can create async task
files. Several tests here call it for real with the provider mocked, so without
this fixture the suite writes into the machine's live runtime store — the one
the console reads and the index projects.

`router` resolves `RUNTIME_ROOT` and `SOLAR_WORKSPACE` once, at import time, so
environment variables alone arrive too late: the module attributes are patched
too. Both are restored after every test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# core/tests/skills/solar-router/conftest.py -> parents[3] == core/
_CORE = Path(__file__).resolve().parents[3]
_ROUTER_SCRIPTS = _CORE / "skills" / "solar-router" / "scripts"
if str(_ROUTER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ROUTER_SCRIPTS))

# Imported here, before any test redirects the environment: `router` resolves
# the workspace at import time through `resolve_solar_paths`, which refuses an
# exported SOLAR_WORKSPACE that disagrees with the one discovered from cwd.
import router  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Point every runtime home at a temp directory, for every test in here."""
    runtime = tmp_path / "solar-runtime"
    workspace = tmp_path / "workspace"
    (runtime / "router").mkdir(parents=True)
    (workspace / "sun" / "runtime").mkdir(parents=True)

    # Subprocesses read the environment; the in-process module read it once, at
    # import. SOLAR_WORKSPACE is deliberately NOT exported: `resolve_solar_paths`
    # fails closed when an exported workspace disagrees with the discovered one,
    # which would break every test that shells out. The module attribute carries
    # the redirect instead.
    for name, value in {
        "SOLAR_APP_DATA": str(tmp_path / "app-data"),
        "SOLAR_RUNTIME_ROOT": str(runtime),
        "SOLAR_RUNTIME_DIR": str(runtime / "router"),
        "SOLAR_ROUTER_RUNTIME_DIR": str(runtime / "router"),
        "SOLAR_DELEGATIONS_RUNTIME": str(runtime / "delegations"),
    }.items():
        monkeypatch.setenv(name, value)

    monkeypatch.setattr(router, "RUNTIME_ROOT", runtime / "router")
    monkeypatch.setattr(router, "SOLAR_WORKSPACE", workspace)

    import solar_state
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format("sqlite")

    yield SimpleRuntime(root=runtime, workspace=workspace)

    # A test that repoints a runtime home at the real store is the failure this
    # wall exists to catch, so check it on the way out instead of trusting it.
    assert _within(router.RUNTIME_ROOT, tmp_path), (
        f"router.RUNTIME_ROOT escaped the fixture: {router.RUNTIME_ROOT}")
    assert _within(router.continuity_root(), tmp_path), (
        f"continuity escaped the fixture: {router.continuity_root()}")


class SimpleRuntime:
    """Where the isolated writes land, for tests that want to look."""

    def __init__(self, root: Path, workspace: Path):
        self.root = root
        self.workspace = workspace
        self.audit = root / "router" / "audit.jsonl"
        self.continuity = root / "continuity" / "active.json"
        self.tasks = workspace / "sun" / "runtime" / "async-tasks"


def _within(path, parent) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False
