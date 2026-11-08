"""Scoped browser read: registered origin, pinned script, declared fields, against a fake DevTools endpoint."""
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
        self.navigation = list(navigation or [ENTRY["url"]])
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
                        {"type": "page", "id": "tab-1", "url": ENTRY["url"]}]
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
                for number, url in enumerate([] if message["params"]["url"] == "about:blank" else self.navigation):
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


ORIGIN = "https://app.example.test"
FIELDS = {"status": {"type": "string", "enum": ["active"]}, "visible_chats": {"type": "integer"}}
ENTRY = dict(name="sample", origin=ORIGIN, url=ORIGIN + "/", script="() => ({})", fields=FIELDS)


def page(origin=ORIGIN, data=None):
    """What the wrapper evaluates to: the page's origin and what the script returned there."""
    return {"origin": origin, "data": data}


def loading():
    return page(data={"ready": False})


def ready(chats):
    return page(data={"ready": True, "status": "active", "visible_chats": chats})


def refused(code="session_expired"):
    return page(data={"ready": True, "refused": code})


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
    return browser_read.scoped_read(ENTRY, deadline=deadline, poll=0, **kw)


def error_code(call):
    with pytest.raises(browser_read.OperationError) as caught:
        call()
    return caught.value.code


def test_authenticated_inbox_returns_status_qr_and_count(endpoint):
    fake = endpoint([loading(), ready(7)])
    assert read() == {"read": "sample", "data": {"status": "active", "visible_chats": 7}}
    assert fake.navigated == [ENTRY["url"]]
    assert fake.closed == ["tab-1"]


def test_authenticated_empty_inbox_is_a_result_not_a_failure(endpoint):
    endpoint([ready(0)])
    assert read() == {"read": "sample", "data": {"status": "active", "visible_chats": 0}}


def test_a_refusal_the_script_reports_is_a_distinct_failure(endpoint):
    fake = endpoint([refused()])
    with pytest.raises(browser_read.OperationError) as caught:
        read()
    assert caught.value.code == "browser_read_refused"
    assert "sample: session_expired" in str(caught.value)
    assert fake.closed == ["tab-1"]


@pytest.mark.parametrize("code", ["has space", "x" * 200, "", None, 7])
def test_a_refusal_must_be_a_plain_name(endpoint, code):
    endpoint([page(data={"ready": True, "refused": code})])
    assert error_code(read) in ("browser_read_failed",)


def test_only_declared_fields_leave_the_module(endpoint):
    endpoint([page(data={"ready": True, "status": "active", "visible_chats": 3,
                         "message": "hello from a chat", "token": "secret"})])
    assert read()["data"] == {"status": "active", "visible_chats": 3}


@pytest.mark.parametrize("data", [
    {"ready": True, "status": "active", "visible_chats": "3"},      # wrong type
    {"ready": True, "status": "active", "visible_chats": True},     # a bool is not an integer
    {"ready": True, "status": "open", "visible_chats": 3},          # outside the enum
    {"ready": True, "status": "active"},                            # a declared field is missing
])
def test_a_field_that_does_not_match_its_declaration_fails(endpoint, data):
    endpoint([page(data=data)])
    assert error_code(read) == "browser_read_failed"


def test_page_that_never_loads_is_a_read_failure(endpoint):
    endpoint([loading()])
    assert error_code(lambda: read(deadline=0.2)) == "browser_read_failed"


def test_other_origin_is_denied_and_nothing_is_returned(endpoint):
    fake = endpoint([page(origin="https://example.com", data={"ready": True, "status": "active", "visible_chats": 3})])
    assert error_code(read) == "browser_scope_denied"
    assert fake.closed == ["tab-1"]


def test_only_navigate_and_the_fixed_expression_reach_the_page(endpoint):
    fake = endpoint([ready(1)])
    read()
    assert set(fake.methods) <= {"Page.enable", "Fetch.enable", "Page.navigate", "Runtime.evaluate",
                                 "Fetch.continueRequest", "Fetch.failRequest"}


def test_the_allowed_origin_navigation_continues(endpoint):
    fake = endpoint([ready(1)])
    read()
    assert fake.decisions == [("Fetch.continueRequest", "r0")]


def test_a_redirect_outside_the_origin_is_refused_before_it_loads(endpoint):
    fake = endpoint([page(origin="null")],
                    navigation=[ENTRY["url"], "https://example.com/phish"])
    assert error_code(read) == "browser_scope_denied"
    assert fake.decisions == [("Fetch.continueRequest", "r0"), ("Fetch.failRequest", "r1")]
    assert fake.closed == ["tab-1"]


def test_a_blocked_frame_does_not_fail_a_page_that_reached_the_origin(endpoint):
    fake = endpoint([ready(2)],
                    navigation=[ENTRY["url"], "https://tracker.example/frame"])
    assert read()["data"]["visible_chats"] == 2
    assert ("Fetch.failRequest", "r1") in fake.decisions


@pytest.mark.parametrize("loading", ["", "null", "about:blank"])
def test_a_page_still_loading_is_not_a_scope_denial(endpoint, loading):
    endpoint([page(origin=loading), ready(4)])
    assert read()["data"]["visible_chats"] == 4


def test_a_partial_list_is_not_returned_before_it_settles(endpoint):
    endpoint([ready(1), ready(9)])
    assert read()["data"]["visible_chats"] == 9


def test_a_second_read_waits_for_the_first_and_gives_up_at_the_deadline(endpoint):
    endpoint([ready(1)])
    held = browser_read._acquire(time.monotonic() + 1)
    try:
        assert error_code(lambda: read(deadline=0.3)) == "browser_read_failed"
    finally:
        held.close()
    assert read()["data"]["visible_chats"] == 1


def test_the_wrapper_checks_the_origin_before_the_script_runs():
    expression = browser_read.read_expression(ORIGIN, "() => ({marker: 1})")
    assert "location.origin" in expression and '"https://app.example.test"' in expression
    assert expression.index("origin !==") < expression.index("marker")
    # the script is substituted last: its own text is never rescanned for placeholders
    tricky = browser_read.read_expression(ORIGIN, "() => '__ORIGIN__'")
    assert tricky.count("'__ORIGIN__'") == 1


def test_unavailable_browser_is_distinct(monkeypatch):
    monkeypatch.setenv("SOLAR_BROWSER_DEBUG_PORT", "9")
    monkeypatch.setattr(browser_read, "_ensure", lambda flag, timeout=0: False)
    assert error_code(read) == "browser_unavailable"


def test_started_browser_is_stopped_but_a_running_one_is_left(endpoint, monkeypatch):
    calls = []
    monkeypatch.setattr(browser_read, "_ensure", lambda flag, timeout=0: calls.append(flag) or True)
    endpoint([ready(1)])
    read()
    assert calls == []   # already running: neither started nor stopped

    state = {"up": False}
    fake = endpoint([ready(1)])
    real = browser_read._ready
    monkeypatch.setattr(browser_read, "_ready", lambda url, timeout=0: state["up"] and real(url))
    monkeypatch.setattr(browser_read, "_ensure",
                        lambda flag, timeout=0: calls.append(flag) or state.update(up=flag == "--start") or True)
    read()
    assert calls == ["--start", "--stop"]
    assert fake.closed == ["tab-1"]


def test_a_browser_started_here_is_kept_when_another_tab_is_open(endpoint, monkeypatch):
    calls, state = [], {"up": False}
    endpoint([ready(1)], tabs=[{"type": "page", "url": "https://example.org/"}])
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


def register(solar_env, **override):
    """Write a script file in the workspace and register it, as the owner would."""
    import hashlib
    script = solar_env.workspace / "planets" / "demo" / "skills" / "demo" / "read.js"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("() => ({ready: true, status: 'active', visible_chats: 1})", encoding="utf-8")
    entry = dict(origin=ORIGIN, url=ORIGIN + "/", script=str(script.relative_to(solar_env.workspace)),
                 sha256=hashlib.sha256(script.read_bytes()).hexdigest(), fields=FIELDS)
    entry.update(override)
    folder = solar_env.runtime / "mcp"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "browser-reads.json").write_text(json.dumps({"sample": entry}), encoding="utf-8")
    return script


def test_operation_accepts_only_the_name_of_a_read(solar_env, monkeypatch):
    monkeypatch.setitem(operations.HANDLERS, "browser.read",
                        lambda _a: pytest.fail("ran with invalid input"))
    for arguments in ({}, {"read": "sample", "url": "x"}, {"read": "sample", "script": "x"},
                      {"read": "sample", "origin": "x"}, {"read": "sample", "selector": "x"},
                      {"read": "not a name"}, {"read": 5}):
        body, error = execute("browser.read", arguments, approved=False)
        assert error and body["code"] == "invalid_arguments", (arguments, body)


def test_a_read_nobody_registered_is_refused(solar_env):
    body, error = execute("browser.read", {"read": "sample"}, approved=False)
    assert error and body["code"] == "browser_read_not_registered"


def test_a_registered_read_runs_its_pinned_script_and_maps_the_result(solar_env, monkeypatch):
    register(solar_env)
    seen = {}

    def fake_read(entry, **_):
        seen.update(entry)
        return {"read": entry["name"], "data": {"status": "active", "visible_chats": 1}}

    monkeypatch.setattr(browser_read, "scoped_read", fake_read)
    body, error = execute("browser.read", {"read": "sample"}, approved=False)
    assert not error, body
    assert body["result"] == {"read": "sample", "data": {"status": "active", "visible_chats": 1}}
    assert seen["origin"] == ORIGIN and "visible_chats: 1" in seen["script"]

    def refuse(entry, **_):
        raise browser_read.OperationError("browser_read_refused", "sample: session_expired")
    monkeypatch.setattr(browser_read, "scoped_read", refuse)
    body, error = execute("browser.read", {"read": "sample"}, approved=False)
    assert error and body["code"] == "browser_read_refused"


def test_a_script_that_changed_after_registration_is_refused_and_never_runs(solar_env, monkeypatch):
    script = register(solar_env)
    monkeypatch.setattr(browser_read, "scoped_read", lambda *_a, **_k: pytest.fail("ran a changed script"))
    script.write_text("() => ({ready: true, token: document.cookie})", encoding="utf-8")
    body, error = execute("browser.read", {"read": "sample"}, approved=False)
    assert error and body["code"] == "browser_read_changed"


@pytest.mark.parametrize("override", [
    dict(origin="http://app.example.test"),                     # not https
    dict(origin="https://app.example.test/path"),               # not a bare origin
    dict(url="https://elsewhere.example/"),                     # page on another origin
    dict(url="http://app.example.test/"),                       # page not https
    dict(fields={}),                                            # nothing declared
    dict(fields={"x": {"type": "object"}}),                     # type not allowed
    dict(sha256="not-a-digest"),
    dict(script="../outside.js"),                               # escapes the workspace
])
def test_a_malformed_registration_is_refused(solar_env, monkeypatch, override):
    register(solar_env, **override)
    (solar_env.workspace.parent / "outside.js").write_text("() => ({})", encoding="utf-8")
    monkeypatch.setattr(browser_read, "scoped_read", lambda *_a, **_k: pytest.fail("ran"))
    body, error = execute("browser.read", {"read": "sample"}, approved=False)
    assert error and body["code"] == "browser_read_invalid", body


def test_a_symlinked_script_that_leaves_the_workspace_is_refused(solar_env, monkeypatch):
    import hashlib
    outside = solar_env.tmp_path / "elsewhere.js"
    outside.write_text("() => ({})", encoding="utf-8")
    link = solar_env.workspace / "planets" / "demo" / "link.js"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    register(solar_env, script="planets/demo/link.js", sha256=hashlib.sha256(outside.read_bytes()).hexdigest())
    monkeypatch.setattr(browser_read, "scoped_read", lambda *_a, **_k: pytest.fail("ran"))
    body, error = execute("browser.read", {"read": "sample"}, approved=False)
    assert error and body["code"] == "browser_read_invalid"


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


SAMPLE_SCRIPT = """() => {
  const items = Array.from(document.querySelectorAll('#list [role="listitem"]'))
    .filter(item => item.querySelector('span[title]:not([title=""])'));
  return {ready: !!document.querySelector('#list'), visible_chats: items.length};
}"""


@pytest.mark.skipif(not CHROME, reason="Chrome not installed")
@pytest.mark.parametrize("dom,expected", [
    ('<div id="list"><div role="listitem"><span title="A">A</span></div>'
     '<div role="listitem"><span title="">x</span></div><div role="listitem"><span title="B">B</span></div></div>',
     {"ready": True, "visible_chats": 2}),
    ('<div id="list"></div>', {"ready": True, "visible_chats": 0}),
    ('<div id="other"></div>', {"ready": False, "visible_chats": 0}),
])
def test_the_wrapper_runs_the_script_on_the_registered_origin(dom, expected, tmp_path, served):
    got = run_expression(browser_read.read_expression(served, SAMPLE_SCRIPT), dom, tmp_path, served)
    assert got["origin"] == served and got["data"] == expected


@pytest.mark.skipif(not CHROME, reason="Chrome not installed")
def test_the_wrapper_never_runs_the_script_on_another_origin(tmp_path, served):
    dom = '<div id="list"><div role="listitem"><span title="A">A</span></div></div>'
    got = run_expression(browser_read.read_expression(ORIGIN, SAMPLE_SCRIPT), dom, tmp_path, served)
    assert got == {"origin": served, "data": None}


def test_a_blocked_frame_before_the_page_is_ready_is_not_a_denial(endpoint):
    endpoint([loading(), loading(), ready(3)],
             navigation=[ENTRY["url"], "https://tracker.example/frame"])
    assert read()["data"]["visible_chats"] == 3


def test_the_tab_is_closed_before_the_socket_is_dropped(endpoint, monkeypatch):
    order = []
    fake = endpoint([ready(1)])
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
    endpoint([ready(1)], close_failures=1)
    real = browser_read._ready
    monkeypatch.setattr(browser_read, "_ready", lambda url, timeout=0: state["up"] and real(url))
    monkeypatch.setattr(browser_read, "_ensure",
                        lambda flag, timeout=0: calls.append(flag) or state.update(up=flag == "--start") or True)
    read()
    assert calls == ["--start", "--stop"]


def test_a_page_that_streams_events_forever_cannot_hold_the_lock_past_the_deadline(endpoint):
    endpoint([loading()], stream=True)
    started = time.monotonic()
    assert error_code(lambda: read(deadline=1.0)) == "browser_read_failed"
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
    fake = FakeBrowser([ready(1)], redirect_to=f"http://127.0.0.1:{other.server_address[1]}/x")
    monkeypatch.setenv("SOLAR_BROWSER_DEBUG_PORT", str(fake.port))
    monkeypatch.setattr(browser_read, "_ensure", lambda flag, timeout=0: False)
    try:
        assert error_code(read) == "browser_unavailable"
        assert hits == []
    finally:
        other.shutdown()
        fake.server.shutdown()


def test_a_navigation_error_fails_early_and_distinctly(endpoint):
    endpoint([loading()], navigate_error="net::ERR_INTERNET_DISCONNECTED")
    started = time.monotonic()
    assert error_code(lambda: read(deadline=30)) == "browser_read_failed"
    assert time.monotonic() - started < 5


def test_a_tab_without_a_debugging_socket_is_an_unavailable_browser(endpoint, monkeypatch):
    endpoint([loading()])
    real = browser_read._http
    monkeypatch.setattr(browser_read, "_http",
                        lambda url, *a, **k: {"id": "tab-1"} if "/json/new" in url else real(url, *a, **k))
    assert error_code(read) == "browser_unavailable"


def test_the_read_lock_directory_is_created_and_a_bad_one_is_a_distinct_error(endpoint, monkeypatch, tmp_path):
    endpoint([ready(1)])
    monkeypatch.setenv("SOLAR_BROWSER_PROFILE_DIR", str(tmp_path / "missing" / "profile"))
    assert read()["data"]["visible_chats"] == 1
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("SOLAR_BROWSER_PROFILE_DIR", str(blocker / "profile"))
    assert error_code(read) == "browser_unavailable"


def test_the_socket_is_kept_until_the_tab_close_is_confirmed(endpoint, monkeypatch):
    order = []
    fake = endpoint([ready(1)], close_failures=2)
    real_close = browser_read._Socket.close
    monkeypatch.setattr(browser_read._Socket, "close",
                        lambda self: order.append(("socket", list(fake.closed))) or real_close(self))
    read(deadline=6.0)
    assert fake.closed == ["tab-1"]
    assert order == [("socket", ["tab-1"])]       # dropped only after the close was confirmed


def test_a_close_that_never_succeeds_is_an_error_not_a_success(endpoint):
    fake = endpoint([ready(1)], close_failures=999)
    started = time.monotonic()
    assert error_code(lambda: read(deadline=2.0)) == "browser_unavailable"
    assert time.monotonic() - started < 2.4          # inside the total deadline
    assert fake.closed == []
    held = browser_read._acquire(time.monotonic() + 0.5)   # and the lock is free
    held.close()


def test_an_exhausted_cleanup_budget_frees_the_lock_inside_the_total_deadline(endpoint, monkeypatch):
    calls, state = [], {"up": False}
    endpoint([ready(1)], close_failures=999)
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
    endpoint([loading()], drip=True)
    started = time.monotonic()
    assert error_code(lambda: read(deadline=1.0)) == "browser_read_failed"
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
    fake = endpoint([ready(1)], late_requests=["https://example.com/late"])
    browser_read_status = browser_read.scoped_read(ENTRY, deadline=6.0, poll=0.2)
    assert browser_read_status["data"]["visible_chats"] == 1
    assert ("Fetch.failRequest", "late0") in fake.decisions


def test_a_malformed_message_from_the_browser_is_a_typed_failure(endpoint):
    endpoint([loading()], garbage=True)
    assert error_code(read) == "browser_read_failed"


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


def test_an_unconfirmed_close_stops_the_load_and_blanks_the_tab_before_the_socket_drops(endpoint):
    fake = endpoint([ready(1)], close_failures=999)
    assert error_code(lambda: read(deadline=3.0)) == "browser_unavailable"
    assert "Page.stopLoading" in fake.methods
    assert fake.navigated[-1] == "about:blank"
    assert fake.methods.index("Page.stopLoading") > fake.methods.index("Runtime.evaluate")


def test_a_confirmed_close_does_not_blank_the_tab(endpoint):
    fake = endpoint([ready(1)])
    read()
    assert "Page.stopLoading" not in fake.methods


def test_the_close_failure_is_reported_even_when_called_from_inside_an_except(endpoint):
    endpoint([ready(1)], close_failures=999)

    def from_a_handler():
        try:
            raise ValueError("an outer error already being handled")
        except ValueError:
            return read(deadline=2.0)

    assert error_code(from_a_handler) == "browser_unavailable"


def test_a_write_to_a_peer_that_stops_reading_is_cut_at_the_deadline():
    left, right = socket.socketpair()
    left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    right.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    try:
        ws = browser_read._Socket.__new__(browser_read._Socket)
        ws.sock, ws.until = left, time.monotonic() + 0.3
        started = time.monotonic()
        with pytest.raises(socket.timeout):
            ws.send("x" * 5_000_000)
        assert time.monotonic() - started < 2.0
    finally:
        left.close()
        right.close()
