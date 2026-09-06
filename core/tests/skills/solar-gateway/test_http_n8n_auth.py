"""Auth, ledger, and contract tests for solar-gateway HTTP n8n webhook routes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import secrets
import sys
import threading
import types
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

import pytest
import urllib.error
import urllib.request

BRIDGE_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "solar-gateway"
    / "scripts"
    / "run_http_webhook_bridge.py"
)

SECRET = "s3cret-value-for-tests-0123456789ab"


def _load_bridge(
    monkeypatch: pytest.MonkeyPatch,
    secret: str = "",
    default_async: bool = False,
    tmp_path: Path | None = None,
    allowed_chat: str = "456",
):
    run_dir = tmp_path / "gw" if tmp_path is not None else Path("/tmp/solar-n8n-test-gw")
    monkeypatch.setenv("SOLAR_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SOLAR_HTTP_PORT", "0")
    monkeypatch.setenv("SOLAR_HTTP_WEBHOOK_BASE", "/webhook")
    monkeypatch.setenv("SOLAR_WS_HOST", "127.0.0.1")
    monkeypatch.setenv("SOLAR_WS_PORT", "8765")
    monkeypatch.setenv("SOLAR_WS_PATH", "/ws")
    monkeypatch.setenv("SOLAR_N8N_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("SOLAR_GATEWAY_RUN_DIR", str(run_dir))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", allowed_chat)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    if default_async:
        monkeypatch.setenv("SOLAR_N8N_DEFAULT_ASYNC", "1")
    else:
        monkeypatch.delenv("SOLAR_N8N_DEFAULT_ASYNC", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    if "websockets" not in sys.modules:
        try:
            import websockets  # noqa: F401
        except ModuleNotFoundError:
            ws_mod = types.ModuleType("websockets")
            ws_client = types.ModuleType("websockets.client")

            async def _connect(*_a, **_k):  # pragma: no cover
                raise RuntimeError("websockets stub: connect unused in auth tests")

            ws_client.connect = _connect  # type: ignore[attr-defined]
            ws_mod.client = ws_client  # type: ignore[attr-defined]
            sys.modules["websockets"] = ws_mod
            sys.modules["websockets.client"] = ws_client

    spec = importlib.util.spec_from_file_location("run_http_webhook_bridge", BRIDGE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.pop("run_http_webhook_bridge", None)
    spec.loader.exec_module(mod)
    return mod


def _start_server(mod):
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.WebhookHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def _http_json(method: str, url: str, body: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None):
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        return exc.code, parsed


def _bearer(secret: str = SECRET) -> Dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _n8n_body(**kwargs) -> Dict[str, Any]:
    base = {
        "type": "request",
        "request_id": "tg:1",
        "session_id": "telegram:456",
        "user_id": "1",
        "chat_id": "456",
        "text": "hi",
    }
    base.update(kwargs)
    return base


def test_check_n8n_secret_uses_compare_digest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret="correct-secret-value", tmp_path=tmp_path)
    assert "compare_digest" in mod.check_n8n_secret.__code__.co_names or secrets.compare_digest in (
        getattr(mod, "secrets", secrets).compare_digest,
    )
    fail = mod.check_n8n_secret({"Authorization": "Bearer wrong"})
    assert fail is not None
    assert fail[0] == 403
    assert mod.check_n8n_secret({"Authorization": "Bearer correct-secret-value"}) is None
    fail_missing = mod.check_n8n_secret({})
    assert fail_missing is not None
    assert fail_missing[0] == 401
    # Legacy header is not accepted.
    legacy = mod.check_n8n_secret({"X-Solar-N8n-Secret": "correct-secret-value"})
    assert legacy is not None
    assert legacy[0] == 401


def test_post_n8n_rejects_missing_and_wrong_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
    called = []
    monkeypatch.setattr(mod, "request_solar", lambda *_a, **_k: called.append(1) or {})
    server, base = _start_server(mod)
    try:
        url = f"{base}/webhook/n8n"
        body = _n8n_body()
        code, payload = _http_json("POST", url, body)
        assert code == 401
        assert payload.get("status") == "failed"
        assert called == []

        code, payload = _http_json("POST", url, body, headers={"Authorization": "Bearer nope"})
        assert code == 403
        assert payload.get("status") == "failed"
        assert called == []
    finally:
        server.shutdown()
        server.server_close()


def test_get_n8n_result_is_failed_not_poll(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
    server, base = _start_server(mod)
    try:
        url = f"{base}/webhook/n8n/result?request_id=missing"
        code, _ = _http_json("GET", url)
        assert code == 401
        code, payload = _http_json("GET", url, headers=_bearer())
        assert code == 200
        assert payload.get("status") == "failed"
        assert "poll" in (payload.get("error") or "").lower()
    finally:
        server.shutdown()
        server.server_close()


def test_post_n8n_async_is_unreachable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
    called = []

    async def fake_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
        called.append(payload)
        return {"status": "success", "reply_text": "should-not-run"}

    monkeypatch.setattr(mod, "request_solar", fake_solar)
    server, base = _start_server(mod)
    try:
        code, payload = _http_json(
            "POST",
            f"{base}/webhook/n8n?async=1",
            {**_n8n_body(request_id="tg_async_1"), "async": True},
            headers=_bearer(),
        )
        assert code == 200
        assert payload.get("status") == "failed"
        assert called == []
    finally:
        server.shutdown()
        server.server_close()


def test_post_n8n_fail_closed_when_secret_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret="", tmp_path=tmp_path)
    called = []

    async def fake_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
        called.append(payload)
        return {"status": "ok", "reply_text": "open"}

    monkeypatch.setattr(mod, "request_solar", fake_solar)
    server, base = _start_server(mod)
    try:
        code, payload = _http_json("POST", f"{base}/webhook/n8n", _n8n_body())
        assert code == 401
        assert payload.get("status") == "failed"
        assert called == []
    finally:
        server.shutdown()
        server.server_close()


def test_post_n8n_direct_reply_bearer_and_origin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
    seen: list[Dict[str, Any]] = []

    async def fake_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
        seen.append(payload)
        return {
            "status": "success",
            "reply_text": "pong",
            "decision": {"kind": "direct_reply"},
            "request_id": payload.get("request_id"),
        }

    monkeypatch.setattr(mod, "request_solar", fake_solar)
    server, base = _start_server(mod)
    try:
        code, payload = _http_json(
            "POST", f"{base}/webhook/n8n", _n8n_body(text="hola"), headers=_bearer()
        )
        assert code == 200
        assert payload.get("reply_text") == "pong"
        assert payload.get("decision", {}).get("kind") == "direct_reply"
        assert seen[0]["metadata"]["origin_chat_id"] == "456"
        assert seen[0]["metadata"]["origin_request_id"] == "tg:1"
        assert seen[0]["metadata"]["origin_channel"] == "telegram"
    finally:
        server.shutdown()
        server.server_close()


def test_post_n8n_long_forwards_origin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
    seen: list[Dict[str, Any]] = []

    async def fake_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
        seen.append(payload)
        return {
            "status": "success",
            "reply_text": "Me pongo con ello. Te aviso por aquí cuando termine.\n\n(Tarea: t-1)",
            "decision": {"kind": "async_draft_created", "task_id": "t-1", "queued": True},
            "request_id": payload.get("request_id"),
        }

    monkeypatch.setattr(mod, "request_solar", fake_solar)
    server, base = _start_server(mod)
    try:
        code, payload = _http_json(
            "POST",
            f"{base}/webhook/n8n",
            _n8n_body(request_id="tg:long", text="haz un plan"),
            headers=_bearer(),
        )
        assert code == 200
        assert "Me pongo con ello" in payload.get("reply_text", "")
        assert seen[0]["metadata"]["origin_chat_id"] == "456"
        assert seen[0]["metadata"]["origin_request_id"] == "tg:long"
    finally:
        server.shutdown()
        server.server_close()


def test_post_n8n_replay_same_request_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
    calls = {"n": 0}

    async def fake_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
        calls["n"] += 1
        return {
            "status": "success",
            "reply_text": "original-reply",
            "decision": {"kind": "direct_reply"},
            "request_id": payload.get("request_id"),
        }

    monkeypatch.setattr(mod, "request_solar", fake_solar)
    server, base = _start_server(mod)
    try:
        body = _n8n_body(request_id="tg:replay")
        code1, payload1 = _http_json("POST", f"{base}/webhook/n8n", body, headers=_bearer())
        code2, payload2 = _http_json("POST", f"{base}/webhook/n8n", body, headers=_bearer())
        assert code1 == 200 and code2 == 200
        assert payload1.get("reply_text") == "original-reply"
        assert payload2.get("reply_text") == "original-reply"
        assert calls["n"] == 1
        key = hashlib.sha256(b"tg:replay").hexdigest()
        ledger = tmp_path / "gw" / "n8n-jobs" / f"{key}.json"
        assert ledger.is_file()
        assert oct(ledger.stat().st_mode)[-3:] == "600"
    finally:
        server.shutdown()
        server.server_close()


def test_post_n8n_unauthorized_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path, allowed_chat="456")
    called = []

    async def fake_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
        called.append(payload)
        return {"status": "success", "reply_text": "nope"}

    monkeypatch.setattr(mod, "request_solar", fake_solar)
    server, base = _start_server(mod)
    try:
        code, payload = _http_json(
            "POST",
            f"{base}/webhook/n8n",
            _n8n_body(chat_id="999", session_id="telegram:999", request_id="tg:bad"),
            headers=_bearer(),
        )
        assert code == 200
        assert payload.get("status") == "failed"
        assert "no autorizado" in (payload.get("reply_text") or "").lower()
        assert called == []
    finally:
        server.shutdown()
        server.server_close()


def test_simultaneous_posts_execute_router_once(monkeypatch, tmp_path):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    mod = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
    calls = []
    start = threading.Barrier(2)

    async def fake_solar(payload):
        calls.append(payload)
        await asyncio.sleep(0.3)
        return {"status": "success", "reply_text": "one reply"}

    monkeypatch.setattr(mod, "request_solar", fake_solar)
    server, base = _start_server(mod)
    def post():
        start.wait(timeout=5)
        return _http_json("POST", f"{base}/webhook/n8n",
                          _n8n_body(request_id="same-concurrent"), headers=_bearer())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(post), pool.submit(post)
            assert a.result(timeout=5) == b.result(timeout=5)
        assert len(calls) == 1
        # A fresh module instance still replays the persisted response.
        reloaded = _load_bridge(monkeypatch, secret=SECRET, tmp_path=tmp_path)
        assert reloaded.n8n_ledger_load("same-concurrent")["body"]["reply_text"] == "one reply"
    finally:
        server.shutdown()
        server.server_close()
