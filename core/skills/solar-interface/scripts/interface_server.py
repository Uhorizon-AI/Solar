#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from interface_http import HttpAdapter, InterfaceHttpDispatcher  # noqa: E402
from interface_store import InterfaceStore, now_iso  # noqa: E402

_STORE: InterfaceStore | None = None
_DISPATCHER: InterfaceHttpDispatcher | None = None


def _store() -> InterfaceStore:
    if _STORE is None:
        raise RuntimeError("InterfaceStore not initialized")
    return _STORE


def _dispatcher() -> InterfaceHttpDispatcher:
    if _DISPATCHER is None:
        raise RuntimeError("InterfaceHttpDispatcher not initialized")
    return _DISPATCHER


class Handler(BaseHTTPRequestHandler):
    server_version = "SolarInterface/0.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _adapter(self) -> HttpAdapter:
        return HttpAdapter(self, service_name="interface")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        store = _store()
        env = store.env

        if path == "/":
            host_port = env.get("SOLAR_HOST_PORT", "9000")
            host_url = f"http://127.0.0.1:{host_port}"
            self._adapter().send_html(
                f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="3;url={host_url}">
  <title>Solar Interface</title>
</head>
<body>
  <main>
    <h1>Solar Interface</h1>
    <p><strong>Primary human UX:</strong> <a href="{host_url}">Solar Host</a> (redirecting in 3s).</p>
    <p>Legacy daemon API on :7741 — optional; Host :9000 serves API in-process (MVP-b).</p>
  </main>
</body>
</html>"""
            )
            return

        if path == "/health":
            self._adapter().send_json({"status": "ok", "service": "solar-interface", "ts": now_iso()})
            return

        if _dispatcher().dispatch_get(self._adapter(), self.path):
            return

        self._adapter().send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        if _dispatcher().dispatch_post(self._adapter(), self.path):
            return
        self._adapter().send_json({"error": "Not found"}, 404)

    def do_DELETE(self) -> None:
        if _dispatcher().dispatch_delete(self._adapter(), self.path):
            return
        self._adapter().send_json({"error": "Not found"}, 404)


def main() -> None:
    global _STORE, _DISPATCHER  # noqa: PLW0603

    parser = argparse.ArgumentParser()
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--workspace", default=None, help="Workspace path (default: SOLAR_WORKSPACE)")
    args = parser.parse_args()

    ws = args.workspace or os.environ.get("SOLAR_WORKSPACE", "")
    if not ws:
        print("ERROR: SOLAR_WORKSPACE not set", file=sys.stderr)
        sys.exit(1)

    _STORE = InterfaceStore(ws)
    _STORE.ensure_runtime()
    _DISPATCHER = InterfaceHttpDispatcher(_STORE)

    if args.setup_only:
        return

    env = _STORE.env
    host = env.get("SOLAR_INTERFACE_HOST", "127.0.0.1")
    port = int(env.get("SOLAR_INTERFACE_PORT", "7741"))

    _STORE.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        if _STORE.pid_file.exists():
            _STORE.pid_file.unlink()


if __name__ == "__main__":
    main()
