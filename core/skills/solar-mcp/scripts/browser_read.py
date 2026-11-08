"""One scoped browser read: WhatsApp Web session status and visible chat count.

The caller supplies nothing. The destination, the script and the fields it returns
are constants in this file, so the authorization of an operation that runs this is
exactly its name: it cannot open a chat, visit another origin, read a message or
account data, run a script of the caller's or send anything.

The scope is enforced twice, and the second line does not depend on the first:

1. Navigation. The Chrome `Fetch` domain pauses every document request of the tab;
   anything outside `ALLOWED_ORIGIN` (including redirects and frames) is refused
   before it loads.
2. The read. The expression checks `location.origin` before it touches a selector, so
   a page on any other origin returns nothing but its origin.

The browser is the shared Solar runtime (`solar-browser`): started and stopped
through `ensure_browser.sh`, never launched here. Only a tab this module opens is
touched, and it is closed (before the debugging socket is dropped) afterwards. Reads are
serialized with a file lock under one absolute deadline that reserves time for cleanup; a
browser this read started is stopped only when no other tab is left in it.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import socket
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
_LOCAL_HOSTS = ("127.0.0.1", "localhost")
_LOADING_ORIGINS = ("", "null", "about:blank")

# The whole read. It returns scalars; it opens nothing, types nothing, and never returns
# text from a chat (titles are only counted). A page on another origin gets no selector.
_EXPRESSION = r"""(() => {
  if (location.origin !== __ORIGIN__) {
    return {origin: location.origin, qr: false, pane: false, rows: 0};
  }
  const qr = !!document.querySelector(
    '[data-testid="qrcode"], canvas[aria-label*="QR"], [data-ref] canvas');
  const pane = document.querySelector('#pane-side');
  const rows = pane
    ? Array.from(pane.querySelectorAll('[role="row"], [role="listitem"]'))
        .filter(item => item.querySelector('span[title]:not([title=""])')).length
    : 0;
  return {origin: location.origin, qr: qr, pane: !!pane, rows: rows};
})()"""


def read_expression(origin: str = ALLOWED_ORIGIN) -> str:
    return _EXPRESSION.replace("__ORIGIN__", json.dumps(origin))


READ_EXPRESSION = read_expression()

_SCRIPTS = Path(__file__).resolve().parents[2] / "solar-browser" / "scripts"
_POLL_SECONDS = 1.0
_READ_DEADLINE = 60.0     # the whole operation, cleanup included
_STABLE_POLLS = 3
_CALL_TIMEOUT = 20.0
_CLEANUP_SECONDS = 8.0   # reserved inside the deadline to close the tab, stop the browser, free the lock


# --- minimal CDP over a stdlib websocket (no dependency) ------------------------------

class _Socket:
    def __init__(self, url: str, timeout: float):
        parts = urlsplit(url)
        if parts.hostname not in _LOCAL_HOSTS:
            raise OperationError("browser_unavailable", "The debugging endpoint is not local")
        try:
            raw = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout)
        except OSError:
            raise OperationError("browser_unavailable", "The debugging socket did not open") from None
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        raw.sendall((f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                     f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                     f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            try:
                chunk = raw.recv(1024)
            except OSError:
                raw.close()
                raise OperationError("browser_unavailable", "The debugging socket did not answer") from None
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


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else url


class _Page:
    def __init__(self, socket_: _Socket, allowed_origin: str):
        self.socket = socket_
        self.allowed_origin = allowed_origin
        self.counter = 0
        self.denied = False     # a document request outside the allowed origin was refused

    def _notify(self, method: str, params: dict) -> None:
        self.counter += 1
        self.socket.send(json.dumps({"id": self.counter, "method": method, "params": params}))

    def _event(self, message: dict) -> None:
        """Every document request is paused: only the allowed origin continues."""
        if message.get("method") != "Fetch.requestPaused":
            return
        params = message.get("params") or {}
        request_id = params.get("requestId")
        if not request_id:
            return
        url = (params.get("request") or {}).get("url", "")
        if _origin_of(url) == self.allowed_origin:
            self._notify("Fetch.continueRequest", {"requestId": request_id})
        else:
            self.denied = True
            self._notify("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})

    def call(self, method: str, params: dict | None = None, until: float | None = None) -> dict:
        """One command, answered before the absolute monotonic time `until`.

        The limit is checked on every frame, so a page that keeps sending events and never
        answers cannot hold the call (and the read lock) past the deadline.
        """
        self.counter += 1
        mine = self.counter
        until = time.monotonic() + _CALL_TIMEOUT if until is None else until
        self.socket.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
        while True:
            left = until - time.monotonic()
            if left <= 0:
                raise OperationError("whatsapp_read_failed", "The page did not answer in time")
            self.socket.sock.settimeout(left)
            try:
                reply = json.loads(self.socket.receive())
            except socket.timeout:
                raise OperationError("whatsapp_read_failed", "The page did not answer in time") from None
            except OSError:
                raise OperationError("browser_unavailable", "The debugging socket was lost") from None
            if "id" not in reply:
                self._event(reply)
                continue
            if reply.get("id") == mine:
                if "error" in reply:
                    raise OperationError("whatsapp_read_failed", "The browser refused the read")
                return reply.get("result", {})


# --- lifecycle ------------------------------------------------------------------------

def _endpoint() -> str:
    host = os.environ.get("SOLAR_BROWSER_DEBUG_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_BROWSER_DEBUG_PORT", "9222")
    if host not in _LOCAL_HOSTS or not port.isdigit():
        raise OperationError("browser_unavailable", "The debugging endpoint must be local")
    return f"http://{host}:{port}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The debugging endpoint is validated as local once; a redirect could leave it."""

    def redirect_request(self, *_args, **_kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _http(url: str, method: str = "GET", timeout: float = 5.0):
    request = urllib.request.Request(url, method=method)
    if method == "PUT":
        request.add_header("Content-Length", "0")   # Chrome refuses a body-less PUT without it
    with _OPENER.open(request, timeout=max(min(timeout, 5.0), 0.2)) as answer:  # loopback only
        text = answer.read().decode()
    try:
        return json.loads(text)
    except ValueError:
        return text


def _ready(endpoint: str, timeout: float = 5.0) -> bool:
    try:
        _http(f"{endpoint}/json/version", timeout=timeout)
        return True
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _ensure(flag: str, timeout: float = 60.0) -> bool:
    script = _SCRIPTS / "ensure_browser.sh"
    try:
        done = subprocess.run(["bash", str(script), flag], capture_output=True, text=True,
                              timeout=max(timeout, 1.0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def _lock_path() -> Path:
    profile = os.environ.get("SOLAR_BROWSER_PROFILE_DIR", "/tmp/com.solar.browser-profile")
    return Path(f"{profile}.read.lock")


def _acquire(limit: float):
    """One read at a time: a second caller waits for the first, within the same deadline."""
    path = _lock_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = open(path, "a")
    except OSError:
        raise OperationError("browser_unavailable", "The read lock could not be created") from None
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            if time.monotonic() >= limit:
                handle.close()
                raise OperationError("whatsapp_read_failed",
                                     "Another WhatsApp Web read kept the browser until the deadline") from None
            time.sleep(0.1)


def _other_tabs(endpoint: str, own: str | None, timeout: float = 2.0) -> bool:
    """Whether a tab other than ours or a blank one is open (someone else may be using the browser)."""
    try:
        tabs = _http(f"{endpoint}/json/list", timeout=timeout)
    except (OSError, urllib.error.URLError, ValueError):
        return True    # unknown: leave the browser running
    return any(t.get("type") == "page" and t.get("id") != own
               and t.get("url") not in ("about:blank", "chrome://newtab/")
               for t in (tabs if isinstance(tabs, list) else []))


# --- the read -------------------------------------------------------------------------

def _classify(read: dict, allowed_origin: str = ALLOWED_ORIGIN):
    """A settled answer, or None while the page has not committed to the allowed origin yet."""
    origin = read.get("origin")
    if origin in _LOADING_ORIGINS:
        return None
    if origin != allowed_origin:
        raise OperationError("browser_scope_denied",
                             "The page left the authorized WhatsApp Web origin; nothing was read")
    if read.get("qr"):
        return "qr_required", {}
    if read.get("pane"):
        return "active", {"visible_chats": int(read.get("rows", 0))}
    return None


def _denied() -> OperationError:
    return OperationError("browser_scope_denied",
                          "A navigation outside the authorized origin was refused; nothing was read")


def whatsapp_status(deadline: float = _READ_DEADLINE, poll: float = _POLL_SECONDS) -> dict:
    """Session status, QR presence and visible chat count of WhatsApp Web, or a distinct refusal.

    `deadline` is absolute for the whole call and includes the cleanup; `poll` exists for tests.
    The operation passes nothing.
    """
    begun = time.monotonic()
    limit = begun + deadline - min(_CLEANUP_SECONDS, deadline * 0.25)    # the work; the rest is cleanup
    remaining = lambda: limit - time.monotonic()  # noqa: E731
    endpoint = _endpoint()
    lock = _acquire(limit)
    started_here = False
    target = None
    page = None
    try:
        if not _ready(endpoint, max(remaining(), 0.2)):
            if not _ensure("--start", remaining()) or not _ready(endpoint, max(remaining(), 0.2)):
                raise OperationError("browser_unavailable", "The Solar browser could not be started")
            started_here = True
        try:
            target = _http(f"{endpoint}/json/new?about:blank", method="PUT", timeout=max(remaining(), 0.2))
            url = target["webSocketDebuggerUrl"]
        except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError):
            raise OperationError("browser_unavailable", "The browser did not open a tab") from None
        page = _Page(_Socket(url, min(10.0, max(remaining(), 0.5))), ALLOWED_ORIGIN)
        page.call("Page.enable", until=limit)
        page.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "resourceType": "Document",
                                                 "requestStage": "Request"}]}, until=limit)
        navigated = page.call("Page.navigate", {"url": DESTINATION}, until=limit)
        if navigated.get("errorText"):
            if page.denied:
                raise _denied()
            raise OperationError("whatsapp_read_failed", "WhatsApp Web could not be loaded")
        last, stable, reached = None, 0, False
        while remaining() > 0:
            time.sleep(min(poll, max(remaining(), 0)))
            answer = page.call("Runtime.evaluate", {
                "expression": READ_EXPRESSION, "returnByValue": True, "awaitPromise": False},
                until=limit)
            value = (answer.get("result") or {}).get("value")
            if not isinstance(value, dict):
                continue
            origin = value.get("origin")
            reached = reached or origin == ALLOWED_ORIGIN
            settled = _classify(value)
            if settled is None:
                # A blocked document only matters while the page has not reached WhatsApp Web itself.
                if page.denied and not reached:
                    raise _denied()
                last, stable = None, 0
                continue
            # An empty list can still be loading: the same answer must hold several polls in a row.
            if settled == last:
                stable += 1
            else:
                last, stable = settled, 1
            if stable >= _STABLE_POLLS:
                if settled[0] == "qr_required":
                    raise OperationError("whatsapp_session_expired",
                                         "WhatsApp Web asks to link the device again (QR shown)")
                return {"status": "active", "qr_present": False,
                        "visible_chats": settled[1]["visible_chats"]}
        if page.denied and not reached:
            raise _denied()
        raise OperationError("whatsapp_read_failed",
                             "WhatsApp Web did not reach a readable state before the deadline")
    finally:
        # Cleanup, in this order: the tab first (so no paused request is released into a tab that
        # is still alive), then the socket, then the browser if this read started it and no other
        # tab is left, then the lock.
        cleanup = max(begun + deadline - time.monotonic(), 1.0)
        if target is not None:
            try:
                _http(f"{endpoint}/json/close/{target['id']}", timeout=min(2.0, cleanup))
            except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError):
                pass
        if page is not None:
            page.socket.close()
        if started_here and not _other_tabs(endpoint, (target or {}).get("id") if isinstance(target, dict) else None):
            _ensure("--stop", max(begun + deadline - time.monotonic(), 1.0))
        lock.close()
