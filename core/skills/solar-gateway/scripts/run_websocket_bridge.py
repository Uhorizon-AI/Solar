#!/usr/bin/env python3
"""
solar-transport-gateway WebSocket bridge v3.

Pure delegate: forwards requests to solar-router and returns the structured
router v3 response. No provider selection, no fallback, no async policy here.
"""
import asyncio
import json
import os
import pathlib
import signal
import subprocess
import sys
import traceback
from typing import Any, Dict

try:
    from websockets.server import serve
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: websockets. Install with: pip install websockets"
    ) from exc


HOST = os.getenv("SOLAR_WS_HOST", "127.0.0.1")
PORT = int(os.getenv("SOLAR_WS_PORT", "8765"))
PATH = os.getenv("SOLAR_WS_PATH", "/ws")
AI_ROUTER_PYTHON = os.getenv("SOLAR_AI_ROUTER_PYTHON", "python3")


def _env_int_with_comment(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    value = raw.split("#", 1)[0].strip()
    if not value:
        return default
    return int(value)


AI_ROUTER_TIMEOUT_SEC = _env_int_with_comment(
    "SOLAR_ROUTER_TIMEOUT_SEC",
    _env_int_with_comment("SOLAR_AI_ROUTER_TIMEOUT_SEC", 310),
)

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
_CLIENT_SCRIPTS = _SCRIPT_DIR.parent.parent / "solar-client" / "scripts"
if str(_CLIENT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CLIENT_SCRIPTS))

from solar_paths import resolve_solar_paths  # noqa: E402

_SOLAR_WORKSPACE, _SOLAR_ROOT = resolve_solar_paths()
_ROUTER_SCRIPT = _SOLAR_ROOT / "core/skills/solar-router/scripts/run_router.py"

REQUIRED_FIELDS = {"type", "request_id", "session_id", "user_id", "text"}


def validate_request(payload: Dict[str, Any]) -> bool:
    return (
        all(k in payload for k in REQUIRED_FIELDS)
        and payload.get("type") == "request"
    )


def n8n_sync_timeout_sec() -> int:
    return _env_int_with_comment("SOLAR_N8N_SYNC_TIMEOUT_SEC", 90)


N8N_SYNC_TIMEOUT_REPLY = "No pude responder a tiempo. Inténtalo de nuevo."


def _failed_router_result(
    payload: Dict[str, Any],
    error_msg: str,
    *,
    error_code: str = "router_crashed",
    reply_text: str = "",
) -> Dict[str, Any]:
    text = reply_text or error_msg
    return {
        "status": "failed",
        "request_id": payload.get("request_id", "n/a"),
        "provider_used": None,
        "reply_text": text,
        "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        "error_code": error_code,
        "error": error_msg,
    }


def _parse_router_stdout(stdout: str, stderr: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    error_msg = (stderr or "").strip() or text or "router failed with no output"
    return _failed_router_result(payload, error_msg)


def call_router(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Forward the full request payload to solar-router v3.
    Returns the parsed router v3 JSON response dict.

    channel=n8n uses a dedicated process group and a 90s budget. On timeout
    that pgid is killed (not the WebSocket server's).
    """
    router_payload = {
        "request_id": payload.get("request_id", "n/a"),
        "session_id": payload.get("session_id", "n/a"),
        "user_id": payload.get("user_id", "n/a"),
        "text": payload["text"],
        "channel": payload.get("channel", "other"),
        "mode": payload.get("mode", "auto"),
        "metadata": payload.get("metadata", {}),
    }
    if payload.get("provider"):
        router_payload["provider"] = payload["provider"]

    cmd = [AI_ROUTER_PYTHON, str(_ROUTER_SCRIPT)]
    stdin_payload = json.dumps(router_payload)
    channel = str(router_payload.get("channel") or "").strip().lower()

    if channel == "n8n":
        timeout = n8n_sync_timeout_sec()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(_SOLAR_WORKSPACE),
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(input=stdin_payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return _failed_router_result(
                payload,
                f"n8n sync budget exceeded ({timeout}s)",
                error_code="n8n_sync_timeout",
                reply_text=N8N_SYNC_TIMEOUT_REPLY,
            )
        return _parse_router_stdout(stdout or "", stderr or "", payload)

    proc = subprocess.run(
        cmd,
        input=stdin_payload,
        text=True,
        capture_output=True,
        timeout=AI_ROUTER_TIMEOUT_SEC,
        cwd=str(_SOLAR_WORKSPACE),
    )
    return _parse_router_stdout(proc.stdout or "", proc.stderr or "", payload)


async def handle_connection(websocket) -> None:
    if websocket.path != PATH:
        await websocket.send(
            json.dumps({
                "type": "response",
                "request_id": "n/a",
                "status": "failed",
                "reply_text": f"Invalid path. Use {PATH}",
                "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
                "error_code": "invalid_path",
                "error": f"Invalid path. Use {PATH}",
            })
        )
        return

    async for raw in websocket:
        request_id = "n/a"
        try:
            payload = json.loads(raw)
            request_id = payload.get("request_id", "n/a")

            if not validate_request(payload):
                raise ValueError("Invalid request payload: missing required fields or type != request")

            router_response = call_router(payload)

            # Envelope: minimal transport metadata + full router v3 response
            response = {
                "type": "response",
                "request_id": request_id,
                **router_response,
            }
        except Exception as exc:
            print(f"[ws-bridge] request failed ({request_id}): {exc}", flush=True)
            traceback.print_exc()
            response = {
                "type": "response",
                "request_id": request_id,
                "status": "failed",
                "provider_used": None,
                "reply_text": str(exc) or "bridge error",
                "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
                "error_code": "bridge_error",
                "error": str(exc),
            }

        await websocket.send(json.dumps(response))


async def main() -> None:
    print(f"solar-transport-gateway listening on ws://{HOST}:{PORT}{PATH}")
    # Keepalive: ping every 60s, wait up to 180s for pong (router timeout is ~310s)
    async with serve(handle_connection, HOST, PORT, ping_interval=60, ping_timeout=180):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
