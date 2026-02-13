#!/usr/bin/env python3
import asyncio
import json
import os
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
BRIDGE_ROUTE_PATTERN = f"{SOLAR_HTTP_WEBHOOK_BASE}/<provider>"


async def request_solar(payload: Dict[str, Any]) -> Dict[str, Any]:
    ws_url = f"ws://{SOLAR_WS_HOST}:{SOLAR_WS_PORT}{SOLAR_WS_PATH}"
    # Keepalive config: ping every 60s, wait up to 180s for pong (AI router timeout is 120s)
    async with connect(ws_url, ping_interval=60, ping_timeout=180) as ws:
        await ws.send(json.dumps(payload))
        raw = await ws.recv()
        return json.loads(raw)


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


def parse_update(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
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


def parse_n8n_request(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    # Accept native contract first.
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

    # Fallback mapping for common n8n payload shapes.
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


class WebhookHandler(BaseHTTPRequestHandler):
    @staticmethod
    def provider_from_path(path: str) -> Optional[str]:
        clean_path = path.split("?", 1)[0].rstrip("/")
        prefix = f"{SOLAR_HTTP_WEBHOOK_BASE}/"
        if not clean_path.startswith(prefix):
            return None
        provider = clean_path[len(prefix):]
        if "/" in provider or not provider:
            return None
        return provider

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
        provider = self.provider_from_path(self.path)
        if provider is None:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            update = json.loads(raw.decode("utf-8"))
            if provider == "telegram":
                parsed = parse_update(update)
                if parsed is None:
                    raise ValueError("Unsupported Telegram payload")
                request_payload = {
                    "type": "request",
                    "request_id": f"tg_{uuid4().hex[:12]}",
                    "session_id": f"telegram:{parsed['chat_id']}",
                    "user_id": parsed["user_id"],
                    "text": parsed["text"],
                }
            elif provider == "n8n":
                parsed_n8n = parse_n8n_request(update)
                if parsed_n8n is None:
                    raise ValueError("Unsupported n8n payload")
                request_payload = {
                    "type": "request",
                    "request_id": parsed_n8n["request_id"],
                    "session_id": parsed_n8n["session_id"],
                    "user_id": parsed_n8n["user_id"],
                    "text": parsed_n8n["text"],
                }
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            response = asyncio.run(request_solar(request_payload))
            reply_text = response.get("reply_text", "No response from solar.")
            if provider == "telegram":
                send_telegram(parsed["chat_id"], reply_text)

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_value = response.get("status", "success")
            ok_value = status_value == "success"
            body = json.dumps(
                {
                    "status": "ok",
                    "ok": ok_value,
                    "bridge": BRIDGE_NAME,
                    "route": self.path.split("?", 1)[0],
                    "provider": provider,
                    "request_id": request_payload["request_id"],
                    "output": reply_text,
                    "reply_text": reply_text,
                    "text": reply_text,
                    "provider_used": response.get("provider_used", "unknown"),
                    "solar_status": status_value,
                    "solar_response": response,
                }
            ).encode("utf-8")
            self.wfile.write(body)
        except Exception as exc:  # pragma: no cover
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps(
                {
                    "status": "failed",
                    "bridge": BRIDGE_NAME,
                    "route": self.path.split("?", 1)[0],
                    "error": str(exc),
                }
            ).encode("utf-8")
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep runtime logs concise.
        return


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")
    server = ThreadingHTTPServer((SOLAR_HTTP_HOST, SOLAR_HTTP_PORT), WebhookHandler)
    print(
        f"solar-webhook listening on http://{SOLAR_HTTP_HOST}:{SOLAR_HTTP_PORT}"
        f"{SOLAR_HTTP_WEBHOOK_BASE}/<provider>"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
