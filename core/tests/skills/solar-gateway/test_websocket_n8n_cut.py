"""n8n 90s cut: own process group, killpg of that pgid, no leftover task."""

from __future__ import annotations

import importlib.util
import json
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

WS_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "solar-gateway"
    / "scripts"
    / "run_websocket_bridge.py"
)


def _load_ws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("SOLAR_WS_HOST", "127.0.0.1")
    monkeypatch.setenv("SOLAR_WS_PORT", "0")
    monkeypatch.setenv("SOLAR_N8N_SYNC_TIMEOUT_SEC", "1")
    monkeypatch.delenv("SOLAR_WORKSPACE", raising=False)

    if "websockets" not in sys.modules:
        try:
            import websockets  # noqa: F401
        except ModuleNotFoundError:
            ws_mod = types.ModuleType("websockets")
            ws_server = types.ModuleType("websockets.server")

            async def _serve(*_a, **_k):  # pragma: no cover
                raise RuntimeError("websockets stub")

            ws_server.serve = _serve  # type: ignore[attr-defined]
            ws_mod.server = ws_server  # type: ignore[attr-defined]
            sys.modules["websockets"] = ws_mod
            sys.modules["websockets.server"] = ws_server

    spec = importlib.util.spec_from_file_location("run_websocket_bridge", WS_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.pop("run_websocket_bridge", None)
    spec.loader.exec_module(mod)
    return mod


def test_n8n_timeout_kills_own_pgid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_ws(monkeypatch, tmp_path)
    killed: list[tuple[int, int]] = []
    popen_kwargs: dict = {}

    class FakeProc:
        pid = 4242

        def communicate(self, input=None, timeout=None):
            raise subprocess.TimeoutExpired(cmd="run_router.py", timeout=timeout)

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    def fake_popen(*_a, **kwargs):
        popen_kwargs.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mod.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    result = mod.call_router(
        {
            "type": "request",
            "request_id": "tg:cut",
            "session_id": "telegram:1",
            "user_id": "1",
            "text": "hang",
            "channel": "n8n",
            "mode": "auto",
            "metadata": {},
        }
    )
    assert popen_kwargs.get("start_new_session") is True
    assert killed == [(4242, signal.SIGKILL)]
    assert result["status"] == "failed"
    assert result["error_code"] == "n8n_sync_timeout"
    assert result["decision"]["task_id"] is None
    assert "tiempo" in result["reply_text"].lower()


def test_non_n8n_uses_subprocess_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_ws(monkeypatch, tmp_path)
    called = {}

    class FakeCompleted:
        stdout = json.dumps({"status": "success", "reply_text": "ok", "decision": {"kind": "direct_reply"}})
        stderr = ""
        returncode = 0

    def fake_run(*_a, **kwargs):
        called["timeout"] = kwargs.get("timeout")
        return FakeCompleted()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    result = mod.call_router(
        {
            "type": "request",
            "request_id": "r1",
            "session_id": "s",
            "user_id": "u",
            "text": "hi",
            "channel": "other",
            "mode": "direct_only",
        }
    )
    assert called["timeout"] == mod.AI_ROUTER_TIMEOUT_SEC
    assert result["reply_text"] == "ok"
