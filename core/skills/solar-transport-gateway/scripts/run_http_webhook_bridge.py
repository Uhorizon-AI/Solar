#!/usr/bin/env python3
"""
solar-transport-gateway HTTP webhook bridge v3.

Responsibilities:
- Telegram: dedup + ACK fast, delegate to WS bridge with channel=telegram/mode=auto,
  handle decision.kind for direct_reply vs async flow.
- n8n: delegate to WS bridge with channel=n8n/mode=auto,
  expose router v3 JSON directly (no legacy double-wrapper).
- No provider selection, no fallback, no async policy here.
"""
import asyncio
import json
import os
import threading
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import time
from typing import Any, Dict, Optional
from uuid import uuid4

try:
    from websockets.client import connect
except Exception as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: websockets") from exc


SOLAR_HTTP_HOST = os.getenv("SOLAR_HTTP_HOST", "127.0.0.1")
SOLAR_HTTP_PORT = int(os.getenv("SOLAR_HTTP_PORT", "8787"))
SOLAR_HTTP_WEBHOOK_BASE = os.getenv("SOLAR_HTTP_WEBHOOK_BASE", "/webhook").rstrip("/")

SOLAR_WS_HOST = os.getenv("SOLAR_WS_HOST", "127.0.0.1")
SOLAR_WS_PORT = int(os.getenv("SOLAR_WS_PORT", "8765"))
SOLAR_WS_PATH = os.getenv("SOLAR_WS_PATH", "/ws")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_PARSE_MODE = os.getenv("TELEGRAM_PARSE_MODE", "Markdown")
TELEGRAM_DISABLE_PREVIEW = os.getenv("TELEGRAM_DISABLE_PREVIEW", "true")
BRIDGE_NAME = "solar-transport-gateway"
BRIDGE_ROUTE_PATTERN = f"{SOLAR_HTTP_WEBHOOK_BASE}/<channel>"
TELEGRAM_DEDUP_TTL_SECONDS = int(os.getenv("SOLAR_TELEGRAM_DEDUP_TTL_SECONDS", "43200"))
_processed_updates: Dict[str, float] = {}
_inflight_updates: set[str] = set()
_updates_lock = threading.Lock()


# ---------------------------------------------------------------------------
# WS bridge communication
# ---------------------------------------------------------------------------

async def request_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
    ws_url = f"ws://{SOLAR_WS_HOST}:{SOLAR_WS_PORT}{SOLAR_WS_PATH}"
    # Keepalive: ping every 60s, wait up to 180s for pong (router timeout ~310s)
    async with connect(ws_url, ping_interval=60, ping_timeout=180) as ws:
        await ws.send(json.dumps(payload))
        raw = await ws.recv()
        return json.loads(raw)


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def send_telegram(chat_id: str, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": TELEGRAM_PARSE_MODE,
            "disable_web_page_preview": TELEGRAM_DISABLE_PREVIEW,
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20):
        pass


def parse_telegram_update(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    msg = payload.get("message") or {}
    text = msg.get("text")
    chat = msg.get("chat") or {}
    from_user = msg.get("from") or {}
    if not text or "id" not in chat:
        return None
    return {
        "chat_id": str(chat["id"]),
        "user_id": str(from_user.get("id", "unknown")),
        "text": str(text),
    }


def telegram_update_key(payload: Dict[str, Any]) -> str:
    update_id = payload.get("update_id")
    if update_id is not None:
        return f"telegram:update:{update_id}"
    msg = payload.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id", "unknown")
    message_id = msg.get("message_id", "unknown")
    date = msg.get("date", "unknown")
    return f"telegram:fallback:{chat_id}:{message_id}:{date}"


def reserve_telegram_update(key: str) -> bool:
    now = time()
    with _updates_lock:
        if TELEGRAM_DEDUP_TTL_SECONDS > 0:
            expired = [
                k for k, ts in _processed_updates.items()
                if now - ts > TELEGRAM_DEDUP_TTL_SECONDS
            ]
            for k in expired:
                _processed_updates.pop(k, None)
        if key in _processed_updates or key in _inflight_updates:
            return False
        _inflight_updates.add(key)
        return True


def finish_telegram_update(key: str, success: bool) -> None:
    with _updates_lock:
        _inflight_updates.discard(key)
        if success:
            _processed_updates[key] = time()


# ---------------------------------------------------------------------------
# n8n helpers
# ---------------------------------------------------------------------------

def parse_n8n_request(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if payload.get("type") == "request":
        text = str(payload.get("text", ""))
        if not text:
            return None
        return {
            "request_id": str(payload.get("request_id", f"n8n_{uuid4().hex[:12]}")),
            "session_id": str(payload.get("session_id", "n8n:default")),
            "user_id": str(payload.get("user_id", "n8n-user")),
            "text": text,
        }

    text = payload.get("text") or payload.get("message_text") or payload.get("message")
    if not text and isinstance(payload.get("body"), dict):
        text = payload["body"].get("text") or payload["body"].get("message_text")
    if not text:
        return None

    return {
        "request_id": str(payload.get("request_id", f"n8n_{uuid4().hex[:12]}")),
        "session_id": str(payload.get("session_id", "n8n:default")),
        "user_id": str(payload.get("user_id", "n8n-user")),
        "text": str(text),
    }


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

class WebhookHandler(BaseHTTPRequestHandler):
    def write_json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    @staticmethod
    def channel_from_path(path: str) -> Optional[str]:
        clean_path = path.split("?", 1)[0].rstrip("/")
        prefix = f"{SOLAR_HTTP_WEBHOOK_BASE}/"
        if not clean_path.startswith(prefix):
            return None
        channel = clean_path[len(prefix):]
        if "/" in channel or not channel:
            return None
        return channel

    @staticmethod
    def process_telegram_async(
        dedup_key: str,
        request_payload: Dict[str, Any],
        chat_id: str,
    ) -> None:
        success = False
        try:
            response = asyncio.run(request_solar(request_payload))
            decision_kind = (response.get("decision") or {}).get("kind", "direct_reply")
            reply_text = response.get("reply_text", "No response from solar.")

            if decision_kind == "direct_reply":
                send_telegram(chat_id, reply_text)
            else:
                # async_draft_proposal / async_draft_created / async_activation_needed
                # Send control message to user
                send_telegram(chat_id, reply_text)
            success = True
        except Exception as exc:
            print(f"[http-bridge] telegram async processing failed ({dedup_key}): {exc}")
        finally:
            finish_telegram_update(dedup_key, success)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps(
                {
                    "status": "ok",
                    "bridge": BRIDGE_NAME,
                    "route": BRIDGE_ROUTE_PATTERN,
                }
            ).encode("utf-8")
            self.wfile.write(body)
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_POST(self) -> None:
        channel = self.channel_from_path(self.path)
        if channel is None:
            self.write_json(
                HTTPStatus.NOT_FOUND,
                {"status": "failed", "error": "Unknown route"},
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            update = json.loads(raw.decode("utf-8"))

            if channel == "telegram":
                parsed = parse_telegram_update(update)
                if parsed is None:
                    raise ValueError("Unsupported Telegram payload")

                dedup_key = telegram_update_key(update)
                if not reserve_telegram_update(dedup_key):
                    self.write_json(
                        HTTPStatus.OK,
                        {
                            "status": "ok",
                            "ok": True,
                            "duplicate": True,
                            "bridge": BRIDGE_NAME,
                            "route": self.path.split("?", 1)[0],
                            "channel": channel,
                        },
                    )
                    return

                request_payload = {
                    "type": "request",
                    "request_id": f"tg_{uuid4().hex[:12]}",
                    "session_id": f"telegram:{parsed['chat_id']}",
                    "user_id": parsed["user_id"],
                    "text": parsed["text"],
                    "channel": "telegram",
                    "mode": "auto",
                }
                # ACK immediately to Telegram (must respond within 5s)
                self.write_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "ok": True,
                        "accepted": True,
                        "bridge": BRIDGE_NAME,
                        "route": self.path.split("?", 1)[0],
                        "channel": channel,
                        "request_id": request_payload["request_id"],
                    },
                )
                threading.Thread(
                    target=self.process_telegram_async,
                    args=(dedup_key, request_payload, parsed["chat_id"]),
                    daemon=True,
                ).start()
                return

            elif channel == "n8n":
                parsed_n8n = parse_n8n_request(update)
                if parsed_n8n is None:
                    raise ValueError("Unsupported n8n payload")

                request_payload = {
                    "type": "request",
                    "request_id": parsed_n8n["request_id"],
                    "session_id": parsed_n8n["session_id"],
                    "user_id": parsed_n8n["user_id"],
                    "text": parsed_n8n["text"],
                    "channel": "n8n",
                    "mode": "auto",
                }
                response = asyncio.run(request_solar(request_payload))

                # n8n: expose router v3 JSON directly, minimal bridge metadata only
                self.write_json(
                    HTTPStatus.OK,
                    {
                        "bridge": BRIDGE_NAME,
                        "route": self.path.split("?", 1)[0],
                        **response,
                    },
                )
                return

            else:
                raise ValueError(f"Unsupported channel: {channel}")

        except Exception as exc:  # pragma: no cover
            self.write_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "status": "failed",
                    "bridge": BRIDGE_NAME,
                    "route": self.path.split("?", 1)[0],
                    "error": str(exc),
                },
            )

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")
    server = ThreadingHTTPServer((SOLAR_HTTP_HOST, SOLAR_HTTP_PORT), WebhookHandler)
    print(
        f"solar-webhook listening on http://{SOLAR_HTTP_HOST}:{SOLAR_HTTP_PORT}"
        f"{SOLAR_HTTP_WEBHOOK_BASE}/<channel>"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
