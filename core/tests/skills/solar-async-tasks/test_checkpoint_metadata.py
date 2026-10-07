"""Async dispatch carries the identity needed for responsibility recovery."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/solar-async-tasks/scripts"))
import execute_active as worker


def test_async_dispatch_preserves_checkpoint_identity(monkeypatch):
    fields = dict(agent="reviewer", planet="demo", responsibility="review")
    monkeypatch.setattr(worker, "_field", lambda task, key: fields[key])
    seen = []
    def run(command, **kwargs):
        seen.append(json.loads(kwargs["input"]))
        return SimpleNamespace(stdout='{"status":"ok"}', stderr="", returncode=0)
    monkeypatch.setattr(worker, "run_managed", run)
    assert worker.call_router(Path("router.py"), "fixture", "Resume", "codex")["status"] == "ok"
    assert seen[0]["metadata"] == fields
    assert seen[0]["mode"] == "direct_only"
