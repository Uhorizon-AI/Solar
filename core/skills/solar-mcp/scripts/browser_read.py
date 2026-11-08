"""One scoped browser read: WhatsApp Web session status and visible chat count.

The caller supplies nothing. The destination, the script and the fields it returns
are constants in this file, so the authorization of an operation that runs this is
exactly its name: it cannot open a chat, visit another origin, read a message or
account data, run a script of the caller's or send anything.

The browser is the shared Solar runtime (`solar-browser`): started and stopped
through `ensure_browser.sh`, never launched here. Only a tab this module opens is
touched, and it is closed afterwards.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from mcp_context import OperationError

DESTINATION = "https://web.whatsapp.com/"
ALLOWED_ORIGIN = "https://web.whatsapp.com"

# The whole read. It returns three scalars; it opens nothing, types nothing, and never
# returns text from a chat (titles are only counted).
READ_EXPRESSION = r"""(() => {
  const qr = !!document.querySelector(
    '[data-testid="qrcode"], canvas[aria-label*="QR"], [data-ref] canvas');
  const pane = document.querySelector('#pane-side');
  const rows = pane
    ? Array.from(pane.querySelectorAll('[role="row"], [role="listitem"]'))
        .filter(item => item.querySelector('span[title]:not([title=""])')).length
    : 0;
  return {origin: location.origin, qr: qr, pane: !!pane, rows: rows};
})()"""

_SCRIPTS = Path(__file__).resolve().parents[2] / "solar-browser" / "scripts"
_POLL_SECONDS = 1.0
_READ_DEADLINE = 45.0
_STABLE_POLLS = 3


# --- minimal CDP over a stdlib websocket (no dependency) ------------------------------

class _Socket:
    def __init__(self, url: str, timeout: float):
        parts = urlsplit(url)
        if parts.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise OperationError("browser_unavailable", "The debugging endpoint is not local")
        raw = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout)
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        raw.sendall((f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                     f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                     f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = raw.recv(1024)
            if not chunk:
                raise OperationError("browser_unavailable", "The debugging socket closed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OperationError("browser_unavailable", "The debugging socket was refused")
        self.buffer = head.split(b"\r\n\r\n", 1)[1]

    def send(self, text: str) -> None:
        data = text.encode()
        header = bytearray([0x81])
        size = len(data)
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", size)
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OperationError("browser_unavailable", "The debugging socket closed")
            self.buffer += chunk
        out, self.buffer = self.buffer[:count], self.buffer[count:]
        return out

    def receive(self) -> str:
        message = b""
        while True:
            first, second = self._read(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(size)
            opcode = first & 0x0F
            if opcode == 8:
                raise OperationError("browser_unavailable", "The debugging socket closed")
            if opcode in (9, 10):
                continue
            message += payload
            if first & 0x80:
                return message.decode()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class _Page:
    def __init__(self, socket_: _Socket):
        self.socket = socket_
        self.counter = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        self.counter += 1
        mine = self.counter
        self.socket.sock.settimeout(timeout)
        self.socket.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
        while True:
            try:
                reply = json.loads(self.socket.receive())
            except socket.timeout:
                raise OperationError("whatsapp_read_failed", "The page did not answer in time") from None
            if reply.get("id") == mine:
                if "error" in reply:
                    raise OperationError("whatsapp_read_failed", "The browser refused the read")
                return reply.get("result", {})


# --- lifecycle ------------------------------------------------------------------------

def _endpoint() -> str:
    host = os.environ.get("SOLAR_BROWSER_DEBUG_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_BROWSER_DEBUG_PORT", "9222")
    if host not in ("127.0.0.1", "localhost", "::1") or not port.isdigit():
        raise OperationError("browser_unavailable", "The debugging endpoint must be local")
    return f"http://{host}:{port}"


def _http(url: str, method: str = "GET") -> dict | str:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=5) as answer:  # noqa: S310 - loopback only
        text = answer.read().decode()
    try:
        return json.loads(text)
    except ValueError:
        return text


def _ready(endpoint: str) -> bool:
    try:
        _http(f"{endpoint}/json/version")
        return True
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _ensure(flag: str) -> bool:
    script = _SCRIPTS / "ensure_browser.sh"
    try:
        done = subprocess.run(["bash", str(script), flag], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


# --- the read -------------------------------------------------------------------------

def _classify(read: dict, allowed_origin: str) -> tuple[str, dict] | None:
    """A settled answer, or None while WhatsApp Web is still loading."""
    if read.get("origin") != allowed_origin:
        raise OperationError("browser_scope_denied",
                             "The page left the authorized WhatsApp Web origin; nothing was read")
    if read.get("qr"):
        return "qr_required", {}
    if read.get("pane"):
        return "active", {"visible_chats": int(read.get("rows", 0))}
    return None


def whatsapp_status(destination: str = DESTINATION, allowed_origin: str = ALLOWED_ORIGIN,
                    deadline: float = _READ_DEADLINE, poll: float = _POLL_SECONDS) -> dict:
    """Session status, QR presence and visible chat count of WhatsApp Web, or a distinct refusal."""
    endpoint = _endpoint()
    started_here = False
    if not _ready(endpoint):
        if not _ensure("--start") or not _ready(endpoint):
            raise OperationError("browser_unavailable", "The Solar browser could not be started")
        started_here = True
    target = None
    page = None
    try:
        try:
            target = _http(f"{endpoint}/json/new?about:blank", method="PUT")
        except (OSError, urllib.error.URLError, ValueError):
            raise OperationError("browser_unavailable", "The browser did not open a tab") from None
        page = _Page(_Socket(target["webSocketDebuggerUrl"], 10))
        page.call("Page.enable")
        page.call("Page.navigate", {"url": destination})
        limit = time.monotonic() + deadline
        last, stable = None, 0
        while time.monotonic() < limit:
            time.sleep(poll)
            answer = page.call("Runtime.evaluate", {
                "expression": READ_EXPRESSION, "returnByValue": True, "awaitPromise": False})
            value = (answer.get("result") or {}).get("value")
            if not isinstance(value, dict):
                continue
            settled = _classify(value, allowed_origin)
            if settled is None:
                last, stable = None, 0
                continue
            # An empty list can still be loading; require the same answer a few polls in a row.
            if settled == last:
                stable += 1
            else:
                last, stable = settled, 1
            if settled[0] == "qr_required" and stable >= 2:
                raise OperationError("whatsapp_session_expired",
                                     "WhatsApp Web asks to link the device again (QR shown)")
            if settled[0] == "active" and (settled[1]["visible_chats"] > 0 or stable >= _STABLE_POLLS):
                return {"status": "active", "qr_present": False,
                        "visible_chats": settled[1]["visible_chats"]}
        raise OperationError("whatsapp_read_failed",
                             "WhatsApp Web did not reach a readable state before the deadline")
    finally:
        if page is not None:
            page.socket.close()
        if target is not None:
            try:
                _http(f"{endpoint}/json/close/{target['id']}")
            except (OSError, urllib.error.URLError, ValueError, KeyError):
                pass
        if started_here:
            _ensure("--stop")
