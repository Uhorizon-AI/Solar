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
import subprocess
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
AI_ROUTER_TIMEOUT_SEC = int(
    os.getenv("SOLAR_ROUTER_TIMEOUT_SEC")
    or os.getenv("SOLAR_AI_ROUTER_TIMEOUT_SEC")
    or "310"
)

# Router script path: repo root is 4 levels up from this script
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_ROUTER_SCRIPT = _REPO_ROOT / "core/skills/solar-router/scripts/run_router.py"

REQUIRED_FIELDS = {"type", "request_id", "session_id", "user_id", "text"}


def validate_request(payload: Dict[str, Any]) -> bool:
    return (
        all(k in payload for k in REQUIRED_FIELDS)
        and payload.get("type") == "request"
    )


def call_router(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Forward the full request payload to solar-router v3.
    Returns the parsed router v3 JSON response dict.
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
    # Pass provider only if explicitly set (strict mode)
    if payload.get("provider"):
        router_payload["provider"] = payload["provider"]

    proc = subprocess.run(
        [AI_ROUTER_PYTHON, str(_ROUTER_SCRIPT)],
        input=json.dumps(router_payload),
        text=True,
        capture_output=True,
        timeout=AI_ROUTER_TIMEOUT_SEC,
    )
    stdout = proc.stdout.strip()

    # Always try to parse stdout as router v3 JSON first — even on non-zero exit.
    # Router emits structured JSON errors (with real error_code) and then exits 1.
    if stdout:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            pass

    # Fallback: no parseable JSON at all (crash, binary not found, etc.)
    error_msg = proc.stderr.strip() or stdout or "router failed with no output"
    return {
        "status": "failed",
        "request_id": payload.get("request_id", "n/a"),
        "provider_used": None,
        "reply_text": error_msg,
        "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        "error_code": "router_crashed",
        "error": error_msg,
    }


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
