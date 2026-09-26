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
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
import re
import secrets
import threading
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import time
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4
import sys

_PATHS_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "solar-paths" / "scripts"
if str(_PATHS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATHS_SCRIPTS))
import solar_runtime  # noqa: E402

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

# Ledger TTL (replay snapshots). HTTP 202 / in-memory poll jobs are not production.
_N8N_JOB_TTL_SECONDS = int(os.getenv("SOLAR_N8N_JOB_TTL_SECONDS", "7200"))
_SOLAR_N8N_DEFAULT_ASYNC = os.getenv("SOLAR_N8N_DEFAULT_ASYNC", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
SOLAR_N8N_WEBHOOK_SECRET = os.getenv("SOLAR_N8N_WEBHOOK_SECRET", "").strip()
_N8N_POLL_DISABLED_ERROR = (
    "HTTP 202 / poll is not part of the production contract. Use a single synchronous POST."
)
_n8n_ledger_lock = threading.Lock()


def _header_get(headers: Any, name: str) -> Optional[str]:
    if headers is None:
        return None
    target = name.lower()
    getter = getattr(headers, "get", None)
    if callable(getter):
        direct = getter(name)
        if direct not in (None, ""):
            return str(direct)
    try:
        items = headers.items()
    except Exception:
        items = []
    for key, value in items:
        if str(key).lower() == target:
            return str(value) if value is not None else None
    return None


def check_n8n_secret(headers: Any) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Return (status, body) if auth fails. Fail-closed when the secret is unset."""
    if not SOLAR_N8N_WEBHOOK_SECRET:
        return (
            HTTPStatus.UNAUTHORIZED,
            {
                "status": "failed",
                "error": "n8n webhook secret is not configured",
                "bridge": BRIDGE_NAME,
            },
        )
    auth = _header_get(headers, "Authorization") or ""
    scheme, _, rest = auth.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        return (
            HTTPStatus.UNAUTHORIZED,
            {
                "status": "failed",
                "error": "missing Authorization Bearer",
                "bridge": BRIDGE_NAME,
            },
        )
    token = rest.strip()
    if not secrets.compare_digest(token, SOLAR_N8N_WEBHOOK_SECRET):
        return (
            HTTPStatus.FORBIDDEN,
            {
                "status": "failed",
                "error": "invalid n8n webhook secret",
                "bridge": BRIDGE_NAME,
            },
        )
    return None


def telegram_chat_allowed(chat_id: str) -> bool:
    cid = str(chat_id or "").strip()
    if not cid:
        return False
    allowed_raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if allowed_raw:
        allowed = {part.strip() for part in allowed_raw.split(",") if part.strip()}
        return cid in allowed
    default = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return bool(default) and cid == default


def session_matches_chat(session_id: str, chat_id: str) -> bool:
    cid = str(chat_id or "").strip()
    sid = str(session_id or "").strip()
    if not cid or not sid.startswith("telegram:"):
        return True
    return sid[len("telegram:") :] == cid


def n8n_ledger_dir() -> Path:
    run_dir = Path(os.getenv("SOLAR_GATEWAY_RUN_DIR", "/tmp/solar-transport-gateway"))
    jobs = run_dir / "n8n-jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(jobs, 0o700)
    except OSError:
        pass
    return jobs


def n8n_ledger_key(request_id: str) -> str:
    return hashlib.sha256(str(request_id).encode("utf-8")).hexdigest()


def n8n_ledger_path(request_id: str) -> Path:
    return n8n_ledger_dir() / f"{n8n_ledger_key(request_id)}.json"


@contextmanager
def n8n_request_lock(request_id: str):
    """Serialize the full request transaction, including across bridge processes.

    Keep the lock inode: unlinking it can let a new caller bypass existing waiters.
    The OS releases flock automatically if the process exits.
    """
    path = n8n_ledger_dir() / f"{n8n_ledger_key(request_id)}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def n8n_ledger_load(request_id: str) -> Optional[Dict[str, Any]]:
    path = n8n_ledger_path(request_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ts = float(data.get("ts") or 0)
    if _N8N_JOB_TTL_SECONDS > 0 and ts and (time() - ts) > _N8N_JOB_TTL_SECONDS:
        return None
    return data


def n8n_ledger_save(request_id: str, http_status: int, body: Dict[str, Any]) -> None:
    path = n8n_ledger_path(request_id)
    payload = {
        "request_id": request_id,
        "http_status": int(http_status),
        "body": body,
        "ts": time(),
    }
    tmp = path.with_name(path.name + ".tmp")
    with _n8n_ledger_lock:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def n8n_poll_disabled_body(request_id: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "status": "failed",
        "error": _N8N_POLL_DISABLED_ERROR,
        "bridge": BRIDGE_NAME,
        "reply_text": "Could not take this request in async mode.",
    }
    if request_id:
        body["request_id"] = request_id
    return body


def find_task_for_origin_request(origin_request_id: str) -> Optional[str]:
    """Return task_id if a task already correlates to this origin_request_id.

    Refuses when the runtime format is not sqlite.
    """
    rid = str(origin_request_id or "").strip()
    if not rid:
        return None
    scripts = Path(__file__).resolve().parents[2] / "solar-state" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import solar_state
    with solar_state.session() as store:
        return store.task_find_origin(rid)


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
        "message_id": str(msg.get("message_id") or ""),
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

_CHANNEL_RE = re.compile(r"^[a-z0-9_-]+$")
_IDENTITY_ERRORS = {
    "identity_incomplete": "Missing channel or conversation_id.",
    "invalid_channel": "Invalid channel.",
    "session_chat_mismatch": "session_id and chat_id do not match.",
}


def _encode_part(value: str) -> str:
    """Escape the separator so composed ids stay unambiguous.

    Without it, conversation a:b + message c and conversation a + message b:c
    would both compose ...:a:b:c. Numeric ids (Telegram) are unchanged.
    """
    return value.replace("%", "%25").replace(":", "%3A")


def compose_identity(
    channel: str, conversation_id: str, message_id: str = ""
) -> Dict[str, str]:
    """Platform-agnostic message identity.

    channel         platform the message comes from (telegram, whatsapp, app)
    conversation_id native address to reply to (Telegram chat.id, WhatsApp JID)
    message_id      native message id; unique only inside its conversation
    session_id      Solar continuity key = channel:conversation_id
    request_id      Solar idempotency key = channel:conversation_id:message_id

    Solar composes these from the parts; it never splits a composed id back.
    channel must match _CHANNEL_RE and the other parts escape '%' and ':', so
    two different part sets never compose the same id.
    """
    session_id = f"{channel}:{_encode_part(conversation_id)}"
    identity = {"session_id": session_id, "request_id": ""}
    if message_id:
        identity["request_id"] = f"{session_id}:{_encode_part(message_id)}"
    return identity


def parse_n8n_request(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse an n8n body. `identity_error` is set when the identity is unusable.

    With parts (channel, conversation_id, message_id) Solar composes session_id
    and request_id. Without parts the legacy body is used as sent. A missing
    session_id stays empty so the router falls back to user_id instead of a
    shared default session.
    """
    chat_id = str(payload.get("chat_id") or "").strip()
    if payload.get("type") == "request":
        text = str(payload.get("text", ""))
        if not text:
            return None
        channel = str(payload.get("channel") or "").strip().lower()
        conversation_id = str(payload.get("conversation_id") or "").strip()
        message_id = str(payload.get("message_id") or "").strip()
        request_id = str(payload.get("request_id", f"n8n_{uuid4().hex[:12]}"))
        session_id = str(payload.get("session_id") or "").strip()
        identity_error = ""
        if channel or conversation_id or message_id:
            if not (channel and conversation_id):
                identity_error = "identity_incomplete"
            elif not _CHANNEL_RE.match(channel):
                identity_error = "invalid_channel"
            else:
                identity = compose_identity(channel, conversation_id, message_id)
                # A legacy session_id sent alongside the parts must agree with them.
                if session_id and session_id != identity["session_id"]:
                    identity_error = "session_chat_mismatch"
                session_id = identity["session_id"]
                request_id = identity["request_id"] or request_id
                # Only Telegram has a notifier today: its conversation is the reply chat.
                chat_id = conversation_id if channel == "telegram" else ""
        elif chat_id and not session_matches_chat(session_id, chat_id):
            identity_error = "session_chat_mismatch"
        return {
            "request_id": request_id,
            "session_id": session_id,
            "user_id": str(payload.get("user_id", "n8n-user")),
            "text": text,
            "chat_id": chat_id,
            "identity_error": identity_error,
        }

    text = payload.get("text") or payload.get("message_text") or payload.get("message")
    if not text and isinstance(payload.get("body"), dict):
        body = payload["body"]
        text = body.get("text") or body.get("message_text")
        if not chat_id:
            chat_id = str(body.get("chat_id") or "").strip()
    if not text:
        return None

    session_id = str(payload.get("session_id") or "").strip()
    identity_error = ""
    if chat_id and not session_matches_chat(session_id, chat_id):
        identity_error = "session_chat_mismatch"
    return {
        "request_id": str(payload.get("request_id", f"n8n_{uuid4().hex[:12]}")),
        "session_id": session_id,
        "user_id": str(payload.get("user_id", "n8n-user")),
        "text": str(text),
        "chat_id": chat_id,
        "identity_error": identity_error,
    }


def n8n_wants_async(path: str, body: Dict[str, Any]) -> bool:
    """True if client opted into the retired fast ACK + poll contract."""
    parsed = urllib.parse.urlparse(path)
    qs = urllib.parse.parse_qs(parsed.query)
    flag = (qs.get("async") or [""])[0].lower()
    if flag in ("1", "true", "yes"):
        return True
    if body.get("async") is True:
        return True
    if str(body.get("async", "")).lower() in ("1", "true", "yes"):
        return True
    return False


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

    def write_n8n_json(
        self, status: HTTPStatus, payload: Dict[str, Any], request_id: Optional[str] = None
    ) -> None:
        if request_id:
            try:
                n8n_ledger_save(request_id, int(status), payload)
            except OSError as err:
                print(f"[http-bridge] n8n ledger save failed ({request_id}): {err}", flush=True)
        self.write_json(status, payload)

    def _drain_body(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except (TypeError, ValueError):
            length = 0
        if length > 0:
            self.rfile.read(length)

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
    def n8n_result_path() -> str:
        return f"{SOLAR_HTTP_WEBHOOK_BASE}/n8n/result"

    def do_GET_n8n_result(self, parsed_path: urllib.parse.ParseResult) -> bool:
        """Handle GET .../webhook/n8n/result. Production contract: always failed (no poll)."""
        clean = parsed_path.path.split("?", 1)[0].rstrip("/")
        expected = self.n8n_result_path().rstrip("/")
        if clean != expected:
            return False
        auth_fail = check_n8n_secret(self.headers)
        if auth_fail is not None:
            code, body = auth_fail
            self.write_json(code, body)
            return True
        qs = urllib.parse.parse_qs(parsed_path.query)
        request_id = (qs.get("request_id") or [None])[0]
        self.write_json(HTTPStatus.OK, n8n_poll_disabled_body(request_id))
        return True

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
        parsed = urllib.parse.urlparse(self.path)
        if self.do_GET_n8n_result(parsed):
            return
        if parsed.path == "/health":
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

        if channel == "n8n":
            auth_fail = check_n8n_secret(self.headers)
            if auth_fail is not None:
                self._drain_body()
                code, body = auth_fail
                self.write_json(code, body)
                return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            update = json.loads(raw.decode("utf-8"))

            if channel == "telegram":
                if not TELEGRAM_BOT_TOKEN:
                    self.write_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {
                            "status": "failed",
                            "error": "Telegram not configured (set TELEGRAM_BOT_TOKEN)",
                            "bridge": BRIDGE_NAME,
                        },
                    )
                    return
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

                identity = compose_identity(
                    "telegram", parsed["chat_id"], parsed["message_id"]
                )
                request_payload = {
                    "type": "request",
                    "request_id": identity["request_id"] or f"tg_{uuid4().hex[:12]}",
                    "session_id": identity["session_id"],
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

                rid = parsed_n8n["request_id"]
                identity_error = parsed_n8n.get("identity_error") or ""
                if identity_error:
                    # Checked before the ledger: never replay another request's
                    # response to a bad identity, and never store the rejection,
                    # so a corrected body with the same request_id still runs.
                    self.write_json(
                        HTTPStatus.OK,
                        {
                            "status": "failed",
                            "request_id": rid,
                            "bridge": BRIDGE_NAME,
                            "reply_text": _IDENTITY_ERRORS[identity_error],
                            "error": identity_error,
                        },
                    )
                    return

                with n8n_request_lock(rid):
                    replay = n8n_ledger_load(rid)
                    if replay is not None:
                        saved = replay.get("body") or {}
                        status = HTTPStatus(int(replay.get("http_status") or 200))
                        self.write_json(status, saved)
                        return

                    if n8n_wants_async(self.path, update) or _SOLAR_N8N_DEFAULT_ASYNC:
                        body = n8n_poll_disabled_body(rid)
                        self.write_n8n_json(HTTPStatus.OK, body, rid)
                        return

                    chat_id = parsed_n8n.get("chat_id") or ""
                    origin_ok = bool(chat_id) and telegram_chat_allowed(chat_id)
                    if chat_id and not origin_ok:
                        body = {
                            "status": "failed",
                            "request_id": rid,
                            "bridge": BRIDGE_NAME,
                            "reply_text": "Chat not authorized.",
                            "error": "chat_not_allowed",
                        }
                        self.write_n8n_json(HTTPStatus.OK, body, rid)
                        return

                    correlated = find_task_for_origin_request(rid)
                    if correlated:
                        from_ack = {
                            "status": "success",
                            "request_id": rid,
                            "bridge": BRIDGE_NAME,
                            "route": self.path.split("?", 1)[0],
                            "reply_text": (
                                "On it. I'll let you know here when it's done."
                                f"\n\n(Task: {correlated})"
                            ),
                            "decision": {
                                "kind": "async_draft_created",
                                "task_id": correlated,
                                "queued": True,
                            },
                        }
                        self.write_n8n_json(HTTPStatus.OK, from_ack, rid)
                        return

                    metadata: Dict[str, Any] = {}
                    if origin_ok:
                        metadata = {
                            "origin_channel": "telegram",
                            "origin_chat_id": chat_id,
                            "origin_request_id": rid,
                            "chat_id": chat_id,
                        }

                    request_payload = {
                        "type": "request",
                        "request_id": rid,
                        "session_id": parsed_n8n["session_id"],
                        "user_id": parsed_n8n["user_id"],
                        "text": parsed_n8n["text"],
                        "channel": "n8n",
                        "mode": "auto",
                        "metadata": metadata,
                    }

                    response = asyncio.run(request_solar(request_payload))
                    body = {
                        "bridge": BRIDGE_NAME,
                        "route": self.path.split("?", 1)[0],
                        **response,
                    }
                    self.write_n8n_json(HTTPStatus.OK, body, rid)
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
        print(
            "[http-bridge] TELEGRAM_BOT_TOKEN unset: /webhook/telegram disabled; "
            "/webhook/n8n still works.",
            flush=True,
        )
    if SOLAR_N8N_WEBHOOK_SECRET:
        print(
            "[http-bridge] SOLAR_N8N_WEBHOOK_SECRET set: "
            "/webhook/n8n requires Authorization: Bearer.",
            flush=True,
        )
    else:
        print(
            "[http-bridge] SOLAR_N8N_WEBHOOK_SECRET unset: /webhook/n8n is fail-closed (401).",
            flush=True,
        )
    server = ThreadingHTTPServer((SOLAR_HTTP_HOST, SOLAR_HTTP_PORT), WebhookHandler)
    print(
        f"solar-webhook listening on http://{SOLAR_HTTP_HOST}:{SOLAR_HTTP_PORT}"
        f"{SOLAR_HTTP_WEBHOOK_BASE}/<channel>"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
