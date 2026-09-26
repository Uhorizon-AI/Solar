"""Test helper. Calls the real claim_owner. There is no session bypass."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

_CORE = Path(__file__).resolve().parents[2]
_STATE = _CORE / "skills" / "solar-state" / "scripts"
if str(_STATE) not in sys.path:
    sys.path.insert(0, str(_STATE))

import solar_state  # noqa: E402


def bound_env(test):
    """Stand-in for pytest's monkeypatch in a unittest.TestCase.

    setenv records the previous value of that one key and restores it in
    addCleanup. It does not snapshot the whole environment: patch.dict would
    put back later changes to other variables when it stops.
    """
    class _Bound:
        def setenv(self, key, value):
            previous = os.environ.get(key)
            os.environ[key] = str(value)

            def _restore(key=key, previous=previous):
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous

            test.addCleanup(_restore)

    return _Bound()


def claim_test_owner(runtime, workspace, workspace_id: str | None = None, *, monkeypatch) -> dict:
    """Give a temp runtime the owner session() will accept.

    Writes workspace_id into that workspace's settings and sets
    SOLAR_WORKSPACE through monkeypatch (pytest's fixture, or bound_env).
    Callers pass a temporary workspace, never a live one. There is no raw
    os.environ write: a caller that omits monkeypatch fails immediately.
    """
    runtime = Path(runtime)
    workspace = Path(workspace)
    runtime.mkdir(parents=True, exist_ok=True)
    solar = workspace / ".solar"
    solar.mkdir(parents=True, exist_ok=True)
    settings_path = solar / "settings.json"
    data: dict = {}
    if settings_path.is_file():
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    workspace_id = workspace_id or str(data.get("workspace_id") or "") or str(uuid.uuid4())
    data["workspace_id"] = workspace_id
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setenv("SOLAR_WORKSPACE", str(workspace))
    return solar_state.claim_owner(workspace, workspace_id, root=runtime)
