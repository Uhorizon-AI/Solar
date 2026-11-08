"""Scoped WhatsApp Web read: positive and denied paths against a fake local DevTools endpoint."""
import base64
import hashlib
import json
import shutil
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import browser_read
import operations
from mcp_helpers import execute


class FakeBrowser:
    """A DevTools endpoint whose page answers `Runtime.evaluate` from a scripted list."""

    def __init__(self, reads, navigation=None, tabs=(), redirect_to=None, navigate_error=None,
                 stream=False, drip=False, close_failures=0, late_requests=(), garbage=False):
        self.reads = list(reads)
        self.redirect_to, self.navigate_error = redirect_to, navigate_error
        self.stream, self.drip, self.garbage = stream, drip, garbage
        self.close_failures, self.late_requests = close_failures, list(late_requests)
        self.late_sent = False
        # document requests the "browser" makes after Page.navigate (redirects, frames)
        self.navigation = list(navigation or [browser_read.DESTINATION])
        self.tabs = list(tabs)
        self.navigated, self.closed, self.methods, self.decisions = [], [], [], []
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
                if self.path == "/json/version" and outer.redirect_to:
                    self.send_response(302)
                    self.send_header("Location", outer.redirect_to)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/json/version":
                    return self._json({"Browser": "fake"})
                if self.path == "/json/list":
                    own = [] if "tab-1" in outer.closed else [
                        {"type": "page", "id": "tab-1", "url": browser_read.DESTINATION}]
                    return self._json(outer.tabs + own)
                if self.path.startswith("/json/close/"):
                    if outer.fail_close():
                        return self.send_error(500)
                    outer.closed.append(self.path.rsplit("/", 1)[1])
                    return self._json("Target is closing")
                if self.headers.get("Upgrade") == "websocket":
                    return outer.serve_socket(self)
                self.send_error(404)

            def do_PUT(self):
                if self.headers.get("Content-Length") != "0":
                    return self.send_error(411)   # Chrome refuses a body-less PUT without it
                if self.path.startswith("/json/new"):
                    return self._json({"id": "tab-1", "webSocketDebuggerUrl":
                                       f"ws://127.0.0.1:{outer.port}/devtools/page/tab-1"})
                self.send_error(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def fail_close(self):
        if self.close_failures > 0:
            self.close_failures -= 1
            return True
        return False

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
            if self.garbage and message["method"] == "Page.enable":
                self._send_text(sock, "this is not json")
            if self.drip and message["method"] == "Page.enable":
                try:   # the header of a 200-byte frame, then one byte at a time, never finishing
                    sock.sendall(bytes([0x81, 126]) + struct.pack(">H", 200))
                    while True:
                        sock.sendall(b"x")
                        time.sleep(0.02)
                except OSError:
                    return
            if message["method"] == "Page.close" and not self.fail_close():
                self.closed.append("tab-1")
            if self.stream and message["method"] == "Page.enable":
                try:   # a page that never answers and never stops talking
                    while True:
                        self._send(sock, {"method": "Network.dataReceived", "params": {}})
                        time.sleep(0.01)
                except OSError:
                    return
            if message["method"] == "Page.navigate":
                self.navigated.append(message["params"]["url"])
                if self.navigate_error:
                    result = {"errorText": self.navigate_error}
                for number, url in enumerate(self.navigation):
                    self._send(sock, {"method": "Fetch.requestPaused", "params": {
                        "requestId": f"r{number}", "resourceType": "Document", "request": {"url": url}}})
            if message["method"] in ("Fetch.continueRequest", "Fetch.failRequest"):
                self.decisions.append((message["method"], message["params"]["requestId"]))
            if message["method"] == "Runtime.evaluate":
                value = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
                result = {"result": {"value": value}}
            self._send(sock, {"id": message["id"], "result": result})
            if message["method"] == "Runtime.evaluate" and not self.late_sent:
                self.late_sent = True
                for number, url in enumerate(self.late_requests):   # requests that arrive between reads
                    self._send(sock, {"method": "Fetch.requestPaused", "params": {
                        "requestId": f"late{number}", "resourceType": "Document", "request": {"url": url}}})

    @staticmethod
    def _send_text(sock, text):
        data = text.encode()
        sock.sendall(bytes([0x81, len(data)]) + data)

    @staticmethod
    def _send(sock, body):
        reply = json.dumps(body).encode()
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


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLAR_BROWSER_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(browser_read, "_POLL_SECONDS", 0)


@pytest.fixture
def endpoint(monkeypatch):
    made = []

    def start(reads, **options):
        fake = FakeBrowser(reads, **options)
        made.append(fake)
        monkeypatch.setenv("SOLAR_BROWSER_DEBUG_HOST", "127.0.0.1")
        monkeypatch.setenv("SOLAR_BROWSER_DEBUG_PORT", str(fake.port))
        return fake

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
    assert set(fake.methods) <= {"Page.enable", "Fetch.enable", "Page.navigate", "Runtime.evaluate",
                                 "Fetch.continueRequest", "Fetch.failRequest"}


def test_the_allowed_origin_navigation_continues(endpoint):
    fake = endpoint([page(pane=True, rows=1)])
    read()
    assert fake.decisions == [("Fetch.continueRequest", "r0")]


def test_a_redirect_outside_the_origin_is_refused_before_it_loads(endpoint):
    fake = endpoint([page(origin="null")],
                    navigation=[browser_read.DESTINATION, "https://example.com/phish"])
    assert error_code(read) == "browser_scope_denied"
    assert fake.decisions == [("Fetch.continueRequest", "r0"), ("Fetch.failRequest", "r1")]
    assert fake.closed == ["tab-1"]


def test_a_blocked_frame_does_not_fail_a_page_that_reached_the_origin(endpoint):
    fake = endpoint([page(pane=True, rows=2)],
                    navigation=[browser_read.DESTINATION, "https://tracker.example/frame"])
    assert read()["visible_chats"] == 2
    assert ("Fetch.failRequest", "r1") in fake.decisions


@pytest.mark.parametrize("loading", ["", "null", "about:blank"])
def test_a_page_still_loading_is_not_a_scope_denial(endpoint, loading):
    endpoint([page(origin=loading), page(pane=True, rows=4)])
    assert read()["visible_chats"] == 4


def test_a_partial_list_is_not_returned_before_it_settles(endpoint):
    endpoint([page(pane=True, rows=1), page(pane=True, rows=9)])
    assert read()["visible_chats"] == 9


def test_a_second_read_waits_for_the_first_and_gives_up_at_the_deadline(endpoint):
    endpoint([page(pane=True, rows=1)])
    held = browser_read._acquire(time.monotonic() + 1)
    try:
        assert error_code(lambda: read(deadline=0.3)) == "whatsapp_read_failed"
    finally:
        held.close()
    assert read()["visible_chats"] == 1


def test_the_expression_returns_nothing_from_another_origin(endpoint):
    expression = browser_read.READ_EXPRESSION
    assert "location.origin !== " in expression
    assert expression.index("location.origin !==") < expression.index("querySelector")


def test_unavailable_browser_is_distinct(monkeypatch):
    monkeypatch.setenv("SOLAR_BROWSER_DEBUG_PORT", "9")
    monkeypatch.setattr(browser_read, "_ensure", lambda flag, timeout=0: False)
    assert error_code(read) == "browser_unavailable"


def test_started_browser_is_stopped_but_a_running_one_is_left(endpoint, monkeypatch):
    calls = []
    monkeypatch.setattr(browser_read, "_ensure", lambda flag, timeout=0: calls.append(flag) or True)
    endpoint([page(pane=True, rows=1)])
    read()
    assert calls == []   # already running: neither started nor stopped

    state = {"up": False}
    fake = endpoint([page(pane=True, rows=1)])
    real = browser_read._ready
    monkeypatch.setattr(browser_read, "_ready", lambda url, timeout=0: state["up"] and real(url))
    monkeypatch.setattr(browser_read, "_ensure",
                        lambda flag, timeout=0: calls.append(flag) or state.update(up=flag == "--start") or True)
    read()
    assert calls == ["--start", "--stop"]
    assert fake.closed == ["tab-1"]


def test_a_browser_started_here_is_kept_when_another_tab_is_open(endpoint, monkeypatch):
    calls, state = [], {"up": False}
    endpoint([page(pane=True, rows=1)], tabs=[{"type": "page", "url": "https://example.org/"}])
    real = browser_read._ready
    monkeypatch.setattr(browser_read, "_ready", lambda url, timeout=0: state["up"] and real(url))
    monkeypatch.setattr(browser_read, "_ensure",
                        lambda flag, timeout=0: calls.append(flag) or state.update(up=flag == "--start") or True)
    read()
    assert calls == ["--start"]


@pytest.mark.parametrize("host", ["example.com", "::1", "0.0.0.0"])
def test_non_local_debug_endpoint_is_refused(monkeypatch, host):
    monkeypatch.setenv("SOLAR_BROWSER_DEBUG_HOST", host)
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


@pytest.fixture
def served(tmp_path):
    """Synthetic pages served from http://127.0.0.1, so `location.origin` is a real http origin."""
    from functools import partial
    from http.server import SimpleHTTPRequestHandler
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *_: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), type("Quiet", (SimpleHTTPRequestHandler,), {
        "log_message": lambda *_: None,
        "__init__": lambda self, *a, **k: SimpleHTTPRequestHandler.__init__(self, *a, directory=str(tmp_path), **k)}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def run_expression(expression, dom, tmp_path, origin):
    (tmp_path / "p.html").write_text(
        f"<body>{dom}<script>document.title=JSON.stringify({expression})"
        f";document.body.setAttribute('data-r',document.title)</script></body>")
    out = subprocess.run([CHROME, "--headless", "--no-first-run", f"--user-data-dir={tmp_path/'u'}",
                          "--dump-dom", f"{origin}/p.html"], capture_output=True, text=True, timeout=30).stdout
    raw = out.split("data-r=\"", 1)[1].split("\">", 1)[0].replace("&quot;", '"')
    return json.loads(raw)


@pytest.mark.skipif(not CHROME, reason="Chrome not installed")
@pytest.mark.parametrize("dom,expected", [
    ('<div id="pane-side"><div role="listitem"><span title="A">A</span></div>'
     '<div role="listitem"><span title="">x</span></div><div role="row"><span title="B">B</span></div></div>',
     {"qr": False, "pane": True, "rows": 2}),
    ('<div id="pane-side"></div>', {"qr": False, "pane": True, "rows": 0}),
    ('<div data-testid="qrcode"></div>', {"qr": True, "pane": False, "rows": 0}),
])
def test_read_expression_on_synthetic_pages(dom, expected, tmp_path, served):
    got = run_expression(browser_read.read_expression(served), dom, tmp_path, served)
    assert got["origin"] == served
    assert {k: got[k] for k in expected} == expected


@pytest.mark.skipif(not CHROME, reason="Chrome not installed")
def test_the_expression_reads_no_selector_on_another_origin(tmp_path, served):
    dom = '<div id="pane-side"><div role="listitem"><span title="A">A</span></div></div>'
    got = run_expression(browser_read.READ_EXPRESSION, dom, tmp_path, served)
    assert (got["qr"], got["pane"], got["rows"]) == (False, False, 0)
    assert got["origin"] == served != browser_read.ALLOWED_ORIGIN


def test_a_blocked_frame_before_the_pane_appears_is_not_a_denial(endpoint):
    endpoint([page(), page(), page(pane=True, rows=3)],
             navigation=[browser_read.DESTINATION, "https://tracker.example/frame"])
    assert read()["visible_chats"] == 3


def test_the_tab_is_closed_before_the_socket_is_dropped(endpoint, monkeypatch):
    order = []
    fake = endpoint([page(pane=True, rows=1)])
    real_close = browser_read._Socket.close
    monkeypatch.setattr(browser_read._Socket, "close", lambda self: order.append("socket") or real_close(self))
    real_http = browser_read._http

    def http(url, *args, **kwargs):
        if "/json/close/" in url:
            order.append("tab")
        return real_http(url, *args, **kwargs)

    monkeypatch.setattr(browser_read, "_http", http)
    read()
    assert order.index("tab") < order.index("socket")
    assert fake.closed == ["tab-1"]


def test_a_browser_started_here_is_stopped_after_a_failed_first_close(endpoint, monkeypatch):
    calls, state = [], {"up": False}
    endpoint([page(pane=True, rows=1)], close_failures=1)
    real = browser_read._ready
    monkeypatch.setattr(browser_read, "_ready", lambda url, timeout=0: state["up"] and real(url))
    monkeypatch.setattr(browser_read, "_ensure",
                        lambda flag, timeout=0: calls.append(flag) or state.update(up=flag == "--start") or True)
    read()
    assert calls == ["--start", "--stop"]


def test_a_page_that_streams_events_forever_cannot_hold_the_lock_past_the_deadline(endpoint):
    endpoint([page()], stream=True)
    started = time.monotonic()
    assert error_code(lambda: read(deadline=1.0)) == "whatsapp_read_failed"
    assert time.monotonic() - started < 3.0
    held = browser_read._acquire(time.monotonic() + 0.5)   # the lock is free again
    held.close()


def test_a_redirect_from_the_debugging_endpoint_is_not_followed(monkeypatch):
    hits = []

    class Elsewhere(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_error(404)

        def log_message(self, *_):
            pass

    other = ThreadingHTTPServer(("127.0.0.1", 0), Elsewhere)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    fake = FakeBrowser([page(pane=True, rows=1)], redirect_to=f"http://127.0.0.1:{other.server_address[1]}/x")
    monkeypatch.setenv("SOLAR_BROWSER_DEBUG_PORT", str(fake.port))
    monkeypatch.setattr(browser_read, "_ensure", lambda flag, timeout=0: False)
    try:
        assert error_code(read) == "browser_unavailable"
        assert hits == []
    finally:
        other.shutdown()
        fake.server.shutdown()


def test_a_navigation_error_fails_early_and_distinctly(endpoint):
    endpoint([page()], navigate_error="net::ERR_INTERNET_DISCONNECTED")
    started = time.monotonic()
    assert error_code(lambda: read(deadline=30)) == "whatsapp_read_failed"
    assert time.monotonic() - started < 5


def test_a_tab_without_a_debugging_socket_is_an_unavailable_browser(endpoint, monkeypatch):
    endpoint([page()])
    real = browser_read._http
    monkeypatch.setattr(browser_read, "_http",
                        lambda url, *a, **k: {"id": "tab-1"} if "/json/new" in url else real(url, *a, **k))
    assert error_code(read) == "browser_unavailable"


def test_the_read_lock_directory_is_created_and_a_bad_one_is_a_distinct_error(endpoint, monkeypatch, tmp_path):
    endpoint([page(pane=True, rows=1)])
    monkeypatch.setenv("SOLAR_BROWSER_PROFILE_DIR", str(tmp_path / "missing" / "profile"))
    assert read()["visible_chats"] == 1
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("SOLAR_BROWSER_PROFILE_DIR", str(blocker / "profile"))
    assert error_code(read) == "browser_unavailable"


def test_the_socket_is_kept_until_the_tab_close_is_confirmed(endpoint, monkeypatch):
    order = []
    fake = endpoint([page(pane=True, rows=1)], close_failures=2)
    real_close = browser_read._Socket.close
    monkeypatch.setattr(browser_read._Socket, "close",
                        lambda self: order.append(("socket", list(fake.closed))) or real_close(self))
    read(deadline=6.0)
    assert fake.closed == ["tab-1"]
    assert order == [("socket", ["tab-1"])]       # dropped only after the close was confirmed


def test_a_close_that_never_succeeds_is_an_error_not_a_success(endpoint):
    fake = endpoint([page(pane=True, rows=1)], close_failures=999)
    started = time.monotonic()
    assert error_code(lambda: read(deadline=2.0)) == "browser_unavailable"
    assert time.monotonic() - started < 2.4          # inside the total deadline
    assert fake.closed == []
    held = browser_read._acquire(time.monotonic() + 0.5)   # and the lock is free
    held.close()


def test_an_exhausted_cleanup_budget_frees_the_lock_inside_the_total_deadline(endpoint, monkeypatch):
    calls, state = [], {"up": False}
    endpoint([page(pane=True, rows=1)], close_failures=999)
    real_http, real_ready = browser_read._http, browser_read._ready

    def slow_http(url, *args, **kwargs):
        if "/json/close/" in url:
            time.sleep(0.4)             # each attempt eats the reserve
        return real_http(url, *args, **kwargs)

    monkeypatch.setattr(browser_read, "_http", slow_http)
    monkeypatch.setattr(browser_read, "_ready", lambda url, timeout=0: state["up"] and real_ready(url))
    monkeypatch.setattr(browser_read, "_ensure",
                        lambda flag, timeout=0: calls.append(flag) or state.update(up=flag == "--start") or True)
    started = time.monotonic()
    assert error_code(lambda: read(deadline=2.0)) == "browser_unavailable"
    assert time.monotonic() - started < 2.6
    assert calls == ["--start"]          # no time left to stop it: it is left running, never over the deadline
    held = browser_read._acquire(time.monotonic() + 0.5)
    held.close()


def test_a_page_that_drips_one_frame_forever_cannot_hold_the_read(endpoint):
    endpoint([page()], drip=True)
    started = time.monotonic()
    assert error_code(lambda: read(deadline=1.0)) == "whatsapp_read_failed"
    assert time.monotonic() - started < 3.0
    held = browser_read._acquire(time.monotonic() + 0.5)
    held.close()


def test_an_http_body_that_drips_is_cut_at_the_deadline():
    class Drip(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                for _ in range(1000):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.05)
            except OSError:
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Drip)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        started = time.monotonic()
        with pytest.raises(OSError):
            browser_read._http(f"http://127.0.0.1:{server.server_address[1]}/x", timeout=0.5)
        assert time.monotonic() - started < 2.0
    finally:
        server.shutdown()


def test_requests_that_arrive_between_reads_are_decided_while_waiting(endpoint):
    fake = endpoint([page(pane=True, rows=1)], late_requests=["https://example.com/late"])
    browser_read_status = browser_read.whatsapp_status(deadline=6.0, poll=0.2)
    assert browser_read_status["visible_chats"] == 1
    assert ("Fetch.failRequest", "late0") in fake.decisions


def test_a_malformed_message_from_the_browser_is_a_typed_failure(endpoint):
    endpoint([page()], garbage=True)
    assert error_code(read) == "whatsapp_read_failed"


def test_a_malformed_message_while_waiting_is_a_typed_failure():
    class Page:
        class socket:
            until = 0
            receive = staticmethod(lambda: "not json")
    page_ = browser_read._Page.__new__(browser_read._Page)
    page_.socket = Page.socket
    with pytest.raises(browser_read.OperationError) as caught:
        page_.pump(1.0, time.monotonic() + 1.0)
    assert caught.value.code == "browser_unavailable"
