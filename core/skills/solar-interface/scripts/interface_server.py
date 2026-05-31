#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from solar_paths import resolve_solar_paths, resolve_under_home  # noqa: E402

SOLAR_WORKSPACE, SOLAR_ROOT = resolve_solar_paths()

ENV_PATH = SOLAR_WORKSPACE / ".env"
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
# Export .env vars to os.environ so subprocesses (router, providers) inherit them.
for _k, _v in ENV.items():
    os.environ.setdefault(_k, _v)
HOST = ENV.get("SOLAR_INTERFACE_HOST", "127.0.0.1")
PORT = int(ENV.get("SOLAR_INTERFACE_PORT", "7741"))
CONTEXT_TURNS = int(ENV.get("SOLAR_ROUTER_CONTEXT_TURNS", "12"))
RUNTIME_DIR = SOLAR_WORKSPACE / ENV.get("SOLAR_INTERFACE_RUNTIME_DIR", "sun/runtime/interface")
_router_runtime_dir = pathlib.Path(ENV.get("SOLAR_ROUTER_RUNTIME_DIR", "sun/runtime/router"))
ROUTER_RUNTIME_DIR = _router_runtime_dir if _router_runtime_dir.is_absolute() else SOLAR_WORKSPACE / _router_runtime_dir
ROUTER_CONVERSATIONS_DIR = ROUTER_RUNTIME_DIR / "conversations"
DB_DIR = RUNTIME_DIR / "db"
MIGRATIONS_DIR = DB_DIR / "migrations"
DB_PATH = DB_DIR / "interface.sqlite"
STATE_DIR = RUNTIME_DIR / "state"
THREADS_DIR = RUNTIME_DIR / "threads"
RUNS_DIR = RUNTIME_DIR / "runs"
PID_FILE = STATE_DIR / "interface.pid"
ROUTER_SCRIPT = resolve_under_home("core/skills/solar-router/scripts/run_router.py")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sanitize_runtime_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return cleaned[:120] if cleaned else "unknown"


def _strip_solar_tags(text: str) -> str:
    """Remove <solar_summary> and <solar_decision> blocks from model output."""
    import re
    text = re.sub(r"\s*<solar_decision>[^<]*</solar_decision>", "", text)
    text = re.sub(r"\s*<solar_summary>.*?</solar_summary>", "", text, flags=re.DOTALL)
    return text.strip()


def _extract_reply_text_from_wrapped_json(text: str) -> str | None:
    """Return reply_text when provider returns decision-wrapper JSON; else None."""
    raw = text.strip()
    if not raw:
        return None
    # Fast gate to avoid parsing normal prose responses.
    if '"decision"' not in raw or '"reply_text"' not in raw:
        return None
    # Remove optional markdown fences.
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    reply_text = payload.get("reply_text")
    return reply_text if isinstance(reply_text, str) and reply_text.strip() else None


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


def write_user_input(run_id: str, text: str) -> pathlib.Path:
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = run_dir / "input.md"
    input_path.write_text(text, encoding="utf-8")
    return input_path


def build_thread_context(thread_id: str, current_text: str, mode: str) -> str:
    # Context is managed entirely by solar-router via rolling summary.
    # The interface passes only the current message.
    if mode == "plan":
        return f"Return a concise actionable plan for:\n\n{current_text}"
    return current_text


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


def is_run_stale(run: sqlite3.Row | dict) -> bool:
    status = str(run["status"])
    if status not in {"running", "queued"}:
        return False

    pid = run["pid"]
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            return False
        except OSError:
            return True

    started_at = str(run["started_at"] or "")
    if not started_at:
        return True
    try:
        started = dt.datetime.fromisoformat(started_at)
    except ValueError:
        return True
    return (dt.datetime.now(dt.timezone.utc) - started) > dt.timedelta(minutes=10)


def delete_thread(thread_id: str) -> dict:
    conn = connect_db()
    try:
        thread = conn.execute(
            "SELECT * FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise KeyError(thread_id)

        candidate_active_runs = conn.execute(
            """
            SELECT run_id, status, pid, started_at
            FROM runs
            WHERE thread_id = ? AND status NOT IN ('success', 'succeeded', 'failed', 'rejected')
            ORDER BY started_at DESC
            """,
            (thread_id,),
        ).fetchall()

        active_runs = []
        stale_run_ids = []
        for run in candidate_active_runs:
            if is_run_stale(run):
                stale_run_ids.append(run["run_id"])
            else:
                active_runs.append(run)

        if stale_run_ids:
            placeholders = ",".join("?" for _ in stale_run_ids)
            conn.execute(
                f"""
                UPDATE runs
                SET status = 'failed',
                    ended_at = COALESCE(ended_at, ?),
                    error = COALESCE(error, 'stale run auto-closed during thread delete')
                WHERE run_id IN ({placeholders})
                """,
                (now_iso(), *stale_run_ids),
            )

        if active_runs:
            raise ValueError(active_runs[0]["status"])

        run_ids = [
            row["run_id"]
            for row in conn.execute(
                "SELECT run_id FROM runs WHERE thread_id = ?",
                (thread_id,),
            ).fetchall()
        ]

        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            conn.execute(
                f"DELETE FROM artifacts WHERE run_id IN ({placeholders})",
                tuple(run_ids),
            )
            conn.execute(
                f"DELETE FROM approvals WHERE run_id IN ({placeholders})",
                tuple(run_ids),
            )
            conn.execute(
                f"DELETE FROM runs WHERE run_id IN ({placeholders})",
                tuple(run_ids),
            )

        conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
        conn.commit()
    finally:
        conn.close()

    deleted_dirs = 0
    for run_id in run_ids:
        run_dir = RUNS_DIR / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
            deleted_dirs += 1

    router_files_deleted = 0
    sanitized_thread_id = sanitize_runtime_id(thread_id)
    for router_file in (
        ROUTER_CONVERSATIONS_DIR / f"{sanitized_thread_id}.jsonl",
        ROUTER_CONVERSATIONS_DIR / f"{sanitized_thread_id}-summary.txt",
    ):
        if router_file.exists():
            router_file.unlink()
            router_files_deleted += 1

    return {
        "thread_id": thread_id,
        "deleted_runs": len(run_ids),
        "deleted_run_dirs": deleted_dirs,
        "deleted_router_files": router_files_deleted,
    }


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
    write_event(run_id, {"type": "input_received", "run_id": run_id, "text": text, "ts": started_at})
    input_path = write_user_input(run_id, text)

    router_text = build_thread_context(thread_id, text, mode)

    payload = {
        "request_id": request_id,
        "session_id": thread_id,
        "user_id": thread_id,
        "text": router_text,
        "channel": "other",
        "mode": "direct_only",
        "provider": None if provider == "auto" else provider,
        "metadata": {"agent": None, "skills": [], "planet": None},
    }

    proc = subprocess.run(
        ["python3", str(ROUTER_SCRIPT)],
        cwd=str(SOLAR_WORKSPACE),
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
                (artifact_id, run_id, "response", str((run_dir / "output.md").relative_to(SOLAR_WORKSPACE)), "Run output", ended_at),
            )
        conn.execute(
            """
            INSERT INTO artifacts(artifact_id, run_id, kind, path, title, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"artifact_{uuid.uuid4().hex[:10]}", run_id, "request", str(input_path.relative_to(SOLAR_WORKSPACE)), "User input", started_at),
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
            host_port = ENV.get("SOLAR_HOST_PORT", "9000")
            host_url = f"http://127.0.0.1:{host_port}"
            self._send_html(
                f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="3;url={host_url}">
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
    <p><strong>Primary human UX:</strong> <a href="{host_url}">Solar Host</a> (redirecting in 3s). This daemon remains the API backend on :7741.</p>
    <p>Local API for threads, runs, approvals, and runtime inspection.</p>
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
                "runtime_dir": str(RUNTIME_DIR.relative_to(SOLAR_WORKSPACE)),
                "db_path": str(DB_PATH.relative_to(SOLAR_WORKSPACE)),
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
        if path.startswith("/threads/") and path.endswith("/runs"):
            parts = path.strip("/").split("/")
            tid = parts[1]
            self._send({"runs": list_rows(
                "SELECT * FROM runs WHERE thread_id = ? ORDER BY started_at ASC", (tid,)
            )})
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

    def _stream_run(self, thread_id: str, data: dict) -> None:
        """SSE endpoint: streams router JSONL chunks to the client as server-sent events."""
        run_id = f"run_{__import__('uuid').uuid4().hex[:10]}"
        request_id = f"req_{__import__('uuid').uuid4().hex[:10]}"
        started_at = now_iso()
        provider = data.get("provider", "auto")
        text = data.get("text", "")
        mode = data.get("mode", "ask")

        conn = connect_db()
        try:
            conn.execute(
                "INSERT INTO runs(run_id, request_id, thread_id, status, provider_requested, provider_used, router_id, pid, started_at, ended_at, summary, error) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL)",
                (run_id, request_id, thread_id, "running", provider, started_at),
            )
            conn.commit()
        finally:
            conn.close()

        write_event(run_id, {"type": "run_created", "run_id": run_id, "ts": started_at})
        write_event(run_id, {"type": "status_changed", "run_id": run_id, "status": "running", "ts": started_at})
        write_event(run_id, {"type": "input_received", "run_id": run_id, "text": text, "ts": started_at})
        input_path = write_user_input(run_id, text)

        router_text = build_thread_context(thread_id, text, mode)
        payload = {
            "request_id": request_id,
            "session_id": thread_id,
            "user_id": thread_id,
            "text": router_text,
            "channel": "other",
            "mode": "direct_only",
            "stream": True,
        }
        if provider and provider != "auto":
            payload["provider"] = provider

        # Send SSE headers
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Run-Id", run_id)
        self.end_headers()

        proc = subprocess.Popen(
            ["python3", str(ROUTER_SCRIPT)],
            cwd=str(SOLAR_WORKSPACE),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        proc.stdin.write(json.dumps(payload, ensure_ascii=False))  # type: ignore[union-attr]
        proc.stdin.close()  # type: ignore[union-attr]

        full_text_parts: list[str] = []
        provider_used: str | None = None
        usage: dict | None = None
        status = "failed"
        error: str | None = None
        client_disconnected = False
        # Buffer chunks once a solar tag opening is detected; flushed/dropped at done.
        tag_buffer: list[str] = []
        in_solar_tag = False

        try:
            for raw_line in proc.stdout:  # type: ignore[union-attr]
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "chunk":
                    chunk = event.get("text", "")
                    if not chunk:
                        continue
                    full_text_parts.append(chunk)
                    if in_solar_tag:
                        # Already inside a tag block — buffer everything
                        tag_buffer.append(chunk)
                        continue
                    # Check if this chunk contains the start of a solar tag
                    tag_start = chunk.find("<solar_")
                    if tag_start != -1:
                        in_solar_tag = True
                        visible = chunk[:tag_start]
                        tag_buffer.append(chunk[tag_start:])
                        if not visible:
                            continue
                        chunk = visible
                    try:
                        sse = f"data: {json.dumps({'type': 'chunk', 'text': chunk}, ensure_ascii=False)}\n\n"
                        self.wfile.write(sse.encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        client_disconnected = True
                elif event.get("type") == "done":
                    status = event.get("status", "failed")
                    provider_used = event.get("provider")
                    event_usage = event.get("usage")
                    if isinstance(event_usage, dict):
                        usage = event_usage
                    error = event.get("error")

            proc.wait()
        except (BrokenPipeError, ConnectionResetError):
            client_disconnected = True
            status = "failed"
            error = "client disconnected"
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)

        # Strip solar tags from the full accumulated text
        reply_text = _strip_solar_tags("".join(full_text_parts))
        ended_at = now_iso()
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if reply_text and not client_disconnected:
            (run_dir / "output.md").write_text(reply_text, encoding="utf-8")

        conn = connect_db()
        try:
            conn.execute(
                "UPDATE runs SET status = ?, provider_used = ?, ended_at = ?, summary = ?, error = ? WHERE run_id = ?",
                (status, provider_used, ended_at, reply_text[:200] if reply_text else None, error, run_id),
            )
            conn.execute(
                "INSERT INTO artifacts(artifact_id, run_id, kind, path, title, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f"artifact_{uuid.uuid4().hex[:10]}", run_id, "request", str(input_path.relative_to(SOLAR_WORKSPACE)), "User input", started_at),
            )
            if reply_text and not client_disconnected:
                conn.execute(
                    "INSERT INTO artifacts(artifact_id, run_id, kind, path, title, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"artifact_{uuid.uuid4().hex[:10]}", run_id, "response", str((run_dir / "output.md").relative_to(SOLAR_WORKSPACE)), "Run output", ended_at),
                )
            conn.commit()
        finally:
            conn.close()
        update_thread_last_run(thread_id, run_id)

        # Send final SSE done event only if client is still connected.
        if not client_disconnected:
            done_evt = json.dumps({"type": "done", "run_id": run_id, "provider": provider_used, "status": status, "usage": usage, "error": error}, ensure_ascii=False)
            try:
                self.wfile.write(f"data: {done_evt}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

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

        if path.startswith("/threads/") and path.endswith("/stream"):
            parts = path.strip("/").split("/")
            thread_id = parts[1]
            thread = get_row("SELECT * FROM threads WHERE thread_id = ?", (thread_id,))
            if not thread:
                self._send({"error": "Thread not found"}, 404)
                return
            self._stream_run(thread_id, data)
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

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path

        if path.startswith("/threads/"):
            thread_id = path.strip("/").split("/")[1]
            try:
                result = delete_thread(thread_id)
            except KeyError:
                self._send({"error": "Thread not found"}, 404)
                return
            except ValueError as exc:
                self._send(
                    {"error": f"Thread has a non-terminal run: {exc}"},
                    HTTPStatus.CONFLICT,
                )
                return

            self._send({"status": "deleted", **result})
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
