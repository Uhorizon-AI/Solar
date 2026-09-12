#!/usr/bin/env python3
"""Solar Host — read-only local console on :9000."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import host_client_actions as client_actions  # noqa: E402
import host_registry as reg  # noqa: E402
import host_workspace_context as ctx  # noqa: E402

HOST = os.environ.get("SOLAR_APP_HOST", "127.0.0.1")
PORT = 9000
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
            self._send_json({"error": str(exc)}, 503)

    def do_POST(self) -> None:
        self._send_json({"error": "Read-only console"}, 405)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST


def main() -> int:
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

    server = ThreadingHTTPServer((HOST, PORT), HostHandler)
    print(f"Solar Host listening on http://{HOST}:{PORT} (workspace={ws})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
