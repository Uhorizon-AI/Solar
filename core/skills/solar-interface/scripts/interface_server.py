#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
ENV_PATH = REPO_ROOT / ".env"
MIGRATION_SOURCE = pathlib.Path(__file__).resolve().parent.parent / "references" / "001_initial.sql"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = load_env()
HOST = ENV.get("SOLAR_INTERFACE_HOST", "127.0.0.1")
PORT = int(ENV.get("SOLAR_INTERFACE_PORT", "7741"))
RUNTIME_DIR = REPO_ROOT / ENV.get("SOLAR_INTERFACE_RUNTIME_DIR", "sun/runtime/interface")
DB_DIR = RUNTIME_DIR / "db"
MIGRATIONS_DIR = DB_DIR / "migrations"
DB_PATH = DB_DIR / "interface.sqlite"
STATE_DIR = RUNTIME_DIR / "state"
THREADS_DIR = RUNTIME_DIR / "threads"
RUNS_DIR = RUNTIME_DIR / "runs"
PID_FILE = STATE_DIR / "interface.pid"
ROUTER_SCRIPT = REPO_ROOT / "core" / "skills" / "solar-router" / "scripts" / "run_router.py"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify_title(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    return cleaned[:60] if cleaned else f"Thread {now_iso()}"


def ensure_runtime() -> None:
    for path in (DB_DIR, MIGRATIONS_DIR, STATE_DIR, THREADS_DIR, RUNS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MIGRATION_SOURCE, MIGRATIONS_DIR / "001_initial.sql")
    apply_migrations()


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def apply_migrations() -> None:
    conn = connect_db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (0)")
            current = 0
        else:
            current = int(row["version"])
        for migration in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(migration.name.split("_", 1)[0])
            if version <= current:
                continue
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute("UPDATE schema_version SET version = ?", (version,))
            current = version
        conn.commit()
    finally:
        conn.close()


def readiness_report() -> tuple[bool, dict]:
    checks: dict[str, object] = {
        "runtime_dir": RUNTIME_DIR.exists(),
        "db_path": DB_PATH.exists(),
        "router_script": ROUTER_SCRIPT.exists(),
    }

    schema_version: int | None = None
    tables_ok = False
    db_error: str | None = None
    required_tables = {"schema_version", "sessions", "threads", "runs", "approvals", "artifacts"}

    if checks["db_path"]:
        conn: sqlite3.Connection | None = None
        try:
            conn = connect_db()
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            tables_ok = required_tables.issubset(tables)
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            schema_version = int(row["version"]) if row else None
        except Exception as exc:
            db_error = str(exc)
        finally:
            if conn is not None:
                conn.close()

    checks["tables"] = tables_ok
    checks["schema_version"] = schema_version
    if db_error:
        checks["db_error"] = db_error

    ready = bool(checks["runtime_dir"] and checks["db_path"] and checks["router_script"] and tables_ok)
    return ready, checks


def write_event(run_id: str, event: dict) -> None:
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def create_thread(title: str | None = None, scope_layer: str = "sun", scope_planet: str | None = None) -> dict:
    thread_id = f"thread_{uuid.uuid4().hex[:10]}"
    created_at = now_iso()
    final_title = slugify_title(title or "")
    conn = connect_db()
    try:
        conn.execute(
            """
            INSERT INTO threads(thread_id, title, scope_layer, scope_planet, created_at, updated_at, last_run_id)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (thread_id, final_title, scope_layer, scope_planet, created_at, created_at),
        )
        conn.commit()
    finally:
        conn.close()
    thread_doc = THREADS_DIR / f"{thread_id}.md"
    thread_doc.write_text(f"# {final_title}\n", encoding="utf-8")
    return {
        "thread_id": thread_id,
        "title": final_title,
        "scope": {"layer": scope_layer, "planet": scope_planet},
        "created_at": created_at,
        "updated_at": created_at,
        "last_run_id": None,
    }


def list_rows(query: str, params: tuple = ()) -> list[dict]:
    conn = connect_db()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_row(query: str, params: tuple = ()) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_thread_last_run(thread_id: str, run_id: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "UPDATE threads SET last_run_id = ?, updated_at = ? WHERE thread_id = ?",
            (run_id, now_iso(), thread_id),
        )
        conn.commit()
    finally:
        conn.close()


def run_router(thread_id: str, mode: str, text: str, provider: str = "auto") -> tuple[dict, dict]:
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    started_at = now_iso()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_db()
    try:
        conn.execute(
            """
            INSERT INTO runs(run_id, request_id, thread_id, status, provider_requested, provider_used, router_id, pid, started_at, ended_at, summary, error)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL)
            """,
            (run_id, request_id, thread_id, "running", provider, started_at),
        )
        conn.commit()
    finally:
        conn.close()

    write_event(run_id, {"type": "run_created", "run_id": run_id, "ts": started_at})
    write_event(run_id, {"type": "status_changed", "run_id": run_id, "status": "running", "ts": started_at})

    router_text = text
    if mode == "plan":
        router_text = f"Return a concise actionable plan for:\n\n{text}"

    payload = {
        "request_id": request_id,
        "session_id": thread_id,
        "user_id": "local-interface",
        "text": router_text,
        "channel": "other",
        "mode": "direct_only",
        "provider": None if provider == "auto" else provider,
        "metadata": {"agent": None, "skills": [], "planet": None},
    }

    proc = subprocess.run(
        ["python3", "core/skills/solar-router/scripts/run_router.py"],
        cwd=str(REPO_ROOT),
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
    )

    ended_at = now_iso()
    response: dict
    try:
        response = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        response = {"status": "failed", "error": proc.stderr.strip() or "Invalid router output"}

    status = "succeeded" if response.get("status") == "success" else "failed"
    reply_text = response.get("reply_text", "")
    provider_used = response.get("provider_used")
    summary = reply_text[:200] if reply_text else None
    error = response.get("error")

    if reply_text:
        write_event(run_id, {"type": "output_delta", "run_id": run_id, "text": reply_text, "ts": ended_at})
        (run_dir / "output.md").write_text(reply_text, encoding="utf-8")

    if status == "succeeded":
        write_event(run_id, {"type": "run_completed", "run_id": run_id, "status": status, "ts": ended_at})
    else:
        write_event(run_id, {"type": "run_failed", "run_id": run_id, "error": error or "Router failed", "ts": ended_at})

    artifact_id = f"artifact_{uuid.uuid4().hex[:10]}"
    conn = connect_db()
    try:
        conn.execute(
            """
            UPDATE runs
            SET status = ?, provider_used = ?, ended_at = ?, summary = ?, error = ?
            WHERE run_id = ?
            """,
            (status, provider_used, ended_at, summary, error, run_id),
        )
        if reply_text:
            conn.execute(
                """
                INSERT INTO artifacts(artifact_id, run_id, kind, path, title, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, run_id, "response", str((run_dir / "output.md").relative_to(REPO_ROOT)), "Run output", ended_at),
            )
        conn.commit()
    finally:
        conn.close()

    update_thread_last_run(thread_id, run_id)
    run_record = get_row("SELECT * FROM runs WHERE run_id = ?", (run_id,)) or {}
    return run_record, response


class Handler(BaseHTTPRequestHandler):
    server_version = "SolarInterface/0.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, html: str, status: int = 200) -> None:
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> tuple[dict | None, str | None]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}, None
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as exc:
            snippet = raw[:200].replace("\n", "\\n")
            print(
                f"Invalid JSON body on {self.command} {self.path}: {exc.msg}; raw={snippet!r}",
                file=sys.stderr,
                flush=True,
            )
            return None, f"Invalid JSON body: {exc.msg}"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(
                f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Solar Interface</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f1e8;
      --panel: #fffaf0;
      --ink: #1f2937;
      --muted: #6b7280;
      --accent: #b45309;
      --border: #e5dccb;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: linear-gradient(135deg, #f7f1e3 0%, #efe4cf 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 760px;
      margin: 48px auto;
      padding: 32px;
      background: rgba(255, 250, 240, 0.92);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(78, 52, 21, 0.08);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 2rem;
    }}
    p {{
      margin: 0 0 18px;
      color: var(--muted);
      line-height: 1.55;
    }}
    ul {{
      margin: 0;
      padding-left: 20px;
    }}
    li {{
      margin: 10px 0;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }}
    code {{
      background: #f3ead9;
      padding: 2px 6px;
      border-radius: 6px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Solar Interface</h1>
    <p>Local interactive entrypoint for threads, runs, approvals, and runtime inspection.</p>
    <ul>
      <li><a href="/status">/status</a> for daemon health and recent runs.</li>
      <li><a href="/threads">/threads</a> for persisted threads.</li>
      <li><a href="/runs">/runs</a> for recent runs.</li>
      <li><a href="/approvals">/approvals</a> for pending and recent approvals.</li>
    </ul>
    <p style="margin-top: 24px;">CLI entrypoint: <code>bash core/skills/solar-interface/scripts/solar ask "..."</code></p>
  </main>
</body>
</html>"""
            )
            return
        if path == "/health":
            self._send({"status": "ok", "service": "solar-interface", "ts": now_iso()})
            return
        if path == "/ready":
            ready, checks = readiness_report()
            status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
            self._send(
                {
                    "status": "ready" if ready else "not_ready",
                    "service": "solar-interface",
                    "ts": now_iso(),
                    "checks": checks,
                },
                status,
            )
            return
        if path == "/status":
            ready, checks = readiness_report()
            runs = list_rows("SELECT run_id, status, provider_used, thread_id, started_at FROM runs ORDER BY started_at DESC LIMIT 10")
            self._send({
                "status": "ok",
                "service": "solar-interface",
                "ready": ready,
                "pid": os.getpid(),
                "host": HOST,
                "port": PORT,
                "runtime_dir": str(RUNTIME_DIR.relative_to(REPO_ROOT)),
                "db_path": str(DB_PATH.relative_to(REPO_ROOT)),
                "checks": checks,
                "runs": runs,
            })
            return
        if path == "/threads":
            self._send({"threads": list_rows("SELECT * FROM threads ORDER BY updated_at DESC")})
            return
        if path == "/runs":
            self._send({"runs": list_rows("SELECT * FROM runs ORDER BY started_at DESC LIMIT 50")})
            return
        if path == "/approvals":
            self._send({"approvals": list_rows("SELECT * FROM approvals ORDER BY requested_at DESC LIMIT 50")})
            return
        if path.startswith("/runs/"):
            run_id = path.split("/", 2)[2]
            run = get_row("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            if not run:
                self._send({"error": "Run not found"}, 404)
                return
            self._send({"run": run})
            return
        self._send({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        data, read_error = self._read_json()
        if read_error:
            self._send({"error": read_error}, 400)
            return
        assert data is not None

        if path == "/threads":
            thread = create_thread(title=data.get("title"), scope_layer=data.get("scope_layer", "sun"), scope_planet=data.get("scope_planet"))
            self._send({"thread": thread}, 201)
            return

        if path.startswith("/threads/") and path.endswith("/runs"):
            parts = path.strip("/").split("/")
            thread_id = parts[1]
            thread = get_row("SELECT * FROM threads WHERE thread_id = ?", (thread_id,))
            if not thread:
                self._send({"error": "Thread not found"}, 404)
                return
            run_record, router_response = run_router(
                thread_id=thread_id,
                mode=data.get("mode", "ask"),
                text=data.get("text", ""),
                provider=data.get("provider", "auto"),
            )
            reply_text = router_response.get("reply_text", "")
            status = 200 if run_record.get("status") == "succeeded" else 502
            self._send({"run": run_record, "reply_text": reply_text, "router": router_response}, status)
            return

        if path.startswith("/approvals/") and path.endswith("/approve"):
            approval_id = path.strip("/").split("/")[1]
            conn = connect_db()
            try:
                row = conn.execute("SELECT run_id, status FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
                if row is None:
                    self._send({"error": "Approval not found"}, 404)
                    return
                if row["status"] != "pending":
                    self._send({"error": "Approval is not pending"}, 409)
                    return
                ts = now_iso()
                conn.execute("UPDATE approvals SET status = 'approved', resolved_at = ? WHERE approval_id = ?", (ts, approval_id))
                conn.execute("UPDATE runs SET status = 'queued' WHERE run_id = ?", (row["run_id"],))
                conn.commit()
            finally:
                conn.close()
            self._send({"status": "approved", "approval_id": approval_id})
            return

        if path.startswith("/approvals/") and path.endswith("/reject"):
            approval_id = path.strip("/").split("/")[1]
            conn = connect_db()
            try:
                row = conn.execute("SELECT run_id, status FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
                if row is None:
                    self._send({"error": "Approval not found"}, 404)
                    return
                if row["status"] != "pending":
                    self._send({"error": "Approval is not pending"}, 409)
                    return
                ts = now_iso()
                conn.execute("UPDATE approvals SET status = 'rejected', resolved_at = ? WHERE approval_id = ?", (ts, approval_id))
                conn.execute("UPDATE runs SET status = 'rejected', ended_at = ? WHERE run_id = ?", (ts, row["run_id"]))
                conn.commit()
            finally:
                conn.close()
            self._send({"status": "rejected", "approval_id": approval_id})
            return

        self._send({"error": "Not found"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup-only", action="store_true")
    args = parser.parse_args()

    ensure_runtime()

    if args.setup_only:
        return

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


if __name__ == "__main__":
    main()
