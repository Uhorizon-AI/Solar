"""One scoped browser read of a page the owner registered.

Solar knows nothing about any site. The owner registers a read in
`<runtime>/mcp/browser-reads.json`: the one origin it may touch, the page to open, a script
file (a function expression) pinned by its SHA-256, and the fields it may return. The caller
of the operation only names the read; it supplies no URL, script, selector or argument.

The scope is enforced twice, and the second line does not depend on the first:

1. Navigation. The Chrome `Fetch` domain pauses every document request of the tab;
   anything outside the registered origin (including redirects and frames) is refused
   before it loads.
2. The read. The wrapper checks `location.origin` before it runs the script, so a page
   on any other origin returns nothing but its origin.

The script's answer is never passed through as it is: only the declared fields, with their
declared types, leave this module. A script that changed since it was registered is refused.

The browser is the shared Solar runtime (`solar-browser`): started and stopped
through `ensure_browser.sh`, never launched here. Only a tab this module opens is
touched, and it is closed (before the debugging socket is dropped) afterwards. Reads are
serialized with a file lock under one absolute deadline that reserves time for cleanup; a
browser this read started is stopped only when no other tab is left in it.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import http.client
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit

from mcp_context import OperationError

_LOCAL_HOSTS = ("127.0.0.1", "localhost")
_LOADING_ORIGINS = ("", "null", "about:blank")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}")
_MAX_SCRIPT = 32 * 1024
_MAX_FIELDS = 16

# The wrapper. The script is the owner's pinned function expression; it only runs once the
# page is on the registered origin. `__SCRIPT__` is substituted last so its text is never rescanned.
_WRAPPER = r"""(() => {
  const origin = location.origin;
  if (origin !== __ORIGIN__) { return {origin: origin, data: null}; }
  const read = (__SCRIPT__);
  return {origin: origin, data: read()};
})()"""


def read_expression(origin: str, script: str) -> str:
    return _WRAPPER.replace("__ORIGIN__", json.dumps(origin)).replace("__SCRIPT__", script)


_SCRIPTS = Path(__file__).resolve().parents[2] / "solar-browser" / "scripts"
_POLL_SECONDS = 1.0
_READ_DEADLINE = 60.0     # the whole operation, cleanup included
_STABLE_POLLS = 3
_CALL_TIMEOUT = 20.0
_CLEANUP_SECONDS = 8.0   # reserved inside the deadline to close the tab, stop the browser, free the lock


# --- minimal CDP over a stdlib websocket (no dependency) ------------------------------

_MAX_FRAME = 16 * 1024 * 1024


class _Socket:
    """A websocket whose every read is bounded by the absolute time in `self.until`.

    The deadline is recomputed before each `recv`, so a peer that drips single bytes cannot
    stretch a call past it. A frame is consumed only once it is complete: a timeout in the
    middle of one leaves the buffer intact for the next read.
    """

    def __init__(self, url: str, timeout: float):
        parts = urlsplit(url)
        if parts.hostname not in _LOCAL_HOSTS:
            raise OperationError("browser_unavailable", "The debugging endpoint is not local")
        self.until = time.monotonic() + timeout
        try:
            raw = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout)
        except OSError:
            raise OperationError("browser_unavailable", "The debugging socket did not open") from None
        self.sock = raw
        self.buffer = b""
        self.partial = b""
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        try:
            raw.sendall((f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                         f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                         f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            while b"\r\n\r\n" not in self.buffer:
                self._fill()
        except OSError:
            raw.close()
            raise OperationError("browser_unavailable", "The debugging socket did not answer") from None
        except OperationError:
            raw.close()
            raise
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raw.close()
            raise OperationError("browser_unavailable", "The debugging socket was refused")

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
        left = self.until - time.monotonic()
        if left <= 0:
            raise socket.timeout("deadline")
        self.sock.settimeout(left)       # a peer that stops reading cannot hold a write past the deadline
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _fill(self) -> None:
        left = self.until - time.monotonic()
        if left <= 0:
            raise socket.timeout("deadline")
        self.sock.settimeout(left)
        chunk = self.sock.recv(65536)
        if not chunk:
            raise OperationError("browser_unavailable", "The debugging socket closed")
        self.buffer += chunk

    def _frame(self):
        """One complete frame out of the buffer, or None if it has not fully arrived."""
        buf = self.buffer
        if len(buf) < 2:
            return None
        first, size, offset = buf[0], buf[1] & 0x7F, 2
        if size == 126:
            if len(buf) < 4:
                return None
            size, offset = struct.unpack(">H", buf[2:4])[0], 4
        elif size == 127:
            if len(buf) < 10:
                return None
            size, offset = struct.unpack(">Q", buf[2:10])[0], 10
        if size > _MAX_FRAME:
            raise OperationError("browser_unavailable", "The debugging socket sent an oversized frame")
        if len(buf) < offset + size:
            return None
        self.buffer = buf[offset + size:]
        return first, buf[offset:offset + size]

    def receive(self) -> str:
        """The next text message, or `socket.timeout` when `self.until` passes first."""
        while True:
            frame = self._frame()
            if frame is None:
                self._fill()
                continue
            first, payload = frame
            opcode = first & 0x0F
            if opcode == 8:
                raise OperationError("browser_unavailable", "The debugging socket closed")
            if opcode in (9, 10):
                continue
            self.partial += payload
            if first & 0x80:
                message, self.partial = self.partial, b""
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

    def _write(self, text: str) -> None:
        try:
            self.socket.send(text)
        except socket.timeout:
            raise OperationError("browser_read_failed", "The page did not accept the command in time") from None
        except OSError:
            raise OperationError("browser_unavailable", "The debugging socket was lost") from None

    def _notify(self, method: str, params: dict) -> None:
        self.counter += 1
        self._write(json.dumps({"id": self.counter, "method": method, "params": params}))

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

        Every read is bounded by it (see `_Socket`), so a page that keeps sending events, or
        drips a frame byte by byte, cannot hold the call and the read lock past the deadline.
        """
        self.counter += 1
        mine = self.counter
        self.socket.until = time.monotonic() + _CALL_TIMEOUT if until is None else until
        self._write(json.dumps({"id": mine, "method": method, "params": params or {}}))
        while True:
            try:
                reply = json.loads(self.socket.receive())
            except socket.timeout:
                raise OperationError("browser_read_failed", "The page did not answer in time") from None
            except OSError:
                raise OperationError("browser_unavailable", "The debugging socket was lost") from None
            except ValueError:
                raise OperationError("browser_read_failed", "The browser sent a malformed message") from None
            if "id" not in reply:
                self._event(reply)
                continue
            if reply.get("id") == mine:
                if "error" in reply:
                    raise OperationError("browser_read_failed", "The browser refused the read")
                return reply.get("result", {})

    def pump(self, seconds: float, until: float) -> None:
        """Wait `seconds` (never past `until`) while still deciding every paused request.

        A plain sleep would leave requests paused and undecided between two reads.
        """
        end = min(time.monotonic() + seconds, until)
        self.socket.until = end
        while time.monotonic() < end:
            try:
                reply = json.loads(self.socket.receive())
            except socket.timeout:
                return
            except OSError:
                raise OperationError("browser_unavailable", "The debugging socket was lost") from None
            except ValueError:
                raise OperationError("browser_unavailable", "The browser sent a malformed message") from None
            if "id" not in reply:
                self._event(reply)


# --- lifecycle ------------------------------------------------------------------------

def _endpoint() -> str:
    host = os.environ.get("SOLAR_BROWSER_DEBUG_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_BROWSER_DEBUG_PORT", "9222")
    if host not in _LOCAL_HOSTS or not port.isdigit():
        raise OperationError("browser_unavailable", "The debugging endpoint must be local")
    return f"http://{host}:{port}"


_MAX_BODY = 1024 * 1024


def _http(url: str, method: str = "GET", timeout: float = 5.0):
    """One loopback request that cannot outlive `timeout`, however slowly the peer answers.

    `http.client` never follows a redirect (a 3xx is an error here), and a watchdog shuts the
    socket at the deadline, so a peer that drips headers or a body byte by byte is cut too.
    """
    parts = urlsplit(url)
    window = max(min(timeout, 5.0), 0.05)
    until = time.monotonic() + window
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=window)
    expired = threading.Event()
    guard = None
    try:
        conn.connect()
        connected = conn.sock

        def cut():
            expired.set()
            try:
                connected.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        guard = threading.Timer(max(until - time.monotonic(), 0.01), cut)   # what is left after connect
        guard.daemon = True
        guard.start()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        conn.request(method, path, headers={"Content-Length": "0"} if method == "PUT" else {})
        answer = conn.getresponse()
        if answer.status >= 300:
            raise OSError(f"HTTP {answer.status}")
        body = answer.read(_MAX_BODY + 1)
        if expired.is_set() or len(body) > _MAX_BODY:
            raise OSError("the debugging endpoint did not answer in time")
        text = body.decode()
    except (http.client.HTTPException, UnicodeDecodeError) as exc:
        raise OSError(str(exc)) from None
    finally:
        if guard is not None:
            guard.cancel()
        conn.close()
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
                              timeout=max(timeout, 0.1))
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
                raise OperationError("browser_read_failed",
                                     "Another browser read kept the browser until the deadline") from None
            time.sleep(0.1)


def _other_tabs(endpoint: str, own: str | None, end: float) -> bool:
    """Whether a tab other than ours or a blank one is open (someone else may be using the browser).

    Bounded by `end`; with no time left the answer is "yes", so the browser is left running.
    """
    timeout = min(2.0, end - time.monotonic())
    if timeout <= 0.05:
        return True
    try:
        tabs = _http(f"{endpoint}/json/list", timeout=timeout)
    except (OSError, urllib.error.URLError, ValueError):
        return True    # unknown: leave the browser running
    return any(t.get("type") == "page" and t.get("id") != own
               and t.get("url") not in ("about:blank", "chrome://newtab/")
               for t in (tabs if isinstance(tabs, list) else []))


def _tab_gone(endpoint: str, tab_id, timeout: float) -> bool:
    try:
        tabs = _http(f"{endpoint}/json/list", timeout=timeout)
    except (OSError, urllib.error.URLError, ValueError):
        return False    # unknown is not confirmed
    return isinstance(tabs, list) and all(t.get("id") != tab_id for t in tabs)


def _close_tab(endpoint: str, target: dict, page, end: float) -> bool:
    """Close our tab and confirm it is gone, retrying until `end`. Returns whether it was confirmed.

    Paused requests keep being decided between attempts. If `/json/close` keeps failing the
    page is asked to close itself over the socket, which is still up.
    """
    tab_id = target.get("id") if isinstance(target, dict) else None
    attempt = 0
    while time.monotonic() < end:
        attempt += 1
        left = end - time.monotonic()
        try:
            _http(f"{endpoint}/json/close/{tab_id}", timeout=min(2.0, left))
        except (OSError, urllib.error.URLError, ValueError):
            pass
        if page is not None:
            try:
                page.pump(0.05, end)
                if attempt > 1:
                    page.call("Page.close", until=min(end, time.monotonic() + 1.0))
            except OperationError:
                pass
        if _tab_gone(endpoint, tab_id, min(2.0, max(end - time.monotonic(), 0.05))):
            return True
        time.sleep(min(0.1, max(end - time.monotonic(), 0)))
    return False


def _quiesce(page, end: float) -> None:
    """Last resort when the tab could not be confirmed closed: cancel what it is loading.

    Dropping the socket ends the request interception, and Chrome may release what was paused.
    Stopping the load and moving the tab to a blank page first cancels in-flight navigations,
    and a last pump decides whatever was still arriving. It narrows the window; it cannot
    close it (see "Where the guarantee ends" in SKILL.md).
    """
    try:
        page.call("Page.stopLoading", until=min(end, time.monotonic() + 0.5))
        page.call("Page.navigate", {"url": "about:blank"}, until=min(end, time.monotonic() + 0.5))
        page.pump(0.1, end)
    except OperationError:
        pass


# --- the read -------------------------------------------------------------------------

def _invalid(message: str) -> OperationError:
    return OperationError("browser_read_invalid", message)


def prepare(name: str, registry: dict, root: Path) -> dict:
    """The registered read `name`, checked, with its script text loaded and its digest verified."""
    entry = registry.get(name) if isinstance(registry, dict) else None
    if not isinstance(entry, dict):
        raise OperationError("browser_read_not_registered",
                             f"{name} is not in the owner's browser-reads registry")
    origin, url, script_path = entry.get("origin"), entry.get("url"), entry.get("script")
    if not (isinstance(origin, str) and isinstance(url, str) and isinstance(script_path, str)):
        raise _invalid("origin, url and script must be strings")
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.hostname or origin != f"https://{parts.netloc}":
        raise _invalid("origin must be a bare https origin")
    if urlsplit(url).scheme != "https" or f"https://{urlsplit(url).netloc}" != origin:
        raise _invalid("url must be an https page on the registered origin")
    fields = entry.get("fields")
    if not isinstance(fields, dict) or not fields or len(fields) > _MAX_FIELDS:
        raise _invalid("fields must declare between 1 and 16 fields")
    for key, spec in fields.items():
        if not _NAME.fullmatch(str(key)) or not isinstance(spec, dict) \
                or spec.get("type") not in ("integer", "boolean", "string"):
            raise _invalid("each field needs a name and a type of integer, boolean or string")
    pin = entry.get("sha256")
    if not (isinstance(pin, str) and re.fullmatch(r"[0-9a-f]{64}", pin)):
        raise _invalid("sha256 must be the 64-hex digest of the script file")
    base = root.resolve()
    path = (base / script_path).resolve()
    if base not in path.parents or not path.is_file():
        raise _invalid("the script must be a file inside the workspace")
    raw = path.read_bytes()
    if len(raw) > _MAX_SCRIPT:
        raise _invalid("the script is too large")
    if hashlib.sha256(raw).hexdigest() != pin:
        raise OperationError("browser_read_changed",
                             f"The script of {name} changed since the owner registered it; nothing ran")
    return dict(name=name, origin=origin, url=url, script=raw.decode("utf-8"), fields=fields)


def _shape(data: dict, fields: dict) -> dict:
    """Only the declared fields, with their declared types, leave this module."""
    out = {}
    for key, spec in fields.items():
        value = data.get(key)
        kind = spec["type"]
        good = ((kind == "boolean" and isinstance(value, bool))
                or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool)
                    and 0 <= value <= 10**9)
                or (kind == "string" and isinstance(value, str) and 0 < len(value) <= 80
                    and value.isprintable()))
        if good and "enum" in spec:
            good = value in spec["enum"]
        if not good:
            raise OperationError("browser_read_failed",
                                 f"The page did not return the declared field {key}")
        out[key] = value
    return out


def _denied() -> OperationError:
    return OperationError("browser_scope_denied",
                          "A navigation outside the registered origin was refused; nothing was read")


def scoped_read(entry: dict, deadline: float = _READ_DEADLINE, poll: float = _POLL_SECONDS) -> dict:
    """Run one prepared read, or fail with a distinct refusal.

    `deadline` is absolute for the whole call and includes the cleanup; `poll` exists for tests.
    The operation passes nothing.
    """
    origin, expression = entry["origin"], read_expression(entry["origin"], entry["script"])
    begun = time.monotonic()
    limit = begun + deadline - min(_CLEANUP_SECONDS, deadline * 0.25)    # the work; the rest is cleanup
    remaining = lambda: limit - time.monotonic()  # noqa: E731
    endpoint = _endpoint()
    lock = _acquire(limit)
    started_here = False
    target = None
    page = None
    completed = False    # set only when a result is about to be returned
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
        page = _Page(_Socket(url, min(10.0, max(remaining(), 0.5))), origin)
        page.call("Page.enable", until=limit)
        page.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "resourceType": "Document",
                                                 "requestStage": "Request"}]}, until=limit)
        navigated = page.call("Page.navigate", {"url": entry["url"]}, until=limit)
        if navigated.get("errorText"):
            if page.denied:
                raise _denied()
            raise OperationError("browser_read_failed", "The page could not be loaded")
        last, stable, reached = None, 0, False
        while remaining() > 0:
            page.pump(min(poll, max(remaining(), 0)), limit)   # still deciding paused requests
            answer = page.call("Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "awaitPromise": False},
                until=limit)
            value = (answer.get("result") or {}).get("value")
            if not isinstance(value, dict):
                continue
            seen = value.get("origin")
            reached = reached or seen == origin
            if seen in _LOADING_ORIGINS:
                if page.denied and not reached:
                    raise _denied()
                last, stable = None, 0
                continue
            if seen != origin:
                raise OperationError("browser_scope_denied",
                                     "The page left the registered origin; nothing was read")
            data = value.get("data")
            if not isinstance(data, dict) or data.get("ready") is not True:
                last, stable = None, 0     # still loading
                continue
            refused = data.get("refused")
            if refused is not None:
                if not (isinstance(refused, str) and _NAME.fullmatch(refused)):
                    raise OperationError("browser_read_failed", "The page returned an invalid refusal")
                settled = ("refused", refused)
            else:
                settled = ("ok", _shape(data, entry["fields"]))
            # An empty list can still be loading: the same answer must hold several polls in a row.
            if settled == last:
                stable += 1
            else:
                last, stable = settled, 1
            if stable >= _STABLE_POLLS:
                if settled[0] == "refused":
                    raise OperationError("browser_read_refused", f"{entry['name']}: {settled[1]}")
                completed = True
                return {"read": entry["name"], "data": settled[1]}
        if page.denied and not reached:
            raise _denied()
        raise OperationError("browser_read_failed",
                             "The page did not reach a readable state before the deadline")
    finally:
        # Cleanup, in this order. The tab is closed and the close CONFIRMED while the socket (and
        # with it the request interception) is still up; only then is the socket dropped, so no
        # paused request can be released into a tab that is still alive. Then the browser, if this
        # read started it and no other tab is left, and last the lock.
        end = begun + deadline
        closed = True
        if target is not None:
            # keep a little of the cleanup time for _quiesce, in case the close is not confirmed
            closed = _close_tab(endpoint, target, page, end - min(0.7, max(end - time.monotonic(), 0) * 0.3))
        if page is not None:
            if not closed:
                _quiesce(page, end)
            page.socket.close()
        own = target.get("id") if isinstance(target, dict) else None
        if started_here and end - time.monotonic() > 0.5 and not _other_tabs(endpoint, own, end):
            _ensure("--stop", end - time.monotonic())
        lock.close()
        if completed and not closed:
            # Success is never reported with the tab possibly still open: whatever it had paused
            # is released when the socket drops, so the caller must know the read did not end clean.
            raise OperationError("browser_unavailable",
                                 "The read tab could not be confirmed closed; nothing is returned")
