"""What every tool and operation needs to know about where it runs.

Kept apart from the server so the operation registry can use it without
importing the transport.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]
for _extra in ("solar-paths/scripts", "solar-state/scripts"):
    _path = _SKILLS / _extra
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_gate  # noqa: E402


class OperationError(Exception):
    """A refusal or failure with a stable, documented code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class WorkspaceUnresolved(RuntimeError):
    """No workspace was discovered. Verbs stop here and touch no runtime."""


def workspace() -> Path:
    from solar_paths import resolve_solar_paths
    try:
        found, _install = resolve_solar_paths()
    except Exception as exc:
        raise WorkspaceUnresolved(f"no Solar workspace resolved: {exc}") from None
    return found


def action_skills() -> dict:
    """Which action skills are reachable as operations. Empty until the owner fills it.

    Instruction skills never appear here: they stay native to the harness.
    """
    path = mcp_gate.gate_root() / "action-skills.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
