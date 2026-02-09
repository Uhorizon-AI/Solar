#!/usr/bin/env python3
import asyncio
import json
import os
from typing import Any, Dict, List, Tuple

try:
    from websockets.server import serve
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: websockets. Install with: pip install websockets"
    ) from exc


HOST = os.getenv("SOLAR_WS_HOST", "127.0.0.1")
PORT = int(os.getenv("SOLAR_WS_PORT", "8765"))
PATH = os.getenv("SOLAR_WS_PATH", "/ws")
SUPPORTED_PROVIDERS = ("codex", "claude", "gemini")
AI_PROVIDER_PRIORITY = os.getenv(
    "SOLAR_AI_PROVIDER_PRIORITY", "codex,claude,gemini"
)


def validate_request(payload: Dict[str, Any]) -> bool:
    required = ["type", "request_id", "session_id", "user_id", "text"]
    return all(k in payload for k in required) and payload.get("type") == "request"


def parse_csv(value: str) -> List[str]:
    return [x.strip().lower() for x in value.split(",") if x.strip()]


def dedupe(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def select_provider() -> Tuple[str, List[str]]:
    configured = parse_csv(AI_PROVIDER_PRIORITY)
    ordered = [p for p in configured if p in SUPPORTED_PROVIDERS]
    ordered = dedupe(ordered)
    if not ordered:
        ordered = list(SUPPORTED_PROVIDERS)

    provider = ordered[0]
    backups = ordered[1:] if len(ordered) > 1 else []
    return provider, backups


def call_provider(provider: str, text: str, payload: Dict[str, Any]) -> str:
    # Provider stubs. Replace with real API calls while keeping same interface.
    if provider in SUPPORTED_PROVIDERS:
        return f"[{provider}] {text}"
    return text


async def handle_connection(websocket) -> None:
    if websocket.path != PATH:
        await websocket.send(
            json.dumps(
                {
                    "type": "response",
                    "request_id": "n/a",
                    "status": "failed",
                    "reply_text": f"Invalid path. Use {PATH}",
                }
            )
        )
        return

    async for raw in websocket:
        request_id = "n/a"
        try:
            payload = json.loads(raw)
            request_id = payload.get("request_id", "n/a")

            if not validate_request(payload):
                raise ValueError("Invalid request payload")

            provider, backups = select_provider()
            provider_used = provider
            try:
                reply = call_provider(provider, payload["text"], payload)
            except Exception:
                reply = ""
                for backup in backups:
                    try:
                        reply = call_provider(backup, payload["text"], payload)
                        provider_used = backup
                        break
                    except Exception:
                        continue
                if not reply:
                    raise

            response = {
                "type": "response",
                "request_id": request_id,
                "status": "success",
                "reply_text": reply,
                "provider_used": provider_used,
            }
        except Exception:
            response = {
                "type": "response",
                "request_id": request_id,
                "status": "failed",
                "reply_text": "Invalid request payload.",
            }

        await websocket.send(json.dumps(response))


async def main() -> None:
    print(f"solar-transport-gateway listening on ws://{HOST}:{PORT}{PATH}")
    async with serve(handle_connection, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
