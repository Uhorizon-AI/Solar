"""Pytest bootstrapping for solar-mcp, and the wall that keeps it off the live store.

Everything here resolves its runtime through `solar_runtime`, so redirecting
`SOLAR_APP_DATA` is enough to move the whole tree —gate audit, approvals, task
queue— into a temporary directory. The tools shell out, so the redirect has to
live in the environment, not only in a patched attribute.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[3]
for _skill in ("solar-mcp", "solar-app", "solar-client"):
    _scripts = _CORE / "skills" / _skill / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))


@pytest.fixture
def solar_env(tmp_path, monkeypatch):
    """A whole Solar runtime in a temp dir, for this test only."""
    app_data = tmp_path / "app-data"
    workspace = tmp_path / "workspace"
    (workspace / "sun" / "delegations").mkdir(parents=True)
    (workspace / ".solar").mkdir(parents=True)
    # A workspace the path resolver accepts: settings + sun/. Without it the
    # scripts that shell out fail closed before reaching anything under test.
    (workspace / ".solar" / "settings.json").write_text(
        '{"version": "fixture"}\n', encoding="utf-8")
    (app_data / "Solar" / "runtime").mkdir(parents=True)

    env = {
        "SOLAR_APP_DATA": str(app_data),
        "SOLAR_WORKSPACE": str(workspace),
        "SOLAR_ROOT": str(_CORE.parent),
        "SOLAR_DELEGATIONS_DIR": str(workspace / "sun" / "delegations"),
        "SOLAR_DELEGATIONS_RUNTIME": str(app_data / "Solar" / "runtime" / "delegations"),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    import mcp_gate
    import importlib
    importlib.reload(mcp_gate)

    return Env(tmp_path=tmp_path, app_data=app_data, workspace=workspace,
               runtime=app_data / "Solar" / "runtime", env={**os.environ, **env})


class Env:
    def __init__(self, tmp_path, app_data, workspace, runtime, env):
        self.tmp_path = tmp_path
        self.app_data = app_data
        self.workspace = workspace
        self.runtime = runtime
        self.env = env

    @property
    def gate_audit(self) -> Path:
        return self.runtime / "mcp" / "audit.jsonl"

    @property
    def approvals(self) -> Path:
        return self.runtime / "mcp" / "approvals"

    @property
    def tasks(self) -> Path:
        return self.runtime / "async-tasks"

    def register_action_skill(self, name: str, **entry) -> None:
        import json
        folder = self.runtime / "mcp"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "action-skills.json").write_text(
            json.dumps({name: entry}, indent=2), encoding="utf-8")

    def write_mandate(self, name: str, mode: str = "active", expires: str = "2099-01-01",
                      actions=("status",)) -> None:
        body = ["delegation:", f"  name: {name}", "  owner: test", f"  mode: {mode}",
                "  objective: >", "    fixture mandate", "  allowed_actions:"]
        body += [f"    - {action}" for action in actions]
        body += ["  shadow_safe_actions:", "    - status", "  systems:", "    - fixture",
                 "  recipients: []", "  limits:", "    volume: unlimited", "    cost: local-only",
                 "  stop_conditions:", "    - none", "  valid_from: \"2026-01-01\"",
                 f"  expires_at: \"{expires}\"",
                 f"  revoke_with: 'delegation_ctl.py revoke {name}'",
                 f"  evidence_log: runtime/delegations/{name}/", ""]
        (self.workspace / "sun" / "delegations" / f"{name}.yaml").write_text(
            "\n".join(body), encoding="utf-8")
