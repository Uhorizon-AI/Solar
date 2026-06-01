#!/usr/bin/env python3
"""Solar Host — local control plane (default :9000), multi-workspace fleet."""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_INTERFACE_SCRIPTS = _SCRIPT_DIR.parent.parent / "solar-interface" / "scripts"
if str(_INTERFACE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_INTERFACE_SCRIPTS))

import host_client_actions as client_actions  # noqa: E402
import host_events  # noqa: E402
import host_health_monitor as health_monitor  # noqa: E402
import host_interface as hi  # noqa: E402
import host_registry as reg  # noqa: E402
import host_workspace_context as ctx  # noqa: E402
from interface_http import HttpAdapter, InterfaceHttpDispatcher, is_interface_path  # noqa: E402

HOST = os.environ.get("SOLAR_HOST_HOST", "127.0.0.1")
PORT = int(os.environ.get("SOLAR_HOST_PORT", "9000"))
_APPROVAL_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_CORE_DIR = _SCRIPT_DIR.parent.parent.parent


def _skill_script(skill: str, script: str) -> Path:
    root = os.environ.get("SOLAR_ROOT", "").strip()
    if root:
        candidate = Path(root) / "core" / "skills" / skill / "scripts" / script
        if candidate.is_file():
            return candidate
    return _CORE_DIR / "skills" / skill / "scripts" / script


def _active_workspace() -> Path:
    mounted = ctx.get_mounted()
    if mounted:
        return Path(mounted).resolve()
    path = reg.get_active_path()
    if not path:
        path = os.environ.get("SOLAR_WORKSPACE", "")
    return Path(path).resolve()


def _active_store():
    return hi.get_store(str(_active_workspace()))


def _interface_dispatcher() -> InterfaceHttpDispatcher:
    store = _active_store()
    return InterfaceHttpDispatcher(store, on_event=host_events.emit)


def _http_adapter(handler: BaseHTTPRequestHandler) -> HttpAdapter:
    return HttpAdapter(handler, service_name="host", host_port=PORT)


def _dispatch_interface_get(handler: BaseHTTPRequestHandler, path: str, *, route_path: str | None = None) -> bool:
    if not is_interface_path(path):
        return False
    raw = route_path if route_path is not None else handler.path
    return _interface_dispatcher().dispatch_get(_http_adapter(handler), raw)


def _dispatch_interface_post(handler: BaseHTTPRequestHandler, path: str) -> bool:
    if not is_interface_path(path):
        return False
    return _interface_dispatcher().dispatch_post(_http_adapter(handler), handler.path)


def _dispatch_interface_delete(handler: BaseHTTPRequestHandler, path: str) -> bool:
    if not is_interface_path(path):
        return False
    return _interface_dispatcher().dispatch_delete(_http_adapter(handler), handler.path)


def _solar_bin(ws: Path | None = None) -> str:
    return reg.solar_cli_for(str(ws or _active_workspace()))


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _valid_approval_id(approval_id: str) -> bool:
    return bool(approval_id and _APPROVAL_ID_RE.fullmatch(approval_id))


INBOX_FILTER_TYPES = (
    ("approval.pending", "Pending approvals"),
    ("approval.resolved", "Resolved"),
    ("run.failed", "Failed runs"),
    ("run.completed", "Completed runs"),
    ("workspace.activated", "Workspace switch"),
    ("health.degraded", "Health degraded"),
    ("gateway.error", "Gateway errors"),
    ("client.action.failed", "Client action failed"),
)


def _parse_event_types(qs: dict) -> set[str] | None:
    raw = (qs.get("types") or [""])[0].strip()
    if not raw:
        return None
    return {t.strip() for t in raw.split(",") if t.strip()}


def _inbox_event_li(e: dict) -> str:
    etype = str(e.get("type", ""))
    payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
    summary = str(payload.get("summary") or payload.get("label") or payload.get("run_id") or "")
    aid = str(payload.get("approval_id", ""))
    li_id = f' id="inbox-approval-{aid}"' if aid and _valid_approval_id(aid) else ""
    actions = ""
    if etype == "approval.pending" and _valid_approval_id(aid):
        actions = (
            f'<span class="inbox-actions">'
            f'<button type="button" class="inbox-act" data-id="{_esc(aid)}" data-action="approve">Approve</button> '
            f'<button type="button" class="inbox-act" data-id="{_esc(aid)}" data-action="reject">Reject</button>'
            f"</span>"
        )
    focus_cls = " inbox-focus" if aid else ""
    return (
        f"<li class='inbox-item{focus_cls}' data-type='{_esc(etype)}'{li_id}>"
        f"<strong>{_esc(etype)}</strong> "
        f"<span class='muted'>{_esc(e.get('ts', ''))}</span> "
        f"{_esc(summary)} {actions}</li>"
    )


def _inbox_filter_html() -> str:
    boxes = "".join(
        f'<label><input type="checkbox" class="inbox-filter" value="{_esc(t)}" checked /> {_esc(label)}</label> '
        for t, label in INBOX_FILTER_TYPES
    )
    return f'<div id="inboxFilters" class="muted">{boxes}</div>'


def run_solar_status(ws: Path | None = None) -> str:
    workspace = ws or _active_workspace()
    try:
        proc = subprocess.run(
            reg.solar_cli_argv(str(workspace), "status"),
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.stdout or proc.stderr or "(no output)"
    except Exception as exc:  # noqa: BLE001
        return f"status error: {exc}"


def _approval_row(a: dict, store) -> str:
    aid = str(a.get("approval_id", ""))
    run_id = str(a.get("run_id", ""))
    if not _valid_approval_id(aid):
        return ""
    summary = str(a.get("summary") or a.get("reason") or run_id)
    run_ctx = ""
    if run_id:
        run = store.get_run(run_id)
        if run:
            run_ctx = str(run.get("summary") or run.get("status") or "")[:200]
    ctx_line = f"<br/><span class='muted'>run context: {_esc(run_ctx)}</span>" if run_ctx else ""
    return (
        '<div class="approval-item" style="margin:12px 0">'
        f"<strong>{_esc(summary)}</strong><br/>"
        f'<span class="muted">approval {_esc(aid)} · run {_esc(run_id)}</span>'
        f"{ctx_line}<br/>"
        f'<button type="button" class="approval-act" data-id="{_esc(aid)}" data-action="approve">Approve</button> '
        f'<button type="button" class="approval-act" data-id="{_esc(aid)}" data-action="reject">Reject</button>'
        "</div>"
    )


def _fleet_rows() -> str:
    fleet = reg.fleet_health()
    rows = []
    for ws in fleet.get("workspaces", []):
        path = ws.get("path", "")
        label = ws.get("label", "")
        sev = ws.get("severity", "DOWN")
        cls = {"OK": "ok", "WARN": "warn"}.get(sev, "warn")
        active = " (active)" if ws.get("active") else ""
        cursor_href = "cursor://file/" + urllib.parse.quote(path, safe="/")
        rows.append(
            f"<tr>"
            f"<td><span class='{cls}'>{_esc(sev)}</span></td>"
            f"<td><strong>{_esc(label)}</strong>{_esc(active)}<br/>"
            f"<span class='muted'>{_esc(path)}</span></td>"
            f"<td>{_esc(ws.get('interface_base', ''))}</td>"
            f"<td>"
            f'<button type="button" class="ws-use" data-path="{_esc(path)}">Use</button> '
            f'<a href="{_esc(cursor_href)}">Cursor</a>'
            f"</td></tr>"
        )
    return "\n".join(rows) if rows else "<tr><td colspan='4'>No workspaces registered.</td></tr>"


def _refresh_health_events(ws: Path) -> None:
    try:
        health_monitor.scan_fleet(str(ws))
    except Exception:  # noqa: BLE001
        pass


def dashboard_html() -> str:
    reg.record_metric("dashboard_view")
    ws = _active_workspace()
    _refresh_health_events(ws)
    store = _active_store()
    ready, _checks = store.readiness()
    approvals = store.list_approvals()
    api_label = "OK" if ready else "DOWN"
    api_class = "ok" if ready else "warn"
    pending = [a for a in approvals if a.get("status") == "pending"]
    status_text = run_solar_status(ws)
    jobs = reg.list_async_jobs(str(ws))
    jobs_html = "".join(
        f"<li><strong>{_esc(j.get('state'))}</strong> {_esc(j.get('summary', j.get('id')))} "
        f"<span class='muted'>{_esc(j.get('file', ''))}</span></li>"
        for j in jobs[:15]
    ) or "<li class='muted'>No async jobs found.</li>"
    pending_html = "".join(_approval_row(a, store) for a in pending[:20])
    if not pending_html:
        pending_html = "<p class='muted'>No pending approvals.</p>"
    events = host_events.list_recent(20)
    inbox_html = "".join(_inbox_event_li(e) for e in events) or "<li class='muted'>No recent events.</li>"
    host_url = f"http://{HOST}:{PORT}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Solar Host</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #0f1419; color: #e7ecf3; }}
    h1,h2 {{ margin: 0 0 8px; }}
    .muted {{ color: #9aa7b5; }}
    section {{ margin: 20px 0; padding: 16px; border: 1px solid #2a3542; border-radius: 10px; }}
    pre, textarea {{ white-space: pre-wrap; background: #1a222c; padding: 12px; border-radius: 8px; width: 100%; box-sizing: border-box; color: #e7ecf3; }}
    button {{ margin-right: 8px; padding: 6px 12px; cursor: pointer; }}
    .ok {{ color: #6dd58c; }}
    .warn {{ color: #e8b84a; }}
    .inbox-focus {{ outline: 2px solid #e8b84a; border-radius: 6px; padding: 4px; }}
    #inboxFilters label {{ margin-right: 12px; display: inline-block; }}
    .badge {{ background: #e8b84a; color: #0f1419; padding: 2px 8px; border-radius: 999px; font-size: 12px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ padding: 8px; border-bottom: 1px solid #2a3542; text-align: left; }}
    #chatOut {{ min-height: 120px; }}
  </style>
</head>
<body>
  <h1>Solar Host</h1>
  <p class="muted">Control plane — active workspace <code>{_esc(ws)}</code></p>
  <p>Host: <span class="ok">OK</span> <span class="muted">({_esc(host_url)} — this page)</span></p>
  <section>
    <h2>Fleet</h2>
    <p class="muted">Health = workspace + in-process runtime. Host stays up on :{PORT}.</p>
    <table><thead><tr><th>Health</th><th>Workspace</th><th>Runtime</th><th>Actions</th></tr></thead>
    <tbody>{_fleet_rows()}</tbody></table>
  </section>
  <section>
    <h2>Fleet operations</h2>
    <p class="muted">Run Solar Client / workspace doctors on the active workspace (localhost only).</p>
    <button type="button" class="client-act" data-action="sync" id="btnClientSync">Sync skills</button>
    <button type="button" class="client-act" data-action="client_doctor" id="btnClientDoctor">Client doctor</button>
    <button type="button" class="client-act" data-action="workspace_doctor" id="btnWsDoctor">Workspace doctor</button>
    <label class="muted" style="margin-left:12px"><input type="checkbox" id="clientStrict" /> strict</label>
    <pre id="clientActOut" class="muted">(no output yet)</pre>
  </section>
  <section>
    <h2>Runtime (active)</h2>
    <p>Host: <span class="ok">OK</span> <span class="muted">({_esc(host_url)})</span></p>
    <p>Workspace runtime: <span class="{api_class}">{api_label}</span> <span class="muted">(in-process on :9000)</span></p>
    <pre>{_esc(status_text)}</pre>
    <button type="button" id="btnKill">Kill switch (stop gateway)</button>
    <button type="button" id="btnEnsureGw">Start gateway</button>
  </section>
  <section>
    <h2>Approvals <span class="badge" id="pendingBadge">{len(pending)}</span></h2>
    {pending_html}
  </section>
  <section>
    <h2>Inbox</h2>
    <p class="muted">Recent runtime events (poll every 10s). Deep-link: <code>?focus=approval:&lt;id&gt;</code></p>
    {_inbox_filter_html()}
    <button type="button" id="btnInboxRefresh">Refresh inbox</button>
    <ul id="inboxList">{inbox_html}</ul>
  </section>
  <section>
    <h2>Async monitor</h2>
    <ul>{jobs_html}</ul>
  </section>
  <section>
    <h2>Scoped chat</h2>
    <p class="muted">Context: active workspace agent (not generalist chat).</p>
    <textarea id="chatIn" rows="3" placeholder="Ask about this workspace..."></textarea>
    <button type="button" id="btnChat">Send</button>
    <pre id="chatOut"></pre>
  </section>
  <section>
    <h2>Governance editor</h2>
    <input id="govPath" value="sun/MEMORY.md" style="width:100%;padding:8px;margin-bottom:8px"/>
    <button type="button" id="btnGovLoad">Load</button>
    <button type="button" id="btnGovSave">Save</button>
    <textarea id="govBody" rows="12"></textarea>
  </section>
  <script>
    async function postJson(url, body) {{
      const r = await fetch(url, {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(body || {{}}) }});
      return r;
    }}
    function esc(s) {{
      return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
    }}
    async function actApproval(id, action) {{
      const r = await fetch(`/api/approvals/${{encodeURIComponent(id)}}/${{action}}`, {{ method: "POST" }});
      if (r.ok) location.reload(); else alert(await r.text());
    }}
    document.querySelectorAll(".approval-act, .inbox-act").forEach((btn) => {{
      btn.addEventListener("click", () => actApproval(btn.dataset.id, btn.dataset.action));
    }});
    document.querySelectorAll(".ws-use").forEach((btn) => {{
      btn.addEventListener("click", async () => {{
        const r = await postJson("/api/workspaces/active", {{ path: btn.dataset.path }});
        if (r.ok) location.reload(); else alert(await r.text());
      }});
    }});
    document.getElementById("btnKill").onclick = async () => {{
      if (!confirm("Emergency stop gateway for active workspace?")) return;
      const r = await postJson("/api/kill", {{}});
      alert(await r.text()); location.reload();
    }};
    document.getElementById("btnEnsureGw").onclick = async () => {{
      const r = await postJson("/api/runtime/gateway/start", {{}}); alert(await r.text());
    }};
    async function runClientAction(action) {{
      const strict = document.getElementById("clientStrict").checked;
      document.querySelectorAll(".client-act").forEach((b) => {{ b.disabled = true; }});
      const out = document.getElementById("clientActOut");
      out.textContent = "Running " + action + "…";
      try {{
        const r = await postJson("/api/actions/client", {{ action, strict }});
        const data = await r.json();
        out.textContent = data.output || JSON.stringify(data);
        if (!r.ok) alert(data.error || r.status);
        refreshInbox();
      }} catch (e) {{
        out.textContent = String(e);
      }} finally {{
        document.querySelectorAll(".client-act").forEach((b) => {{ b.disabled = false; }});
      }}
    }}
    document.querySelectorAll(".client-act").forEach((btn) => {{
      btn.addEventListener("click", () => runClientAction(btn.dataset.action));
    }});
    document.getElementById("btnChat").onclick = async () => {{
      const msg = document.getElementById("chatIn").value;
      const r = await postJson("/api/chat", {{ message: msg }});
      document.getElementById("chatOut").textContent = await r.text();
    }};
    document.getElementById("btnGovLoad").onclick = async () => {{
      const p = document.getElementById("govPath").value;
      const r = await fetch("/api/governance/file?path=" + encodeURIComponent(p));
      document.getElementById("govBody").value = await r.text();
    }};
    document.getElementById("btnGovSave").onclick = async () => {{
      const p = document.getElementById("govPath").value;
      const r = await fetch("/api/governance/file?path=" + encodeURIComponent(p), {{
        method: "PUT", headers: {{ "Content-Type": "text/plain" }}, body: document.getElementById("govBody").value
      }});
      alert(r.ok ? "Saved" : await r.text());
    }};
    function selectedInboxTypes() {{
      return Array.from(document.querySelectorAll(".inbox-filter:checked")).map((el) => el.value);
    }}
    function inboxItemHtml(e) {{
      const p = e.payload || {{}};
      const summary = p.summary || p.label || p.run_id || "";
      const aid = p.approval_id || "";
      let actions = "";
      if (e.type === "approval.pending" && aid) {{
        actions = `<span class="inbox-actions">`
          + `<button type="button" class="inbox-act" data-id="${{esc(aid)}}" data-action="approve">Approve</button> `
          + `<button type="button" class="inbox-act" data-id="${{esc(aid)}}" data-action="reject">Reject</button></span>`;
      }}
      const liId = aid ? ` id="inbox-approval-${{esc(aid)}}"` : "";
      return `<li class="inbox-item" data-type="${{esc(e.type)}}"${{liId}}>`
        + `<strong>${{esc(e.type)}}</strong> <span class="muted">${{esc(e.ts)}}</span> `
        + `${{esc(summary)}} ${{actions}}</li>`;
    }}
    async function refreshInbox() {{
      const types = selectedInboxTypes();
      const qs = new URLSearchParams({{ limit: "20" }});
      if (types.length) qs.set("types", types.join(","));
      const r = await fetch("/api/events?" + qs.toString());
      if (!r.ok) return;
      const data = await r.json();
      const ul = document.getElementById("inboxList");
      const events = (data.events || []).filter((e) => !types.length || types.includes(e.type));
      ul.innerHTML = events.map(inboxItemHtml).join("") || "<li class='muted'>No recent events.</li>";
      ul.querySelectorAll(".inbox-act").forEach((btn) => {{
        btn.addEventListener("click", () => actApproval(btn.dataset.id, btn.dataset.action));
      }});
      applyInboxFocus();
    }}
    function applyInboxFocus() {{
      const params = new URLSearchParams(location.search);
      const focus = params.get("focus") || "";
      if (!focus.startsWith("approval:")) return;
      const id = focus.slice("approval:".length);
      const el = document.getElementById("inbox-approval-" + id);
      if (el) {{
        el.classList.add("inbox-focus");
        el.scrollIntoView({{ behavior: "smooth", block: "center" }});
      }}
    }}
    document.querySelectorAll(".inbox-filter").forEach((el) => {{
      el.addEventListener("change", refreshInbox);
    }});
    document.getElementById("btnInboxRefresh").onclick = refreshInbox;
    setInterval(refreshInbox, 10000);
    applyInboxFocus();
  </script>
</body>
</html>"""


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", 0))
    return handler.rfile.read(length) if length else b""


def _run_script(script_rel: str, ws: Path) -> tuple[int, str]:
    parts = script_rel.split("/", 1)
    skill = parts[0]
    name = parts[1] if len(parts) > 1 else ""
    script = _skill_script(skill, name)
    if not script.is_file():
        return 1, f"missing script: {script}"
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(ws),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, "SOLAR_WORKSPACE": str(ws)},
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _kill_runtime(ws: Path) -> dict[str, object]:
    results = []
    gw_port = reg.port_offsets(str(ws))[1]
    try:
        proc = subprocess.run(
            ["lsof", "-ti", f"tcp:{gw_port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        for pid in (proc.stdout or "").split():
            if pid.strip().isdigit():
                subprocess.run(["kill", pid.strip()], check=False)
                results.append({"step": "kill_gateway", "pid": pid.strip()})
    except Exception as exc:  # noqa: BLE001
        results.append({"step": "kill_gateway", "error": str(exc)})
    lock = "/tmp/com.solar.system.lock"
    if Path(lock).exists():
        subprocess.run(["rm", "-rf", lock], check=False)
        results.append({"step": "clear_orchestrator_lock"})
    reg.record_metric("kill_switch", {"workspace": str(ws)})
    return {"ok": True, "results": results}


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
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        ws = _active_workspace()

        if _dispatch_interface_get(self, path):
            return

        if path in ("/", "/dashboard"):
            self._send(dashboard_html().encode("utf-8"))
            return
        if path == "/health":
            self._send_json({"status": "ok", "service": "solar-host", "port": PORT})
            return
        if path == "/api/status":
            self._send_json({"text": run_solar_status(ws), "workspace": str(ws)})
            return
        if path == "/api/workspaces":
            self._send_json({"workspaces": reg.list_workspaces(), "active_path": reg.get_active_path()})
            return
        if path == "/api/fleet/health":
            _refresh_health_events(ws)
            self._send_json(reg.fleet_health())
            return
        if path == "/api/runtime/health":
            if _dispatch_interface_get(self, "/ready", route_path="/ready"):
                return
            store = _active_store()
            ready, checks = store.readiness()
            status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
            self._send_json(
                {
                    "status": "ready" if ready else "not_ready",
                    "service": "solar-host",
                    "mode": "in-process",
                    "workspace": str(ws),
                    "checks": checks,
                },
                status,
            )
            return
        if path == "/api/events":
            limit = int((qs.get("limit") or ["50"])[0])
            types = _parse_event_types(qs)
            self._send_json({"events": host_events.list_recent(limit, types=types)})
            return
        if path == "/api/approvals":
            store = _active_store()
            self._send_json({"approvals": store.list_approvals()})
            return
        if path == "/api/async/jobs":
            self._send_json({"jobs": reg.list_async_jobs(str(ws))})
            return
        if path == "/api/system/check":
            code, out = _run_script("solar-system/scripts/check_orchestrator.sh", ws)
            self._send_json({"code": code, "output": out})
            return
        if path == "/api/governance/file":
            rel = (qs.get("path") or [""])[0]
            target = reg.governance_resolve(str(ws), rel)
            if not target or not target.is_file():
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            self._send(target.read_text(encoding="utf-8").encode("utf-8"), 200, "text/plain; charset=utf-8")
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        path = self.path.split("?", 1)[0]
        if _dispatch_interface_delete(self, path):
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        path = self.path.split("?", 1)[0]
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        ws = _active_workspace()
        if path == "/api/governance/file":
            rel = (qs.get("path") or [""])[0]
            target = reg.governance_resolve(str(ws), rel)
            if not target:
                self._send_json({"error": "invalid path"}, HTTPStatus.BAD_REQUEST)
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_read_body(self).decode("utf-8"), encoding="utf-8")
            self._send_json({"ok": True, "path": rel})
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        ws = _active_workspace()

        if _dispatch_interface_post(self, path):
            return

        body_raw = _read_body(self)
        body: dict = {}
        if body_raw:
            try:
                body = json.loads(body_raw.decode("utf-8"))
            except json.JSONDecodeError:
                body = {}

        parts = path.strip("/").split("/")
        if path == "/api/workspaces/active":
            target = str(body.get("path", ""))
            try:
                active_path = ctx.switch_workspace(target)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True, "active_path": active_path})
            return
        if path == "/api/kill":
            self._send_json(_kill_runtime(ws))
            return
        if path == "/api/runtime/gateway/start":
            code, out = _run_script("solar-gateway/scripts/ensure_transport_gateway.sh", ws)
            self._send_json({"code": code, "output": out})
            return
        if path == "/api/runtime/interface/start":
            self._send_json(
                {
                    "deprecated": True,
                    "ok": True,
                    "hint": "API is in-process on :9000",
                }
            )
            return
        if path == "/api/actions/client":
            if not client_actions.is_loopback_client(self):
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if not client_actions.validate_client_request(self, PORT):
                self._send_json({"error": "forbidden Host/Origin"}, HTTPStatus.FORBIDDEN)
                return
            action = str(body.get("action", "")).strip()
            strict = bool(body.get("strict"))
            code, payload = client_actions.run_action(str(ws), action, strict=strict)
            self._send_json(payload, code)
            return
        if path == "/api/chat":
            msg = str(body.get("message", "")).strip()
            if not msg:
                self._send_json({"error": "empty message"}, HTTPStatus.BAD_REQUEST)
                return
            scoped = (
                f"[Solar Host scoped chat — workspace {ws}]\n"
                f"Use only context from sun/, planets/, skills. User question:\n{msg}"
            )
            store = _active_store()
            thread = store.create_thread(title="Host scoped")
            run_record, router_response = store.run_thread_message(
                thread_id=thread["thread_id"],
                text=scoped,
                mode="ask",
            )
            if run_record.get("status") != "succeeded":
                host_events.emit(
                    "run.failed",
                    {
                        "summary": str(run_record.get("error") or run_record.get("status") or "chat run failed"),
                        "run_id": run_record.get("run_id"),
                    },
                    workspace=str(ws),
                )
            status = HTTPStatus.OK if run_record.get("status") == "succeeded" else HTTPStatus.BAD_GATEWAY
            body_out: dict[str, object] = {
                "run": run_record,
                "reply_text": router_response.get("reply_text", ""),
                "router": router_response,
            }
            if status != HTTPStatus.OK:
                body_out["error"] = router_response.get("error") or "router failed — check solar router doctor"
            self._send_json(body_out, status)
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "approvals" and parts[3] in ("approve", "reject"):
            aid = parts[2]
            if not _valid_approval_id(aid):
                self._send_json({"error": "invalid approval id"}, HTTPStatus.BAD_REQUEST)
                return
            store = _active_store()
            if parts[3] == "approve":
                payload, err_code = store.approve(aid)
            else:
                payload, err_code = store.reject(aid)
            if err_code is None or err_code == HTTPStatus.OK:
                host_events.emit(
                    "approval.resolved",
                    {
                        "approval_id": aid,
                        "action": parts[3],
                        "status": payload.get("status"),
                        "summary": aid,
                    },
                    workspace=str(ws),
                )
            self._send_json(payload, err_code or HTTPStatus.OK)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)


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
            "run: solar host workspace add <path>",
            file=sys.stderr,
        )
        return 1
    try:
        ctx.mount(active)
        hi.get_store(active)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    ws = _active_workspace()

    def _health_poller() -> None:
        while True:
            time.sleep(60)
            try:
                active = reg.get_active_path()
                if active:
                    health_monitor.scan_fleet(active)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_health_poller, daemon=True, name="host-health").start()

    server = ThreadingHTTPServer((HOST, PORT), HostHandler)
    print(f"Solar Host listening on http://{HOST}:{PORT} (workspace={ws})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
