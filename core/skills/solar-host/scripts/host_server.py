#!/usr/bin/env python3
"""Solar Host MVP — single localhost control plane (default :9000)."""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = os.environ.get("SOLAR_HOST_HOST", "127.0.0.1")
PORT = int(os.environ.get("SOLAR_HOST_PORT", "9000"))
WORKSPACE = Path(os.environ["SOLAR_WORKSPACE"]).resolve()
INTERFACE_BASE = os.environ.get(
    "SOLAR_INTERFACE_BASE_URL", "http://127.0.0.1:7741"
).rstrip("/")
SOLAR_BIN = os.environ.get(
    "SOLAR_CLI",
    str(WORKSPACE / "core/skills/solar-interface/scripts/solar"),
)
_APPROVAL_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _valid_approval_id(approval_id: str) -> bool:
    return bool(approval_id and _APPROVAL_ID_RE.fullmatch(approval_id))


def fetch_json(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {"error": exc.reason}
        except json.JSONDecodeError:
            payload = {"error": raw or exc.reason}
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def run_solar_status() -> str:
    try:
        proc = subprocess.run(
            ["bash", SOLAR_BIN, "status"],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.stdout or proc.stderr or "(no output)"
    except Exception as exc:  # noqa: BLE001
        return f"status error: {exc}"


def _approval_row(a: dict) -> str:
    aid = str(a.get("approval_id", ""))
    run_id = str(a.get("run_id", ""))
    if not _valid_approval_id(aid):
        return ""
    summary = str(a.get("summary") or a.get("reason") or run_id)
    return (
        '<div class="approval-item" style="margin:12px 0">'
        f"<strong>{_esc(summary)}</strong><br/>"
        f'<span class="muted">approval {_esc(aid)} · run {_esc(run_id)}</span><br/>'
        f'<button type="button" class="approval-act" data-id="{_esc(aid)}" data-action="approve">Approve</button> '
        f'<button type="button" class="approval-act" data-id="{_esc(aid)}" data-action="reject">Reject</button>'
        "</div>"
    )


def dashboard_html() -> str:
    iface_code, _iface_health = fetch_json(f"{INTERFACE_BASE}/health")
    _, approvals_payload = fetch_json(f"{INTERFACE_BASE}/approvals")
    approvals = approvals_payload.get("approvals", []) if isinstance(approvals_payload, dict) else []
    pending = [a for a in approvals if a.get("status") == "pending"]
    status_text = run_solar_status()
    ws = str(WORKSPACE)
    cursor_href = "cursor://file/" + urllib.parse.quote(ws, safe="/")
    iface_label = "OK" if iface_code == 200 else "DOWN"
    iface_class = "ok" if iface_code == 200 else "warn"
    pending_html = "".join(_approval_row(a) for a in pending[:20])
    if not pending_html:
        pending_html = "<p class='muted'>No pending approvals.</p>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Solar Host</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #0f1419; color: #e7ecf3; }}
    h1 {{ margin: 0 0 8px; }}
    .muted {{ color: #9aa7b5; }}
    section {{ margin: 20px 0; padding: 16px; border: 1px solid #2a3542; border-radius: 10px; }}
    pre {{ white-space: pre-wrap; background: #1a222c; padding: 12px; border-radius: 8px; }}
    button {{ margin-right: 8px; padding: 6px 12px; cursor: pointer; }}
    .ok {{ color: #6dd58c; }}
    .warn {{ color: #e8b84a; }}
  </style>
</head>
<body>
  <h1>Solar Host</h1>
  <p class="muted">Control plane for workspace <code>{_esc(ws)}</code> — port {PORT}. IDE handles code; Host handles operations.</p>
  <section>
    <h2>Runtime</h2>
    <p>Interface daemon: <span class="{iface_class}">{iface_label}</span> ({_esc(INTERFACE_BASE)})</p>
    <pre>{_esc(status_text)}</pre>
  </section>
  <section>
    <h2>Approvals inbox ({len(pending)} pending)</h2>
    {pending_html}
  </section>
  <section>
    <h2>Quick actions</h2>
    <p><a href="{_esc(cursor_href)}">Open workspace in Cursor</a></p>
    <p class="muted">Voice: <code>solar voice once</code> (planned; see solar-host-plan). Chat REPL on :7741 is deprecated as primary UX — use this Host UI or your IDE.</p>
  </section>
  <script>
    document.querySelectorAll(".approval-act").forEach((btn) => {{
      btn.addEventListener("click", async () => {{
        const id = btn.dataset.id;
        const action = btn.dataset.action;
        if (!id || !action) return;
        const r = await fetch(`/api/approvals/${{encodeURIComponent(id)}}/${{action}}`, {{ method: "POST" }});
        if (r.ok) location.reload();
        else alert(await r.text());
      }});
    }});
  </script>
</body>
</html>"""


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

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/dashboard"):
            self._send(dashboard_html().encode("utf-8"))
            return
        if path == "/health":
            self._send_json({"status": "ok", "service": "solar-host", "port": PORT})
            return
        if path == "/api/status":
            self._send_json({"text": run_solar_status(), "workspace": str(WORKSPACE)})
            return
        if path == "/api/approvals":
            code, payload = fetch_json(f"{INTERFACE_BASE}/approvals")
            self._send_json(payload, code or HTTPStatus.BAD_GATEWAY)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "approvals" and parts[3] in ("approve", "reject"):
            aid = parts[2]
            action = parts[3]
            if not _valid_approval_id(aid):
                self._send_json({"error": "invalid approval id"}, HTTPStatus.BAD_REQUEST)
                return
            code, payload = fetch_json(f"{INTERFACE_BASE}/approvals/{aid}/{action}", "POST", {})
            self._send_json(payload, code or HTTPStatus.BAD_GATEWAY)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def main() -> int:
    if "SOLAR_WORKSPACE" not in os.environ:
        print("ERROR: SOLAR_WORKSPACE required", file=sys.stderr)
        return 1
    server = ThreadingHTTPServer((HOST, PORT), HostHandler)
    print(f"Solar Host listening on http://{HOST}:{PORT} (workspace={WORKSPACE})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
