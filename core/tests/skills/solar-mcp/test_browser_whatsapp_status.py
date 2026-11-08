"""Scoped WhatsApp Web read: positive and denied paths against a fake local DevTools endpoint."""
import base64
import hashlib
import json
import shutil
import socket
import struct
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import browser_read
import operations
from mcp_helpers import execute


class FakeBrowser:
    """A DevTools endpoint whose page answers `Runtime.evaluate` from a scripted list."""

    def __init__(self, reads):
        self.reads = list(reads)
        self.navigated, self.closed, self.methods = [], [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _json(self, body):
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/json/version":
                    return self._json({"Browser": "fake"})
                if self.path.startswith("/json/close/"):
                    outer.closed.append(self.path.rsplit("/", 1)[1])
                    return self._json("Target is closing")
                if self.headers.get("Upgrade") == "websocket":
                    return outer.serve_socket(self)
                self.send_error(404)

            def do_PUT(self):
                if self.path.startswith("/json/new"):
                    return self._json({"id": "tab-1", "webSocketDebuggerUrl":
                                       f"ws://127.0.0.1:{outer.port}/devtools/page/tab-1"})
                self.send_error(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def serve_socket(self, handler):
        key = handler.headers["Sec-WebSocket-Key"]
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        handler.wfile.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                            b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        handler.wfile.flush()
        sock = handler.connection
        while True:
            head = self._exact(sock, 2)
            if not head:
                return
            size = head[1] & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._exact(sock, 2))[0]
            mask = self._exact(sock, 4)
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._exact(sock, size)))
            message = json.loads(data)
            self.methods.append(message["method"])
            result = {}
            if message["method"] == "Page.navigate":
                self.navigated.append(message["params"]["url"])
            if message["method"] == "Runtime.evaluate":
                value = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
                result = {"result": {"value": value}}
            reply = json.dumps({"id": message["id"], "result": result}).encode()
            frame = bytes([0x81]) + (bytes([len(reply)]) if len(reply) < 126
                                     else bytes([126]) + struct.pack(">H", len(reply)))
            sock.sendall(frame + reply)

    @staticmethod
    def _exact(sock, count):
        out = b""
        while len(out) < count:
            chunk = sock.recv(count - len(out))
            if not chunk:
                return b""
            out += chunk
        return out


ORIGIN = "https://web.whatsapp.com"


def page(**fields):
    return {**dict(origin=ORIGIN, qr=False, pane=False, rows=0), **fields}


@pytest.fixture
def endpoint(monkeypatch):
    made = []

    def start(reads):
        fake = FakeBrowser(reads)
        made.append(fake)
        monkeypatch.setenv("SOLAR_BROWSER_DEBUG_HOST", "127.0.0.1")
        monkeypatch.setenv("SOLAR_BROWSER_DEBUG_PORT", str(fake.port))
        return fake

    monkeypatch.setattr(browser_read, "_POLL_SECONDS", 0)
    yield start
    for fake in made:
        fake.server.shutdown()


def read(deadline=3.0, **kw):
    return browser_read.whatsapp_status(deadline=deadline, poll=0, **kw)


def error_code(call):
    with pytest.raises(browser_read.OperationError) as caught:
        call()
    return caught.value.code


def test_authenticated_inbox_returns_status_qr_and_count(endpoint):
    fake = endpoint([page(), page(pane=True, rows=7)])
    assert read() == {"status": "active", "qr_present": False, "visible_chats": 7}
    assert fake.navigated == [browser_read.DESTINATION]
    assert fake.closed == ["tab-1"]


def test_authenticated_empty_inbox_is_a_result_not_a_failure(endpoint):
    endpoint([page(pane=True, rows=0)])
    assert read() == {"status": "active", "qr_present": False, "visible_chats": 0}


def test_qr_means_expired_session(endpoint):
    fake = endpoint([page(qr=True)])
    assert error_code(read) == "whatsapp_session_expired"
    assert fake.closed == ["tab-1"]


def test_page_that_never_loads_is_a_read_failure(endpoint):
    endpoint([page()])
    assert error_code(lambda: read(deadline=0.2)) == "whatsapp_read_failed"


def test_other_origin_is_denied_and_nothing_is_returned(endpoint):
    fake = endpoint([dict(origin="https://example.com", qr=False, pane=True, rows=3)])
    assert error_code(read) == "browser_scope_denied"
    assert fake.closed == ["tab-1"]


def test_only_navigate_and_the_fixed_expression_reach_the_page(endpoint):
    fake = endpoint([page(pane=True, rows=1)])
    read()
    assert set(fake.methods) <= {"Page.enable", "Page.navigate", "Runtime.evaluate"}


def test_unavailable_browser_is_distinct(monkeypatch):
    monkeypatch.setenv("SOLAR_BROWSER_DEBUG_PORT", "9")
    monkeypatch.setattr(browser_read, "_ensure", lambda flag: False)
    assert error_code(read) == "browser_unavailable"


def test_started_browser_is_stopped_but_a_running_one_is_left(endpoint, monkeypatch):
    calls = []
    monkeypatch.setattr(browser_read, "_ensure", lambda flag: calls.append(flag) or True)
    endpoint([page(pane=True, rows=1)])
    read()
    assert calls == []   # already running: neither started nor stopped

    state = {"up": False}
    fake = endpoint([page(pane=True, rows=1)])
    real = browser_read._ready
    monkeypatch.setattr(browser_read, "_ready", lambda url: state["up"] and real(url))
    monkeypatch.setattr(browser_read, "_ensure",
                        lambda flag: calls.append(flag) or state.update(up=flag == "--start") or True)
    read()
    assert calls == ["--start", "--stop"]
    assert fake.closed == ["tab-1"]


def test_non_local_debug_endpoint_is_refused(monkeypatch):
    monkeypatch.setenv("SOLAR_BROWSER_DEBUG_HOST", "example.com")
    assert error_code(read) == "browser_unavailable"


def test_operation_accepts_no_caller_control(solar_env, monkeypatch):
    monkeypatch.setitem(operations.HANDLERS, "browser.whatsapp_status",
                        lambda _a: pytest.fail("ran with invalid input"))
    for key in ("url", "chat", "script", "selector", "profile", "origin", "message"):
        body, error = execute("browser.whatsapp_status", {key: "x"}, approved=False)
        assert error and body["code"] == "invalid_arguments", body


def test_operation_maps_result_and_failure(solar_env, monkeypatch):
    monkeypatch.setattr(browser_read, "whatsapp_status",
                        lambda: {"status": "active", "qr_present": False, "visible_chats": 2})
    body, error = execute("browser.whatsapp_status", {}, approved=False)
    assert not error and body["result"]["visible_chats"] == 2

    def expired():
        raise browser_read.OperationError("whatsapp_session_expired", "QR shown")
    monkeypatch.setattr(browser_read, "whatsapp_status", expired)
    body, error = execute("browser.whatsapp_status", {}, approved=False)
    assert error and body["code"] == "whatsapp_session_expired"


CHROME = next((p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           shutil.which("google-chrome") or "") if p and Path(p).is_file()), None)


@pytest.mark.skipif(not CHROME, reason="Chrome not installed")
@pytest.mark.parametrize("dom,expected", [
    ('<div id="pane-side"><div role="listitem"><span title="A">A</span></div>'
     '<div role="listitem"><span title="">x</span></div><div role="row"><span title="B">B</span></div></div>',
     {"qr": False, "pane": True, "rows": 2}),
    ('<div id="pane-side"></div>', {"qr": False, "pane": True, "rows": 0}),
    ('<div data-testid="qrcode"></div>', {"qr": True, "pane": False, "rows": 0}),
])
def test_read_expression_on_synthetic_pages(dom, expected, tmp_path):
    html = tmp_path / "p.html"
    html.write_text(f"<body>{dom}<script>document.title=JSON.stringify({browser_read.READ_EXPRESSION})"
                    f";document.body.setAttribute('data-r',document.title)</script></body>")
    out = subprocess.run([CHROME, "--headless", "--no-first-run", f"--user-data-dir={tmp_path/'u'}",
                          "--dump-dom", html.as_uri()], capture_output=True, text=True, timeout=30).stdout
    raw = out.split("data-r=\"", 1)[1].split("\">", 1)[0].replace("&quot;", '"')
    got = json.loads(raw)
    assert {k: got[k] for k in expected} == expected
