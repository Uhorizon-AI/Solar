#!/usr/bin/env python3
"""Workspace-scoped interface runtime (threads, runs, approvals, DB)."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path

MIGRATION_SOURCE = Path(__file__).resolve().parent.parent / "references" / "001_initial.sql"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sanitize_runtime_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return cleaned[:120] if cleaned else "unknown"


def slugify_title(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    return cleaned[:60] if cleaned else f"Thread {now_iso()}"


class InterfaceStore:
    """Encapsulates interface runtime state for one workspace."""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve()
        self.env = self._load_env()
        self._apply_env_to_os()

        root = os.environ.get("SOLAR_ROOT", "").strip()
        if not root:
            raise RuntimeError("SOLAR_ROOT is not set")
        self.solar_root = Path(root).resolve()

        runtime_rel = self.env.get("SOLAR_INTERFACE_RUNTIME_DIR", "sun/runtime/interface")
        runtime_path = Path(runtime_rel)
        self.runtime_dir = runtime_path if runtime_path.is_absolute() else self.workspace / runtime_rel

        router_rel = Path(self.env.get("SOLAR_ROUTER_RUNTIME_DIR", "sun/runtime/router"))
        self.router_runtime_dir = router_rel if router_rel.is_absolute() else self.workspace / router_rel
        self.router_conversations_dir = self.router_runtime_dir / "conversations"

        self.db_dir = self.runtime_dir / "db"
        self.migrations_dir = self.db_dir / "migrations"
        self.db_path = self.db_dir / "interface.sqlite"
        self.state_dir = self.runtime_dir / "state"
        self.threads_dir = self.runtime_dir / "threads"
        self.runs_dir = self.runtime_dir / "runs"
        self.pid_file = self.state_dir / "interface.pid"
        self.router_script = self._resolve_under_home("core/skills/solar-router/scripts/run_router.py")
        self.context_turns = int(self.env.get("SOLAR_ROUTER_CONTEXT_TURNS", "12"))

    def _load_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        env_path = self.workspace / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
        return env

    def _apply_env_to_os(self) -> None:
        for key, val in self.env.items():
            os.environ.setdefault(key, val)
        os.environ["SOLAR_WORKSPACE"] = str(self.workspace)

    def _resolve_under_home(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p.resolve()
        text = str(rel)
        if text.startswith("core/"):
            return (self.solar_root / text).resolve()
        return (self.workspace / text).resolve()

    def ensure_runtime(self) -> None:
        for path in (self.db_dir, self.migrations_dir, self.state_dir, self.threads_dir, self.runs_dir):
            path.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(MIGRATION_SOURCE, self.migrations_dir / "001_initial.sql")
        self._apply_migrations()

    def connect_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_migrations(self) -> None:
        conn = self.connect_db()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version(version) VALUES (0)")
                current = 0
            else:
                current = int(row["version"])
            for migration in sorted(self.migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(migration.name.split("_", 1)[0])
                if version <= current:
                    continue
                conn.executescript(migration.read_text(encoding="utf-8"))
                conn.execute("UPDATE schema_version SET version = ?", (version,))
                current = version
            conn.commit()
        finally:
            conn.close()

    def readiness(self) -> tuple[bool, dict]:
        checks: dict[str, object] = {
            "runtime_dir": self.runtime_dir.exists(),
            "db_path": self.db_path.exists(),
            "router_script": self.router_script.exists(),
        }

        schema_version: int | None = None
        tables_ok = False
        db_error: str | None = None
        required_tables = {"schema_version", "sessions", "threads", "runs", "approvals", "artifacts"}

        if checks["db_path"]:
            conn: sqlite3.Connection | None = None
            try:
                conn = self.connect_db()
                tables = {
                    row["name"]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }
                tables_ok = required_tables.issubset(tables)
                row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                schema_version = int(row["version"]) if row else None
            except Exception as exc:  # noqa: BLE001
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

    def list_rows(self, query: str, params: tuple = ()) -> list[dict]:
        conn = self.connect_db()
        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_row(self, query: str, params: tuple = ()) -> dict | None:
        conn = self.connect_db()
        try:
            row = conn.execute(query, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_approvals(self, limit: int = 50) -> list[dict]:
        return self.list_rows(
            "SELECT * FROM approvals ORDER BY requested_at DESC LIMIT ?",
            (limit,),
        )

    def get_run(self, run_id: str) -> dict | None:
        return self.get_row("SELECT * FROM runs WHERE run_id = ?", (run_id,))

    def get_thread(self, thread_id: str) -> dict | None:
        return self.get_row("SELECT * FROM threads WHERE thread_id = ?", (thread_id,))

    def list_threads(self) -> list[dict]:
        return self.list_rows("SELECT * FROM threads ORDER BY updated_at DESC")

    def list_runs(self, limit: int = 50) -> list[dict]:
        return self.list_rows(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )

    def list_thread_runs(self, thread_id: str) -> list[dict]:
        return self.list_rows(
            "SELECT * FROM runs WHERE thread_id = ? ORDER BY started_at ASC",
            (thread_id,),
        )

    def create_thread(
        self,
        title: str | None = None,
        scope_layer: str = "sun",
        scope_planet: str | None = None,
    ) -> dict:
        thread_id = f"thread_{uuid.uuid4().hex[:10]}"
        created_at = now_iso()
        final_title = slugify_title(title or "")
        conn = self.connect_db()
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

    def approve(self, approval_id: str) -> tuple[dict, int | None]:
        conn = self.connect_db()
        try:
            row = conn.execute(
                "SELECT run_id, status FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return {"error": "Approval not found"}, 404
            if row["status"] != "pending":
                return {"error": "Approval is not pending"}, 409
            ts = now_iso()
            conn.execute(
                "UPDATE approvals SET status = 'approved', resolved_at = ? WHERE approval_id = ?",
                (ts, approval_id),
            )
            conn.execute("UPDATE runs SET status = 'queued' WHERE run_id = ?", (row["run_id"],))
            conn.commit()
        finally:
            conn.close()
        return {"status": "approved", "approval_id": approval_id}, None

    def reject(self, approval_id: str) -> tuple[dict, int | None]:
        conn = self.connect_db()
        try:
            row = conn.execute(
                "SELECT run_id, status FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return {"error": "Approval not found"}, 404
            if row["status"] != "pending":
                return {"error": "Approval is not pending"}, 409
            ts = now_iso()
            conn.execute(
                "UPDATE approvals SET status = 'rejected', resolved_at = ? WHERE approval_id = ?",
                (ts, approval_id),
            )
            conn.execute(
                "UPDATE runs SET status = 'rejected', ended_at = ? WHERE run_id = ?",
                (ts, row["run_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "rejected", "approval_id": approval_id}, None

    def write_event(self, run_id: str, event: dict) -> None:
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def write_user_input(self, run_id: str, text: str) -> Path:
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        input_path = run_dir / "input.md"
        input_path.write_text(text, encoding="utf-8")
        return input_path

    def build_thread_context(self, thread_id: str, current_text: str, mode: str) -> str:
        if mode == "plan":
            return f"Return a concise actionable plan for:\n\n{current_text}"
        return current_text

    def update_thread_last_run(self, thread_id: str, run_id: str) -> None:
        conn = self.connect_db()
        try:
            conn.execute(
                "UPDATE threads SET last_run_id = ?, updated_at = ? WHERE thread_id = ?",
                (run_id, now_iso(), thread_id),
            )
            conn.commit()
        finally:
            conn.close()

    def is_run_stale(self, run: sqlite3.Row | dict) -> bool:
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

    def delete_thread(self, thread_id: str) -> dict:
        conn = self.connect_db()
        run_ids: list[str] = []
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
                if self.is_run_stale(run):
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
            run_dir = self.runs_dir / run_id
            if run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)
                deleted_dirs += 1

        router_files_deleted = 0
        sanitized_thread_id = sanitize_runtime_id(thread_id)
        for router_file in (
            self.router_conversations_dir / f"{sanitized_thread_id}.jsonl",
            self.router_conversations_dir / f"{sanitized_thread_id}-summary.txt",
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

    def run_thread_message(
        self,
        thread_id: str,
        text: str,
        mode: str = "ask",
        provider: str = "auto",
    ) -> tuple[dict, dict]:
        request_id = f"req_{uuid.uuid4().hex[:10]}"
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        started_at = now_iso()
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        conn = self.connect_db()
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

        self.write_event(run_id, {"type": "run_created", "run_id": run_id, "ts": started_at})
        self.write_event(run_id, {"type": "status_changed", "run_id": run_id, "status": "running", "ts": started_at})
        self.write_event(run_id, {"type": "input_received", "run_id": run_id, "text": text, "ts": started_at})
        input_path = self.write_user_input(run_id, text)

        router_text = self.build_thread_context(thread_id, text, mode)

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
            ["python3", str(self.router_script)],
            cwd=str(self.workspace),
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
            self.write_event(run_id, {"type": "output_delta", "run_id": run_id, "text": reply_text, "ts": ended_at})
            (run_dir / "output.md").write_text(reply_text, encoding="utf-8")

        if status == "succeeded":
            self.write_event(run_id, {"type": "run_completed", "run_id": run_id, "status": status, "ts": ended_at})
        else:
            self.write_event(
                run_id,
                {"type": "run_failed", "run_id": run_id, "error": error or "Router failed", "ts": ended_at},
            )

        artifact_id = f"artifact_{uuid.uuid4().hex[:10]}"
        conn = self.connect_db()
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
                    (
                        artifact_id,
                        run_id,
                        "response",
                        str((run_dir / "output.md").relative_to(self.workspace)),
                        "Run output",
                        ended_at,
                    ),
                )
            conn.execute(
                """
                INSERT INTO artifacts(artifact_id, run_id, kind, path, title, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"artifact_{uuid.uuid4().hex[:10]}",
                    run_id,
                    "request",
                    str(input_path.relative_to(self.workspace)),
                    "User input",
                    started_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self.update_thread_last_run(thread_id, run_id)
        run_record = self.get_row("SELECT * FROM runs WHERE run_id = ?", (run_id,)) or {}
        return run_record, response
