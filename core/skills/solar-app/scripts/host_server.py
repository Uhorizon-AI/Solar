#!/usr/bin/env python3
"""Solar Host — read-only local console on :9000."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import host_client_actions as client_actions  # noqa: E402
import host_identity  # noqa: E402
import host_registry as reg  # noqa: E402
import host_workspace_context as ctx  # noqa: E402

# 9000 in production; tests may move it (see host_identity.resolve_port).
PORT = host_identity.resolve_port()


LOGGER = logging.getLogger("solar.app")


def configure_logging(logger: logging.Logger | None = None) -> None:
    """Send the console's warnings to stderr, where the host already reports errors.

    Adds a stderr handler only when neither this logger nor the root logger has one;
    a configured root is trusted and propagation is left alone. The level is set to
    WARNING only when none was chosen. If the root is configured after the console
    started, a warning prints twice: accepted and pinned by a test, so do not add
    `propagate = False`. Calling it again does nothing.
    """
    logger = logger or LOGGER
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.WARNING)
    if logger.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    handler._solar_host = True  # type: ignore[attr-defined]  # marks the handler added here; tests count it
    logger.addHandler(handler)


def _active_workspace() -> Path:
    path = reg.get_active_path()
    if not path:
        path = os.environ.get("SOLAR_WORKSPACE", "")
    return Path(path).resolve()


class HostHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, body: bytes, code: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, code: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self._send(raw, code, "application/json; charset=utf-8")

    def _work_guard(self) -> bool:
        if not client_actions.is_loopback_client(self) or not client_actions.validate_client_request(self, PORT):
            self._send_json({"error": "forbidden Host/Origin"}, 403)
            return False
        return True

    def do_GET(self) -> None:
        if not self._work_guard():
            return
        path = self.path.split("?", 1)[0]
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            import app_http
            app_http.get(self, path, qs, _active_workspace())
        except (OSError, ValueError, TypeError) as exc:
            # Generic handler: "Console data unavailable" is the body of every console route
            # except task-detail, which answers its own "Task detail unavailable" and logs
            # "task-detail failed". Both lines carry the exception class, never its message.
            LOGGER.warning("console route %r failed: %s", path, type(exc).__name__)
            self._send_json({"error": "Console data unavailable", "refused": True}, 503)

    def do_POST(self) -> None:
        self._send_json({"error": "Read-only console"}, 405)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST


def loopback_host(host: str) -> bool:
    """True for localhost and the loopback ranges. 0.0.0.0 is not loopback."""
    name = (host or "").strip().strip("[]")
    if name.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def main() -> int:
    host = os.environ.get("SOLAR_APP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if not loopback_host(host):
        print(
            f"ERROR: SOLAR_APP_HOST={host} is not a loopback address. "
            "The console stays on this machine.",
            file=sys.stderr,
        )
        return 1
    active = reg.get_active_path()
    if not active:
        seed = os.environ.get("SOLAR_WORKSPACE", "").strip()
        if seed:
            seed_path = Path(seed).expanduser()
            if seed_path.is_dir():
                norm = str(seed_path.resolve())
                try:
                    reg.add_workspace(norm)
                    reg.set_active(norm)
                    active = reg.get_active_path()
                except ValueError:
                    pass
    if not active:
        print(
            "ERROR: no active workspace in registry; "
            "run: solar app workspace add <path>",
            file=sys.stderr,
        )
        return 1
    try:
        ctx.mount(active)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    ws = _active_workspace()
    configure_logging()
    host_identity.freeze_runtime()

    server = ThreadingHTTPServer((host, PORT), HostHandler)
    print(f"Solar Host listening on http://{host}:{PORT} (workspace={ws})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
