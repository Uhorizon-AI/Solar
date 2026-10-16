#!/usr/bin/env python3
"""Solar runtime state: what is there. `solar-paths` says where.

One SQLite file, `<runtime>/state.sqlite`, holds the state more than one
component reads: tasks, the router audit, cross-channel continuity and the
events of A3 mandates. This module is the only thing that opens it.

Two guards, with different jobs:

- `<runtime>/state.lock` (flock). Every operation holds it *shared* from
  start to finish — check, read, write, commit. A cutover (`cutover()`) holds
  it *exclusive* for its whole length. Nobody can check before and write after.
  The OS releases it if the process dies.
- `<runtime>/STATE_FORMAT`, read inside the lock. This code only speaks
  `sqlite`; any other value refuses. It is what keeps things closed when a
  cutover dies halfway: the lock goes, the format stays `files`.

Schema migrations run only inside a cutover, with a backup first. A session
that finds an older schema refuses instead of upgrading under readers.

Tasks keep their frontmatter as an ordered list of `[key, text after the
colon]`, so a task exports byte for byte. The columns are a projection of that
list for queries, rewritten by this module in the same transaction.

Imports nothing but `solar-paths`.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import logging
import os
import posixpath
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_PATHS_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "solar-paths" / "scripts"
if str(_PATHS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATHS_SCRIPTS))

import solar_runtime  # noqa: E402

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no flock
    fcntl = None  # type: ignore[assignment]


FORMAT_SQLITE = "sqlite"
FORMAT_FILES = "files"
DB_NAME = "state.sqlite"
LOCK_NAME = "state.lock"
FORMAT_NAME = "STATE_FORMAT"
OWNER_NAME = "workspace-owner.json"
CUTOVER_MARKER = "state-cutover.json"
BACKUP_DIR = "state-backups"
DAILY_KEEP = 7
DAILY_MAX_AGE_SEC = 24 * 3600
DEFAULT_LOCK_TIMEOUT = float(os.environ.get("SOLAR_STATE_LOCK_TIMEOUT", "30"))
MAINTENANCE_NAME = "maintenance.json"
CAPACITY_MAX = 5
LEASE_SECONDS = int(os.environ.get("SOLAR_TASK_LEASE_SECONDS", "300"))

STATUSES = ("draft", "planned", "queued", "active", "completed", "error", "archived", "cancelled")

# Every move the async-tasks scripts make today, and nothing else.
TRANSITIONS = (
    ("draft", "planned"), ("draft", "queued"), ("draft", "cancelled"), ("draft", "archived"),
    ("planned", "queued"), ("planned", "draft"), ("planned", "cancelled"), ("planned", "archived"),
    ("queued", "active"), ("queued", "error"), ("queued", "cancelled"),
    ("queued", "draft"),         # approval withdrawn: task.return_to_draft
    ("active", "completed"), ("active", "error"), ("active", "cancelled"),
    ("active", "queued"),        # a parent goes back to wait for its subtasks
    ("completed", "queued"),     # recurring task, next run
    ("completed", "archived"),   # recurring task, max runs reached
    ("error", "queued"), ("error", "archived"), ("error", "cancelled"),
    ("cancelled", "archived"),
)
CREATE_STATUSES = ("draft", "planned", "queued")
# A dependency in one of these is finished. The folder used to say the same.
TERMINAL_STATUSES = frozenset({"completed", "archived", "error", "cancelled"})
SCHEDULE_MARGIN_MIN = 15
_PRIORITY_RANK = {"high": 2, "normal": 1, "low": 0}

# Frontmatter keys projected to columns: the ones transitions and queries use.
COLUMN_KEYS = (
    "title", "priority", "created", "updated", "completed_at", "scheduled_time",
    "provider", "parent_task_id", "origin_channel", "origin_chat_id",
    "origin_request_id", "origin_thread_id", "origin_run_id",
    "object", "scope", "effect", "notify_when", "recurring",
)
# Internal columns a transition may set besides the status. Nothing else reaches SQL.
TRANSITION_COLUMNS = ("claimed_by", "claimed_at", "pid", "log_path")
# Set once when an existing task enters the base.
IMPORT_COLUMNS = ("log_path", "source_name")

MIGRATIONS: tuple[str, ...] = (
    # v1
    """
    CREATE TABLE statuses (name TEXT PRIMARY KEY);
    CREATE TABLE transitions (
        from_status TEXT NOT NULL REFERENCES statuses(name),
        to_status   TEXT NOT NULL REFERENCES statuses(name),
        PRIMARY KEY (from_status, to_status)
    );
    CREATE TABLE tasks (
        id                TEXT PRIMARY KEY,
        status            TEXT NOT NULL REFERENCES statuses(name),
        title TEXT, priority TEXT, created TEXT, updated TEXT, completed_at TEXT,
        scheduled_time TEXT, provider TEXT, parent_task_id TEXT,
        origin_channel TEXT, origin_chat_id TEXT, origin_request_id TEXT,
        origin_thread_id TEXT, origin_run_id TEXT,
        object TEXT, scope TEXT, effect TEXT, notify_when TEXT,
        recurring         INTEGER NOT NULL DEFAULT 0,
        frontmatter       TEXT NOT NULL,          -- JSON [[key, text after ':'], ...]
        body              TEXT NOT NULL DEFAULT '',
        log_path TEXT, pid INTEGER, claimed_by TEXT, claimed_at TEXT,
        row_version       INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX tasks_status ON tasks(status, priority, created);
    CREATE INDEX tasks_parent ON tasks(parent_task_id);
    CREATE INDEX tasks_origin_request ON tasks(origin_request_id);
    CREATE TABLE task_links (
        parent_id   TEXT NOT NULL REFERENCES tasks(id) DEFERRABLE INITIALLY DEFERRED,
        child_id    TEXT NOT NULL REFERENCES tasks(id) DEFERRABLE INITIALLY DEFERRED,
        subtask_key TEXT,
        PRIMARY KEY (parent_id, child_id)
    );
    CREATE TABLE task_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL, ts TEXT NOT NULL,
        from_status TEXT, to_status TEXT NOT NULL, actor TEXT
    );
    CREATE TABLE audit (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, event TEXT, router_id TEXT,
        row TEXT NOT NULL                          -- the JSON line, verbatim
    );
    CREATE INDEX audit_event ON audit(event, ts);
    CREATE TABLE continuity (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        data TEXT NOT NULL,                        -- the JSON document, verbatim
        updated_at TEXT NOT NULL
    );
    CREATE TABLE delegation_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        mandate TEXT NOT NULL,
        stream TEXT NOT NULL CHECK (stream IN ('events', 'shadow')),
        ts TEXT,
        row TEXT NOT NULL                          -- the JSON line, verbatim
    );
    CREATE INDEX delegation_events_mandate ON delegation_events(mandate, stream, seq);
    """,
    # v2: what the cutover needs to give files back exactly
    """
    ALTER TABLE tasks ADD COLUMN source_name TEXT;   -- the file it came from, for a rollback
    CREATE TABLE subtask_plans (
        parent_id TEXT PRIMARY KEY,
        plan      TEXT NOT NULL                    -- the declared children, JSON verbatim
    );
    CREATE TABLE cancellation_requests (
        task_id      TEXT PRIMARY KEY,
        requested_at TEXT NOT NULL
    );
    CREATE TABLE delegation_streams (              -- a stream exists even when it is empty
        mandate TEXT NOT NULL,
        stream  TEXT NOT NULL CHECK (stream IN ('events', 'shadow')),
        PRIMARY KEY (mandate, stream)
    );
    """,
    # v3: an empty audit file is still a file; rollback must bring it back
    """
    CREATE TABLE audit_source (                    -- the audit file existed, even with no lines
        id INTEGER PRIMARY KEY CHECK (id = 1)
    );
    """,
    # v4: the console projection lives in the base
    """
    CREATE VIEW console_tasks AS
    SELECT id,
           CASE status WHEN 'draft' THEN 'drafts' ELSE status END AS state,
           title, created AS created_at, COALESCE(updated, created) AS timestamp,
           provider, origin_channel AS origin, origin_thread_id,
           recurring, log_path
    FROM tasks
    WHERE status IN ('draft', 'queued', 'active', 'error', 'completed', 'cancelled');
    CREATE VIEW console_task_counts AS
    SELECT state, COUNT(*) AS n, COALESCE(SUM(recurring), 0) AS recurring
    FROM console_tasks GROUP BY state;
    CREATE VIEW console_audit AS
    SELECT seq, ts, event, router_id,
           json_extract(row, '$.status') AS status,
           json_extract(row, '$.provider') AS provider,
           json_extract(row, '$.request_id') AS request_id,
           json_extract(row, '$.user_id') AS user_id,
           json_extract(row, '$.duration_ms') AS duration_ms,
           json_extract(row, '$.channel') AS channel
    FROM audit;
    """,
    # v5: an approved task can be returned to draft. The table is seeded once, by v1,
    # and every gate reads the table: without this row an existing base would refuse it.
    # Idempotent, and it never touches `tasks`.
    """
    INSERT OR IGNORE INTO transitions (from_status, to_status) VALUES ('queued', 'draft')
    """,
    # v6: execution reservations. One policy row (applied configuration, initial capacity 1),
    # one reservation per active task with its execution token and lease, what each reservation
    # holds (scopes, resources), the provenance of a derived authorization, and the clock of an
    # exclusive task that waits for the others to drain. No row of `tasks` is touched.
    """
    CREATE TABLE async_policy (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        revision INTEGER NOT NULL,
        global_capacity INTEGER NOT NULL CHECK (global_capacity BETWEEN 1 AND 5),
        provider_capacity TEXT NOT NULL,
        exclusive_wait_seconds INTEGER NOT NULL CHECK (exclusive_wait_seconds >= 1),
        enabled_reader_profiles TEXT NOT NULL,
        applied_at TEXT NOT NULL,
        applied_by TEXT,
        proposal_digest TEXT
    );
    INSERT INTO async_policy (id, revision, global_capacity, provider_capacity,
                              exclusive_wait_seconds, enabled_reader_profiles, applied_at, applied_by)
    VALUES (1, 0, 1, '{}', 60, '[]', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), 'migration');
    CREATE TABLE execution_reservations (
        token TEXT PRIMARY KEY,
        task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
        worker TEXT,
        provider TEXT NOT NULL DEFAULT '',
        access_class TEXT NOT NULL CHECK (access_class IN ('exclusive', 'declared')),
        policy_revision INTEGER NOT NULL,
        handoff INTEGER NOT NULL DEFAULT 0,
        claimed_at TEXT NOT NULL,
        heartbeat_at TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL,
        owner_pid INTEGER,
        owner_started TEXT
    );
    CREATE TABLE reservation_scopes (
        token TEXT NOT NULL REFERENCES execution_reservations(token) ON DELETE CASCADE ON UPDATE CASCADE,
        path TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('read', 'write')),
        PRIMARY KEY (token, path, mode)
    );
    CREATE TABLE reservation_resources (
        token TEXT NOT NULL REFERENCES execution_reservations(token) ON DELETE CASCADE ON UPDATE CASCADE,
        name TEXT NOT NULL,
        PRIMARY KEY (token, name)
    );
    CREATE TABLE task_authorizations (
        task_id TEXT PRIMARY KEY REFERENCES tasks(id),
        kind TEXT NOT NULL CHECK (kind IN ('derived')),
        parent_id TEXT NOT NULL,
        parent_digest TEXT NOT NULL,
        manifest_digest TEXT NOT NULL,
        child_key TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE (parent_id, child_key)
    );
    CREATE TABLE claim_waits (
        task_id TEXT PRIMARY KEY,
        first_blocked_at TEXT NOT NULL,
        reason TEXT,
        drain_started_at TEXT
    )
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


class StateError(Exception):
    """Base for refusals the caller should show, not crash on."""


class StateUnavailable(StateError):
    """Wrong format, missing base or other schema: this runtime is not on solar-state."""


class StateBusy(StateError):
    """The lock was not granted in time (a cutover is running)."""


class TransitionRefused(StateError):
    """The task is not where the caller expected, or the move is not allowed."""


class TaskChanged(StateError):
    """The task changed after the caller read it (optimistic lock on `row_version`)."""


class FormatError(StateError):
    """A task document that does not follow the frontmatter contract."""


class StaleToken(TransitionRefused):
    """The execution token is missing or is not the one of the current reservation."""


class PolicyInvalid(StateError):
    """A proposed execution policy is refused; the applied one stays."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _root(root: Optional[os.PathLike[str] | str]) -> Path:
    return Path(root) if root is not None else solar_runtime.runtime_root()


def db_path(root=None) -> Path:
    return _root(root) / DB_NAME


def format_path(root=None) -> Path:
    return _root(root) / FORMAT_NAME


def read_format(root=None) -> Optional[str]:
    try:
        return format_path(root).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _unique_sibling(path: Path, label: str) -> Path:
    stamp = _stamp()
    candidate = path.with_name(f"{path.name}.{label}-{stamp}")
    n = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{label}-{stamp}-{n}")
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

def _lock_wait(handle, exclusive: bool, timeout: float) -> None:
    if fcntl is None:
        return
    mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(handle.fileno(), mode)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                kind = "exclusive" if exclusive else "shared"
                raise StateBusy(f"{kind} state lock not granted in {timeout:g}s "
                                "(a cutover may be running)") from None
            time.sleep(0.02)


@contextmanager
def _flock(root: Path, exclusive: bool, timeout: float) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / LOCK_NAME, "a+", encoding="utf-8")
    try:
        _lock_wait(handle, exclusive, timeout)
        yield
    finally:
        handle.close()  # closing releases the flock


@contextmanager
def _flock_existing(root: Path, timeout: float) -> Iterator[None]:
    """Shared lock on the state.lock that is already there. Never creates it."""
    lock = root / LOCK_NAME
    if not lock.is_file():
        raise StateUnavailable("state.lock is missing")
    try:
        handle = open(lock, "r", encoding="utf-8")
    except OSError as exc:
        raise StateUnavailable(f"state.lock is missing ({exc})") from None
    try:
        _lock_wait(handle, exclusive=False, timeout=timeout)
        yield
    finally:
        handle.close()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    """Read the base without creating a journal, a wal, or a backup.

    A checkpointed base has no wal file. Opening that with immutable=1 does
    not create one. When a writer has left a wal, the read uses it and does
    not add a new file. The shared state.lock is what keeps a cutover out.

    A writer that already holds the shared lock can create the wal after this
    existence check and before SQLite opens the file. The read then keeps an
    immutable contract on a file that is no longer immutable. That window is
    accepted: SQLite returns an error or a stale snapshot and does not write
    the base. The next read sees the wal and opens it read-only. A cutover
    cannot start while this lock is held.
    """
    wal = path.with_name(path.name + "-wal")
    shm = path.with_name(path.name + "-shm")
    flag = "mode=ro" if wal.exists() or shm.exists() else "mode=ro&immutable=1"
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?{flag}", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _open_readonly(base: Path) -> Session:
    path = db_path(base)
    if not path.is_file():
        raise StateUnavailable(f"{path} is missing although the format says sqlite")
    conn = _connect_readonly(path)
    try:
        version = _schema_version(conn)
        if version != SCHEMA_VERSION:
            raise StateUnavailable(
                f"state schema v{version}, this code speaks v{SCHEMA_VERSION}: "
                "the schema migration has not run")
        return Session(conn, base)
    except Exception:
        conn.close()
        raise


# ---------------------------------------------------------------------------
# Workspace owner. The path is not the identity. claim_owner never opens
# .solar/settings.json: Solar Client persists the id there.
# ---------------------------------------------------------------------------

def owner_path(root=None) -> Path:
    return _root(root) / OWNER_NAME


def _path_exists(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return Path(text).exists()


def _same_path(left: str, right: str) -> bool:
    if not str(left or "").strip() or not str(right or "").strip():
        return False
    try:
        return solar_runtime.canonical(left) == solar_runtime.canonical(right)
    except OSError:
        return False


def _read_owner_file(root: Path) -> Optional[dict]:
    path = root / OWNER_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateUnavailable(f"workspace owner file is unreadable: {exc}") from None
    if not isinstance(data, dict) or not str(data.get("workspace_id") or "").strip():
        raise StateUnavailable(f"workspace owner file has no workspace_id: {path}")
    return data


def _write_owner_file(root: Path, workspace_id: str, path: str) -> None:
    payload = {
        "workspace_id": workspace_id,
        "path": path,
        "claimed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    root.mkdir(parents=True, exist_ok=True)
    dest = root / OWNER_NAME
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)


def _owner_refusal(owner_id: str, owner_path_s: str) -> StateUnavailable:
    return StateUnavailable(
        f"this runtime belongs to workspace {owner_id} at {owner_path_s}")


def claim_owner(workspace, workspace_id: Optional[str] = None, *, rebind: bool = False,
                root=None, timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """Create or adopt the owner file. Does not read or write settings.json."""
    base = _root(root)
    caller = str(solar_runtime.canonical(workspace))
    supplied = str(workspace_id or "").strip() or None
    with _flock(base, exclusive=True, timeout=timeout):
        current = _read_owner_file(base)
        if current is None:
            new_id = supplied or str(uuid.uuid4())
            _write_owner_file(base, new_id, caller)
            return dict(action="created", workspace_id=new_id, path=caller)
        owner_id = str(current["workspace_id"])
        owner_path_s = str(current.get("path") or "")
        if supplied and supplied != owner_id:
            raise _owner_refusal(owner_id, owner_path_s)
        if _same_path(owner_path_s, caller):
            return dict(action="unchanged", workspace_id=owner_id, path=owner_path_s)
        if not _path_exists(owner_path_s):
            if supplied != owner_id:
                raise StateUnavailable(
                    "the recorded workspace path is gone; pass its workspace_id to rebind")
            _write_owner_file(base, owner_id, caller)
            return dict(action="rebound", workspace_id=owner_id, path=caller,
                        previous_path=owner_path_s)
        if rebind and supplied == owner_id:
            _write_owner_file(base, owner_id, caller)
            return dict(action="rebound", workspace_id=owner_id, path=caller,
                        previous_path=owner_path_s)
        raise StateUnavailable(
            f"this runtime belongs to {owner_path_s}; {caller} is a copy, not a move")


def owner_record(root=None, timeout: float = DEFAULT_LOCK_TIMEOUT) -> Optional[dict]:
    """The owner file as stored, without checking the caller. Repair reads this."""
    base = _root(root)
    with _flock(base, exclusive=False, timeout=timeout):
        current = _read_owner_file(base)
        return dict(current) if current else None


def replace_owner_id(workspace_id: str, root=None,
                     timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """Point the owner file at another id. Only claim-runtime --keep settings."""
    new_id = str(workspace_id or "").strip()
    if not new_id:
        raise StateUnavailable("replace_owner_id requires a workspace_id")
    base = _root(root)
    with _flock(base, exclusive=True, timeout=timeout):
        current = _read_owner_file(base)
        if current is None:
            raise StateUnavailable("this runtime has no workspace owner")
        path = str(current.get("path") or "")
        _write_owner_file(base, new_id, path)
        return dict(action="id-replaced", workspace_id=new_id, path=path)


def _caller_workspace() -> tuple[str, str]:
    raw = os.environ.get("SOLAR_WORKSPACE", "").strip()
    if not raw:
        raise StateUnavailable(
            "SOLAR_WORKSPACE is not set; this runtime will not serve an unknown workspace")
    workspace = solar_runtime.canonical(raw)
    settings = workspace / ".solar" / "settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateUnavailable(f"cannot read workspace_id from {settings}: {exc}") from None
    if not isinstance(data, dict):
        raise StateUnavailable(f"cannot read workspace_id from {settings}")
    workspace_id = str(data.get("workspace_id") or "").strip()
    if not workspace_id:
        raise StateUnavailable(f"no workspace_id in {settings}")
    return workspace_id, str(workspace)


def _require_owner(base: Path) -> None:
    caller_id, caller_path = _caller_workspace()
    current = _read_owner_file(base)
    if current is None:
        raise StateUnavailable("this runtime has no workspace owner")
    owner_id = str(current["workspace_id"])
    owner_path_s = str(current.get("path") or "")
    if caller_id != owner_id or not _same_path(owner_path_s, caller_path):
        raise _owner_refusal(owner_id, owner_path_s)


# ---------------------------------------------------------------------------
# Connection and schema
# ---------------------------------------------------------------------------

def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def schema_dump(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    return [(r[0], r[1]) for r in rows]


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise StateError(f"refused by the base: {exc}") from None
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

def backup_dir(root=None, kind: str = "daily") -> Path:
    return _root(root) / BACKUP_DIR / kind


def _backup_to(conn: sqlite3.Connection, folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / name
    tmp = folder / f".{name}.partial"
    dest = sqlite3.connect(str(tmp))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    os.replace(tmp, final)
    return final


def _rotate(folder: Path, keep: int) -> None:
    copies = sorted(folder.glob("state-*.sqlite"))
    for old in copies[:-keep] if len(copies) > keep else []:
        old.unlink(missing_ok=True)


def backup_now(conn: sqlite3.Connection, root=None, kind: str = "daily") -> Path:
    path = _backup_to(conn, backup_dir(root, kind), f"state-{_stamp()}.sqlite")
    if kind == "daily":
        _rotate(path.parent, DAILY_KEEP)
    return path


def backup_if_due(conn: sqlite3.Connection, root=None,
                  max_age: float = DAILY_MAX_AGE_SEC) -> Optional[Path]:
    """Daily copy that does not depend on the orchestrator tick being alive."""
    folder = backup_dir(root, "daily")
    newest = max((p.stat().st_mtime for p in folder.glob("state-*.sqlite")), default=0.0)
    if time.time() - newest < max_age:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ".lock", "a+", encoding="utf-8") as guard:
        if fcntl is not None:
            try:
                fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return None  # another process is taking today's copy
        newest = max((p.stat().st_mtime for p in folder.glob("state-*.sqlite")), default=0.0)
        if time.time() - newest < max_age:
            return None
        return backup_now(conn, root, "daily")


def inspect_backup(path: os.PathLike[str] | str) -> dict:
    """Open a copy read-only and say what is in it: the restore check."""
    conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        counts = {row[0]: row[1] for row in
                  conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")}
        return dict(
            schema_version=_schema_version(conn),
            integrity=conn.execute("PRAGMA integrity_check").fetchone()[0],
            tasks=counts,
            audit=conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Frontmatter contract
# ---------------------------------------------------------------------------

_KEY_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")


def parse_task_document(text: str) -> tuple[list[list[str]], str]:
    """Split `---\\nkey: value\\n---\\nbody` into ordered pairs and body.

    Each pair keeps the text after the colon verbatim, leading space included,
    so `render_task_document` gives back the same bytes. A line that does not
    start a key continues the previous value (YAML lists, folded text).
    """
    if not text.startswith("---\n"):
        raise FormatError("task document does not start with a frontmatter block")
    end = text.find("\n---\n", 3)
    if end == -1:
        # A closing `---` with nothing after it would come back with a newline
        # added: refuse it rather than break the byte-for-byte promise.
        raise FormatError("frontmatter block is not closed by a '---' line ending in a newline")
    pairs: list[list[str]] = []
    body = text[end + 5:]
    if end == 3:          # `---\n---\n`: an empty block, the only empty form
        return pairs, body
    for line in text[4:end].split("\n"):
        match = _KEY_LINE.match(line)
        if match:
            pairs.append([match.group(1), match.group(2)])
        elif pairs:
            pairs[-1][1] += "\n" + line
        else:
            raise FormatError(f"frontmatter line before any key: {line!r}")
    return pairs, body


def render_task_document(pairs: Iterable[Iterable[str]], body: str) -> str:
    lines = "".join(f"{key}:{rest}\n" for key, rest in pairs)
    return f"---\n{lines}---\n{body}"


def value_of(rest: Optional[str]) -> Optional[str]:
    """The value a reader means: trimmed, outer quotes removed."""
    if rest is None:
        return None
    value = rest.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return inner
        return inner
    return value


_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _check_field(key: str, value: str) -> None:
    """What task_create and task_set accept is what parse_task_document reads back.
    Multi-line values only come in through task_import, verbatim."""
    if not isinstance(key, str) or not _KEY.match(key):
        raise FormatError(f"frontmatter key {key!r} is not a valid key")
    if "\n" in value or "\r" in value:
        raise FormatError(f"value for {key!r} spans lines; import the document instead")


def _strip_execution_error(body: str) -> str:
    """Drop `## Execution Error` and everything after it.

    Same cut `requeue_from_error.sh` makes, so the next execution reads the
    prompt and not the failure it is being asked to run again.
    """
    lines = body.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.rstrip("\r\n") == "## Execution Error":
            return "".join(lines[:index])
    return body


def _check_id(task_id: str) -> str:
    """A task id ends up as a file name on the way out: no separators, no dots
    that climb, nothing empty."""
    if (not task_id or task_id in (".", "..") or any(c in task_id for c in "/\\")
            or any(ord(c) < 32 or ord(c) == 127 for c in task_id)):
        raise FormatError(f"task id {task_id!r} cannot be a file name")
    return task_id


def _check_unique(pairs: list[list[str]]) -> None:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise FormatError(f"frontmatter key {key!r} appears twice")
        seen.add(key)


def _get_pair(pairs: list[list[str]], key: str) -> Optional[str]:
    for k, rest in pairs:
        if k == key:
            return rest
    return None


def _set_pair(pairs: list[list[str]], key: str, rest: str) -> None:
    for pair in pairs:
        if pair[0] == key:
            pair[1] = rest
            return
    pairs.append([key, rest])


def _drop_pair(pairs: list[list[str]], key: str) -> None:
    pairs[:] = [pair for pair in pairs if pair[0] != key]


def _field(pairs: list[list[str]], key: str) -> Optional[str]:
    return value_of(_get_pair(pairs, key))


def _csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _epoch(text: str) -> float:
    """UTC instant of an ISO-8601 stamp. Unparseable stamps count as the epoch."""
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def _clock_minutes(stamp: str) -> Optional[int]:
    parts = stamp.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def scheduled_now(scheduled_time: Optional[str], weekdays: Optional[str],
                  now: datetime, timezone_name: Optional[str] = None) -> bool:
    """Whether a task may start at `now`. Same window the queue used on files.

    No schedule means always. `scheduled_time: now` means always. A weekday
    list uses ISO days (Monday is 1). A clock time is ready within fifteen
    minutes, wrapping midnight.

    `timezone_name` is an IANA zone (`Europe/Madrid`). When set, weekday and
    clock are read in that zone, so a wall-clock schedule keeps its local hour
    across daylight-saving changes. An unknown zone never matches: the task
    waits instead of running at a guessed hour. Without it, host local time.
    """
    zone_name = (timezone_name or "").strip()
    if zone_name:
        try:
            now = now.astimezone(ZoneInfo(zone_name))
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return False
    moment = (scheduled_time or "").strip()
    days = (weekdays or "").strip()
    if not moment and not days:
        return True
    if moment == "now":
        return True
    if days:
        allowed = {part.strip() for part in days.split(",") if part.strip()}
        if str(now.isoweekday()) not in allowed:
            return False
    if not moment:
        return True
    scheduled = _clock_minutes(moment)
    if scheduled is None:
        return False
    current = now.hour * 60 + now.minute
    diff = current - scheduled
    if diff > 720:
        diff -= 1440
    elif diff < -720:
        diff += 1440
    return -SCHEDULE_MARGIN_MIN <= diff <= SCHEDULE_MARGIN_MIN


# What a human approves when a task is queued: the instructions and everything
# that decides what runs, where, and when. Runtime bookkeeping (run counters,
# claims, appended results) is deliberately outside it. So is the title: it is a
# label, and renaming a task is not a new approval.
MATERIAL_KEYS = (
    "object", "scope", "effect", "priority", "provider", "planet", "agent",
    "responsibility", "agent_contract", "notify_when", "origin_channel", "origin_chat_id",
    "resources", "cleanup_required", "cleanup_timeout",
    "scheduled_time", "scheduled_weekdays", "scheduled_timezone",
    "recurring", "recurring_min_interval", "recurring_max_runs",
    # What runs when the executor is local: a change here is a different command.
    "executor", "local_command", "local_timeout",
    # Concurrency contract. These five are covered only when a task declares them: a task
    # without them hashes exactly as it did before, so no standing approval changes. Absence
    # means "legacy": the task runs exclusive and unrestricted, as it always did.
    "access_policy", "subtask_policy", "execution_profile",
    "review_input_digest", "review_input_manifest",
)
OPTIONAL_MATERIAL_KEYS = frozenset({
    "access_policy", "subtask_policy", "execution_profile",
    "review_input_digest", "review_input_manifest",
})

# What an approval leaves in the frontmatter. `approved_definition` is the
# snapshot: the definition text exactly as it was approved.
APPROVAL_KEYS = ("approved_digest", "approved_at", "approved_row_version", "approved_definition")
# Where the definition ends and the results begin, kept apart from the approval: it
# survives an approval being withdrawn, so the results stay separate from the instructions
# through any number of edits. The approval's own snapshot is `approved_definition`.
BOUNDARY_KEY = "definition_snapshot"
# A digest written by this contract starts with this. One without it (or none at all)
# was made by the old algorithm (title + raw body) or never made: the claim refuses it.
DIGEST_PREFIX = "v2:"
# Level-2 sections the runtime appends to the body. They are not instructions.
RUNTIME_SECTIONS = ("## Delivery", "## Subtask results", "## Execution Error", "## Result")

# The actor `task_import` records on the first event of an imported task. `_was_imported`
# reads it back: an import brings results in the body that nothing else recorded, so the two
# must agree.
IMPORT_ACTOR = "import"

_LOG = logging.getLogger("solar_state")


def definition_text(body: str, title: Optional[str] = None) -> str:
    """The editable instructions of a task, in one canonical form.

    `_body` in solar-mcp writes `\n# {title}\n\n{instructions}\n`. The `# {title}`
    line is a label, so it is dropped when it is the first line and equals the
    stored title: renaming rewrites it together with the title and leaves the
    definition as it was. Leading blank lines and trailing whitespace are removed.
    """
    text = body.lstrip("\r\n")
    if title:
        first, sep, rest = text.partition("\n")
        if sep and first.rstrip("\r") == f"# {title}":
            text = rest
        elif not sep and first.rstrip("\r") == f"# {title}":
            text = ""
    return text.lstrip("\r\n").rstrip()


def _split_runtime_blocks(text: str) -> tuple[str, str]:
    """(text without runtime blocks, the blocks). A block runs from its heading to the
    next `## ` heading or the end, so a `## Result` the author wrote does not swallow
    what follows it."""
    kept: list[str] = []
    taken: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            skipping = _is_runtime_heading(line)
        (taken if skipping else kept).append(line)
    return "".join(kept), "".join(taken)


def definition_body(body: str, title: Optional[str] = None) -> str:
    """`definition_text` without the sections the runtime appended after a run.

    The fallback when no snapshot was approved. A change that sits only under a
    runtime heading does not ask for a new approval: that is the stated limit of
    this reading, and the reason approval stores a snapshot.
    """
    return definition_text(_split_runtime_blocks(definition_text(body, title))[0])


def _is_runtime_heading(line: str) -> bool:
    return line.rstrip() in RUNTIME_SECTIONS


def _after_snapshot(text: str, snapshot: Optional[str]) -> Optional[str]:
    """What follows the snapshot in `text`, when the runtime wrote all of it.

    The boundary is the snapshot itself, so what follows is generated content when it
    is empty or starts with a runtime heading. From there on everything counts as
    generated, headings of its own included (a result may carry `## Findings`).
    """
    if snapshot is None or not text.startswith(snapshot):
        return None
    rest = text[len(snapshot):]
    if rest[:1] not in ("", "\n"):
        return None
    first = next((line for line in rest.splitlines() if line.strip()), None)
    if first is not None and not _is_runtime_heading(first):
        return None
    return rest


def runtime_tail(body: str, title: Optional[str] = None, snapshot: Optional[str] = None) -> str:
    """What the runtime appended after the definition: results, delivery, errors."""
    text = definition_text(body, title)
    rest = _after_snapshot(text, snapshot)
    if rest is None:
        # No known boundary (an import): keep everything from the first runtime heading on.
        # Keeping too much costs nothing; dropping a result cannot be undone.
        lines = text.splitlines(keepends=True)
        start = next((i for i, line in enumerate(lines) if _is_runtime_heading(line)), len(lines))
        rest = "".join(lines[start:])
    return rest.strip("\n")


def current_definition(body: str, title: Optional[str] = None,
                       snapshot: Optional[str] = None) -> str:
    """The definition a claim compares with the approval.

    With a snapshot the boundary is known: when the body is that text followed by
    nothing but runtime sections, the definition is the snapshot itself. Anything
    else is read as `definition_body`, which then differs from the snapshot.
    """
    if _after_snapshot(definition_text(body, title), snapshot) is not None:
        return snapshot
    return definition_body(body, title)


def material_digest(pairs: list[list[str]], body: str, *, definition: Optional[str] = None) -> str:
    """Digest of the material content of a task at one moment: the material fields and
    the definition. `definition` is given when the caller already holds it (a snapshot);
    otherwise it is read from `body` as it stands."""
    import hashlib
    material = {}
    for key in MATERIAL_KEYS:
        raw = _get_pair(pairs, key)
        if key in OPTIONAL_MATERIAL_KEYS:
            if raw is None:
                continue          # not declared: not part of the snapshot (see MATERIAL_KEYS)
            material[key] = _canonical_material(key, value_of(raw))
        else:
            material[key] = value_of(raw)
    if definition is None:
        definition = definition_text(body, value_of(_get_pair(pairs, "title")))
    payload = json.dumps(dict(fields=material, definition=definition), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return DIGEST_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def current_digest(pairs: list[list[str]], body: str) -> str:
    """Digest of the task as a claim reads it now (snapshot if one was approved)."""
    title = value_of(_get_pair(pairs, "title"))
    snapshot = value_of(_get_pair(pairs, "approved_definition"))
    return material_digest(pairs, body, definition=current_definition(body, title, snapshot))


def task_digest(status: str, pairs: list[list[str]], body: str) -> str:
    """The digest a reader should compare: what approving would record for a task still
    being prepared, what a claim would compute for one that was approved."""
    if status in ("draft", "planned"):
        return material_digest(pairs, body)
    return current_digest(pairs, body)


def approval_state(pairs: list[list[str]], body: str) -> Optional[str]:
    """None when the stored approval covers this content, else why not:
    `absent` (no digest), `legacy` (made by the old algorithm), `mismatch`."""
    stored = value_of(_get_pair(pairs, "approved_digest"))
    if not stored:
        return "absent"
    if not stored.startswith(DIGEST_PREFIX):
        return "legacy"
    return None if stored == current_digest(pairs, body) else "mismatch"


def _definition_head(body: str, title: Optional[str] = None) -> str:
    """The definition up to the first runtime heading: where results begin when nothing
    recorded the boundary (an import, or a task that ran before it was recorded)."""
    lines = definition_text(body, title).splitlines(keepends=True)
    stop = next((i for i, line in enumerate(lines) if _is_runtime_heading(line)), len(lines))
    return definition_text("".join(lines[:stop]))


def _record_boundary(pairs: list[list[str]], body: str) -> Optional[str]:
    """Write the boundary before an approval is withdrawn or recreated, so the results
    already in the body keep their place apart from the instructions. Returns the stored
    value when it wrote one (the caller that moves the task persists it), else None."""
    if _get_pair(pairs, BOUNDARY_KEY) is not None or _get_pair(pairs, "approved_definition") is not None:
        return None
    value = json.dumps(_definition_head(body, value_of(_get_pair(pairs, "title"))))
    _set_pair(pairs, BOUNDARY_KEY, " " + value)
    return value


def _was_imported(conn, task_id: str) -> bool:
    row = conn.execute("SELECT actor FROM task_events WHERE task_id = ? ORDER BY seq LIMIT 1",
                       (task_id,)).fetchone()
    return row is not None and row[0] == IMPORT_ACTOR


def _boundary(pairs: list[list[str]]) -> Optional[str]:
    """The definition text this body is known to begin with, if the system recorded it."""
    for key in (BOUNDARY_KEY, "approved_definition"):
        if _get_pair(pairs, key) is not None:
            return value_of(_get_pair(pairs, key))
    return None


def _has_run(conn, task_id: str) -> bool:
    return conn.execute("SELECT 1 FROM task_events WHERE task_id = ? AND to_status = 'active' "
                        "LIMIT 1", (task_id,)).fetchone() is not None


def _approval_fields(conn, task_id: str, pairs: list[list[str]], body: str,
                     row_version: int) -> dict:
    """What approving writes. The snapshot is the definition as it stands; a task that
    already ran carries runtime sections in its body, which are not part of it."""
    validate_material(pairs)
    title = value_of(_get_pair(pairs, "title"))
    text = definition_text(body, title)
    known = _boundary(pairs)
    if known is not None and _after_snapshot(text, known) is not None:
        snapshot = known                    # the results already in the body are not instructions
    elif _has_run(conn, task_id) or _was_imported(conn, task_id):
        snapshot = _definition_head(body, title)       # what the body already holds is results
    else:
        snapshot = text
    return {
        "approved_digest": json.dumps(material_digest(pairs, body, definition=snapshot)),
        "approved_at": json.dumps(_now()),
        "approved_row_version": str(row_version),
        "approved_definition": json.dumps(snapshot),
        BOUNDARY_KEY: json.dumps(snapshot),
    }


def _audit(conn, event: str, **row) -> None:
    row = dict(event=event, ts=_now(), **row)
    conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?, ?, ?, ?)",
                 (row["ts"], event, None, json.dumps(row, ensure_ascii=True)))


def _approval_gate(conn, task_id: str, row_version: int, pairs: list[list[str]],
                   body: str) -> Optional[str]:
    """The claim's check, inside its transaction. None: the approval covers what is
    stored. Otherwise the reason, recorded once per version of the row in `audit`
    (a worker polls every minute) and logged every time."""
    reason = approval_state(pairs, body)
    if reason is None:
        return None
    _LOG.warning("approval_digest_mismatch task=%s reason=%s row_version=%s",
                 task_id, reason, row_version)
    seen = conn.execute(
        "SELECT 1 FROM audit WHERE event = 'approval_digest_mismatch' "
        "AND json_extract(row, '$.task_id') = ? AND json_extract(row, '$.row_version') = ? "
        "AND json_extract(row, '$.reason') = ? LIMIT 1", (task_id, row_version, reason)).fetchone()
    if not seen:
        _audit(conn, "approval_digest_mismatch", task_id=task_id, reason=reason,
               row_version=row_version)
    return reason


def _recurring_ready(pairs: list[list[str]], now_epoch: float) -> bool:
    if str(_field(pairs, "recurring") or "").lower() != "true":
        return True
    last = _field(pairs, "recurring_last_run")
    if not last:
        return True
    try:
        interval = int(_field(pairs, "recurring_min_interval") or "86400")
    except ValueError:
        interval = 86400
    return now_epoch - _epoch(last) >= interval


def _blocked(conn: sqlite3.Connection, pairs: list[list[str]]) -> bool:
    """True when a named dependency is still running. A missing id is finished."""
    for dep in _csv(_field(pairs, "blocked_by_task_ids")):
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (dep,)).fetchone()
        if row is not None and row[0] not in TERMINAL_STATUSES:
            return True
    return False


def _move(conn: sqlite3.Connection, task_id: str, to_status: str, actor: Optional[str],
          *, rewrite_body: Optional[Callable[[str], str]] = None,
          fields: Optional[dict] = None, drop: Iterable[str] = (),
          extra: Optional[dict] = None, handoff: bool = False) -> str:
    """One allowed transition. The caller already holds the transaction.

    Becoming active takes a reservation (and is refused when it does not fit); leaving
    `active` gives it back. No path changes the status around this."""
    row = conn.execute("SELECT status, frontmatter, body FROM tasks WHERE id = ?",
                       (task_id,)).fetchone()
    if row is None:
        raise TransitionRefused(f"no task {task_id}")
    current = row["status"]
    if not conn.execute("SELECT 1 FROM transitions WHERE from_status = ? AND to_status = ?",
                        (current, to_status)).fetchone():
        raise TransitionRefused(f"{current} -> {to_status} is not an allowed transition")
    pairs = json.loads(row["frontmatter"])
    body = rewrite_body(row["body"]) if rewrite_body is not None else row["body"]
    for key in drop:
        _drop_pair(pairs, key)
    for key, value in (fields or {}).items():
        _check_field(key, str(value))
        _set_pair(pairs, key, f" {value}" if value != "" else "")
    _set_pair(pairs, "status", f" {to_status}")
    if to_status == "active" and current != "active":
        _reserve(conn, task_id, pairs, (extra or {}).get("claimed_by") or actor, handoff=handoff)
    elif current == "active" and to_status != "active":
        conn.execute("DELETE FROM execution_reservations WHERE task_id = ?", (task_id,))
    _write_task(conn, task_id, to_status, pairs, body, insert=False, extra=extra)
    conn.execute("INSERT INTO task_events (task_id, ts, from_status, to_status, actor) "
                 "VALUES (?, ?, ?, ?, ?)", (task_id, _now(), current, to_status, actor))
    return current


def _check_version(task_id: str, current: int, expected: Optional[int]) -> None:
    if expected is not None and current != expected:
        raise TaskChanged(f"{task_id} changed (row_version {current}, caller read {expected}); read it again")


def _projection(pairs: list[list[str]]) -> dict[str, Any]:
    cols: dict[str, Any] = {key: value_of(_get_pair(pairs, key)) for key in COLUMN_KEYS}
    cols["recurring"] = 1 if str(cols["recurring"] or "").lower() == "true" else 0
    return cols


def _write_task(conn, task_id: str, status: str, pairs, body: str, *, insert: bool,
                extra: Optional[dict] = None, imported: Optional[dict] = None) -> None:
    cols = _projection(pairs)
    for name, value in (extra or {}).items():
        if name not in TRANSITION_COLUMNS:
            raise StateError(f"{name} is not a column a transition may set")
        cols[name] = value
    for name, value in (imported or {}).items():
        if name not in IMPORT_COLUMNS:
            raise StateError(f"{name} is not a column an import may set")
        cols[name] = value
    cols["status"] = status
    cols["frontmatter"] = json.dumps(pairs, ensure_ascii=False)
    cols["body"] = body
    if insert:
        cols["id"] = task_id
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        conn.execute(f"INSERT INTO tasks ({names}) VALUES ({marks})", list(cols.values()))
    else:
        sets = ", ".join(f"{name} = ?" for name in cols)
        conn.execute(f"UPDATE tasks SET {sets}, row_version = row_version + 1 WHERE id = ?",
                     [*cols.values(), task_id])


def _register_stream(conn, mandate: str, stream: str) -> None:
    conn.execute("INSERT OR IGNORE INTO delegation_streams (mandate, stream) VALUES (?, ?)",
                 (mandate, stream))


def _task_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["frontmatter"] = json.loads(data["frontmatter"])
    return data


# ---------------------------------------------------------------------------
# Concurrency contract: access declarations, execution policy, reservations
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ACCESS_MODES = ("read", "write")
_ACCESS_KEYS = frozenset({"version", "mode", "scopes", "resources"})
_SUBTASK_KEYS = frozenset({"version", "max_children", "providers", "templates", "object",
                           "scope", "effect", "max_access"})
_TEMPLATE_KEYS = frozenset({"key", "title", "instructions", "inputs"})
_POLICY_KEYS = frozenset({"schema_version", "revision", "global_capacity", "provider_capacity",
                          "exclusive_wait_seconds", "enabled_reader_profiles"})
POLICY_SCHEMA_VERSION = 1
SUBTASK_MAX_CHILDREN = 5


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _load_json_object(raw: Any, what: str) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise FormatError(f"{what} must be a JSON object")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise FormatError(f"{what} is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise FormatError(f"{what} must be a JSON object")
    return value


def _closed(value: dict, allowed: frozenset, what: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise FormatError(f"{what} has unknown keys: {', '.join(extra)}")


def _slug_list(value: Any, what: str, *, maximum: int, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise FormatError(f"{what} must be a list of {minimum} to {maximum} names")
    for item in value:
        if not isinstance(item, str) or not _SLUG_RE.match(item):
            raise FormatError(f"{what}: {item!r} is not a valid name")
    return sorted(set(value))


def parse_access_policy(raw: Any) -> Optional[dict]:
    """The access a task declares, validated and in canonical form.

    None: nothing declared. That is the legacy task, and it runs exclusive. A value that
    is declared and wrong raises `FormatError`: it is never read as "no access" or as a
    reader. Scopes are absolute paths, normalized lexically (symlinks are resolved again
    at claim time, so an alias made later is still the same scope).
    """
    if raw is None:
        return None
    data = _load_json_object(raw, "access_policy")
    _closed(data, _ACCESS_KEYS, "access_policy")
    if data.get("version") != 1 or not _is_int(data.get("version")):
        raise FormatError("access_policy.version must be 1")
    mode = data.get("mode")
    if mode not in ACCESS_MODES:
        raise FormatError(f"access_policy.mode must be one of {', '.join(ACCESS_MODES)}")
    scopes = data.get("scopes", [])
    if not isinstance(scopes, list) or len(scopes) > 32:
        raise FormatError("access_policy.scopes must be a list of at most 32 paths")
    clean = set()
    for item in scopes:
        if not isinstance(item, str) or not item.startswith("/") or "\x00" in item:
            raise FormatError(f"access_policy scope {item!r} must be an absolute path")
        clean.add(posixpath.normpath(item))
    if mode == "write" and not clean:
        raise FormatError("access_policy: a writer must name at least one scope")
    resources = _slug_list(data.get("resources", []), "access_policy.resources", maximum=32)
    return dict(version=1, mode=mode, scopes=sorted(clean), resources=resources)


def parse_subtask_policy(raw: Any) -> Optional[dict]:
    """The bounded subtask policy a parent's approval carries, in canonical form.

    None when not declared: a parent without it authorizes no new children. A worker
    that materializes children enforces it; this function only fixes its shape."""
    if raw is None:
        return None
    data = _load_json_object(raw, "subtask_policy")
    _closed(data, _SUBTASK_KEYS, "subtask_policy")
    if data.get("version") != 1 or not _is_int(data.get("version")):
        raise FormatError("subtask_policy.version must be 1")
    count = data.get("max_children")
    if not _is_int(count) or not 1 <= count <= SUBTASK_MAX_CHILDREN:
        raise FormatError(f"subtask_policy.max_children must be 1 to {SUBTASK_MAX_CHILDREN}")
    providers = _slug_list(data.get("providers"), "subtask_policy.providers", maximum=8, minimum=1)
    templates = data.get("templates")
    if not isinstance(templates, list) or not 1 <= len(templates) <= count:
        raise FormatError("subtask_policy.templates must list 1 to max_children templates")
    seen: set[str] = set()
    cleaned = []
    for template in templates:
        if not isinstance(template, dict):
            raise FormatError("subtask_policy.templates entries must be objects")
        _closed(template, _TEMPLATE_KEYS, "subtask_policy template")
        key = template.get("key")
        if not isinstance(key, str) or not _SLUG_RE.match(key) or key in seen:
            raise FormatError(f"subtask_policy template key {key!r} is invalid or repeated")
        seen.add(key)
        for name in ("title", "instructions"):
            if not isinstance(template.get(name), str) or not template[name].strip():
                raise FormatError(f"subtask_policy template {key}: {name} is required")
        inputs = template.get("inputs", [])
        if (not isinstance(inputs, list) or len(inputs) > 32
                or any(not isinstance(i, str) or not _HEX64_RE.match(i) for i in inputs)):
            raise FormatError(f"subtask_policy template {key}: inputs are sha256 digests")
        cleaned.append(dict(key=key, title=template["title"], instructions=template["instructions"],
                            inputs=sorted(set(inputs))))
    scope = {}
    for name in ("object", "scope", "effect"):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise FormatError(f"subtask_policy.{name} is required (at most 500 characters)")
        scope[name] = value
    access = parse_access_policy(data.get("max_access"))
    if access is None:
        raise FormatError("subtask_policy.max_access is required")
    return dict(version=1, max_children=count, providers=providers,
                templates=sorted(cleaned, key=lambda t: t["key"]), max_access=access, **scope)


def canonical_policy_text(key: str, raw: Any) -> str:
    """The one stored spelling of `access_policy` / `subtask_policy` (raises when invalid)."""
    parser = parse_access_policy if key == "access_policy" else parse_subtask_policy
    parsed = parser(raw)
    if parsed is None:
        raise FormatError(f"{key} is empty")
    return _canonical_json(parsed)


def _canonical_material(key: str, value: Optional[str]) -> Optional[str]:
    """What the digest holds for an optional key: the policies in canonical JSON. A value
    that does not validate is hashed as written; approval and claim refuse it separately."""
    if key in ("access_policy", "subtask_policy") and value is not None:
        try:
            return canonical_policy_text(key, value)
        except FormatError:
            return value
    return value


def validate_material(pairs: list[list[str]]) -> None:
    """Refuse an approval whose new material keys do not validate."""
    for key in ("access_policy", "subtask_policy"):
        raw = _get_pair(pairs, key)
        if raw is not None:
            canonical_policy_text(key, value_of(raw))
    profile = _get_pair(pairs, "execution_profile")
    if profile is not None and not _SLUG_RE.match(value_of(profile) or ""):
        raise FormatError("execution_profile must be a profile name")
    digest = _get_pair(pairs, "review_input_digest")
    if digest is not None and not _HEX64_RE.match(value_of(digest) or ""):
        raise FormatError("review_input_digest must be a sha256 digest")
    manifest = _get_pair(pairs, "review_input_manifest")
    if manifest is not None and not (value_of(manifest) or "").strip():
        raise FormatError("review_input_manifest must reference the manifest")


# -- execution policy (the applied configuration) ---------------------------------

def config_path(root=None) -> Path:
    """The readable proposal. Editing it activates nothing: only an applied revision counts."""
    return _root(root) / "async-tasks" / "config" / "async-execution.json"


def validate_policy_document(doc: Any, current_revision: int) -> dict:
    """A proposal, checked in full and returned in canonical form. Raises `PolicyInvalid`."""
    if not isinstance(doc, dict):
        raise PolicyInvalid("the configuration must be a JSON object")
    extra = sorted(set(doc) - _POLICY_KEYS)
    if extra:
        raise PolicyInvalid(f"unknown keys: {', '.join(extra)}")
    if doc.get("schema_version") != POLICY_SCHEMA_VERSION or not _is_int(doc.get("schema_version")):
        raise PolicyInvalid(f"schema_version must be {POLICY_SCHEMA_VERSION}")
    revision = doc.get("revision")
    if not _is_int(revision) or revision <= current_revision:
        raise PolicyInvalid(f"revision must be an integer above the applied revision {current_revision}")
    cap = doc.get("global_capacity")
    if not _is_int(cap) or not 1 <= cap <= CAPACITY_MAX:
        raise PolicyInvalid(f"global_capacity must be an integer from 1 to {CAPACITY_MAX}")
    providers = doc.get("provider_capacity", {})
    if not isinstance(providers, dict):
        raise PolicyInvalid("provider_capacity must map a provider to a positive integer")
    for name, limit in providers.items():
        if not isinstance(name, str) or not _SLUG_RE.match(name):
            raise PolicyInvalid(f"provider_capacity: {name!r} is not a provider name")
        if not _is_int(limit) or not 1 <= limit <= CAPACITY_MAX:
            raise PolicyInvalid(f"provider_capacity.{name} must be an integer from 1 to {CAPACITY_MAX}")
    wait = doc.get("exclusive_wait_seconds", 60)
    if not _is_int(wait) or not 1 <= wait <= 86400:
        raise PolicyInvalid("exclusive_wait_seconds must be an integer from 1 to 86400")
    try:
        profiles = _slug_list(doc.get("enabled_reader_profiles", []), "enabled_reader_profiles",
                              maximum=16)
    except FormatError as exc:
        raise PolicyInvalid(str(exc)) from None
    return dict(schema_version=POLICY_SCHEMA_VERSION, revision=revision, global_capacity=cap,
                provider_capacity={k: providers[k] for k in sorted(providers)},
                exclusive_wait_seconds=wait, enabled_reader_profiles=profiles)


def policy_digest(doc: dict) -> str:
    """sha256 of the canonical document: what an approval of an apply is bound to."""
    return hashlib.sha256(_canonical_json(doc).encode("utf-8")).hexdigest()


def read_proposal(root=None) -> dict:
    """The proposal file as found: `{present, document, error}`. Never raises."""
    path = config_path(root)
    if not path.is_file():
        return dict(present=False, document=None, error=None, path=str(path))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return dict(present=True, document=None, error=f"unreadable: {exc}", path=str(path))
    return dict(present=True, document=document, error=None, path=str(path))


def write_proposal(document: dict, root=None) -> Path:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _policy_row(conn) -> dict:
    row = conn.execute("SELECT * FROM async_policy WHERE id = 1").fetchone()
    if row is None:
        raise StateUnavailable("the execution policy row is missing: the schema migration is incomplete")
    data = dict(row)
    data["provider_capacity"] = json.loads(data["provider_capacity"])
    data["enabled_reader_profiles"] = json.loads(data["enabled_reader_profiles"])
    return data


# -- maintenance barrier ------------------------------------------------------------

def maintenance_path(root=None) -> Path:
    return _root(root) / MAINTENANCE_NAME


def maintenance_state(root=None) -> Optional[dict]:
    """The barrier an update holds, or None. It lives outside the schema, under the control
    of the client. An unreadable file counts as a barrier: claims fail closed."""
    path = maintenance_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(unreadable=True)
    return data if isinstance(data, dict) else dict(unreadable=True)


# -- what a task asks for, what the others hold --------------------------------------

class _Access:
    """A task's claim on the machine: exclusive, or declared scopes and resources."""

    def __init__(self, *, exclusive: bool, scopes=(), resources=(), provider: str = "",
                 invalid: Optional[str] = None, task_id: Optional[str] = None,
                 token: Optional[str] = None):
        self.exclusive = exclusive
        self.scopes = list(scopes)            # [(resolved path, mode)]
        self.resources = frozenset(resources)
        self.provider = provider
        self.invalid = invalid
        self.task_id = task_id
        self.token = token


def _resolve_scope(path: str) -> str:
    return os.path.realpath(path).casefold()


def _overlaps(left: str, right: str) -> bool:
    if left == right:
        return True
    a, b = left.rstrip("/") + "/", right.rstrip("/") + "/"
    return a.startswith(b) or b.startswith(a)


def _access_of(pairs: list[list[str]], task_id: Optional[str] = None) -> _Access:
    provider = (_field(pairs, "provider") or "").strip().lower()
    resources = set(_csv(_field(pairs, "resources")))
    raw = _get_pair(pairs, "access_policy")
    if raw is None:
        return _Access(exclusive=True, resources=resources, provider=provider, task_id=task_id)
    try:
        policy = parse_access_policy(value_of(raw))
    except FormatError as exc:
        return _Access(exclusive=True, resources=resources, provider=provider,
                       invalid=str(exc), task_id=task_id)
    resources |= set(policy["resources"])
    scopes = [(_resolve_scope(path), policy["mode"]) for path in policy["scopes"]]
    return _Access(exclusive=False, scopes=scopes, resources=resources, provider=provider,
                   task_id=task_id)


def _occupancy(conn, ignore_task: Optional[str] = None) -> list[_Access]:
    """Everything that holds a place right now: the reservations, and any active task
    that has none (it predates them), which counts as exclusive."""
    held = []
    for row in conn.execute("SELECT token, task_id, provider, access_class FROM execution_reservations"):
        if row["task_id"] == ignore_task:
            continue
        scopes = [(_resolve_scope(r[0]), r[1]) for r in conn.execute(
            "SELECT path, mode FROM reservation_scopes WHERE token = ?", (row["token"],))]
        resources = [r[0] for r in conn.execute(
            "SELECT name FROM reservation_resources WHERE token = ?", (row["token"],))]
        held.append(_Access(exclusive=row["access_class"] == "exclusive", scopes=scopes,
                            resources=resources, provider=row["provider"],
                            task_id=row["task_id"], token=row["token"]))
    for row in conn.execute("SELECT id, frontmatter FROM tasks WHERE status = 'active' "
                            "AND id NOT IN (SELECT task_id FROM execution_reservations)"):
        if row["id"] != ignore_task:
            held.append(_Access(exclusive=True, task_id=row["id"],
                                provider=(_field(json.loads(row["frontmatter"]), "provider")
                                          or "").strip().lower()))
    return held


def _admission(access: _Access, held: list[_Access], policy: dict) -> Optional[str]:
    """None when the task may start next to what is running, else the reason it waits."""
    if access.exclusive:
        return "exclusive_needs_idle" if held else None
    if any(item.exclusive for item in held):
        return "blocked_by_exclusive"
    if len(held) >= policy["global_capacity"]:
        return "global_capacity"
    limit = policy["provider_capacity"].get(access.provider) if access.provider else None
    if limit is not None and sum(1 for item in held if item.provider == access.provider) >= limit:
        return "provider_capacity"
    for item in held:
        shared = access.resources & item.resources
        if shared:
            return f"resource:{sorted(shared)[0]}"
        for path, mode in access.scopes:
            for other_path, other_mode in item.scopes:
                if (mode == "write" or other_mode == "write") and _overlaps(path, other_path):
                    return "scope_conflict"
    return None


def _lease_expiry(seconds: int = LEASE_SECONDS) -> str:
    return datetime.fromtimestamp(time.time() + seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reserve(conn, task_id: str, pairs: list[list[str]], worker: Optional[str],
             *, handoff: bool = False) -> str:
    """Take the place for a task that is becoming active. Raises when it does not fit:
    every way into `active` is checked here, whoever asked."""
    if maintenance_state(_db_root(conn)) is not None:
        raise TransitionRefused(f"{task_id} cannot start: maintenance is in progress")
    access = _access_of(pairs, task_id)
    if access.invalid:
        raise TransitionRefused(f"{task_id} cannot start: access_policy_invalid ({access.invalid})")
    policy = _policy_row(conn)
    reason = _admission(access, _occupancy(conn, ignore_task=task_id), policy)
    if reason:
        raise TransitionRefused(f"{task_id} cannot start now: {reason}")
    return _reserve_with(conn, task_id, pairs, worker, uuid.uuid4().hex, handoff=handoff,
                         access=access, policy=policy)


def _reserve_with(conn, task_id: str, pairs: list[list[str]], worker: Optional[str], token: str, *,
                  handoff: bool, access: Optional[_Access] = None,
                  policy: Optional[dict] = None) -> str:
    access = access or _access_of(pairs, task_id)
    policy = policy or _policy_row(conn)
    now = _now()
    conn.execute(
        "INSERT INTO execution_reservations (token, task_id, worker, provider, access_class, "
        "policy_revision, handoff, claimed_at, heartbeat_at, lease_expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (token, task_id, worker, access.provider, "exclusive" if access.exclusive else "declared",
         policy["revision"], 1 if handoff else 0, now, now, _lease_expiry()))
    for path, mode in access.scopes:
        conn.execute("INSERT OR IGNORE INTO reservation_scopes (token, path, mode) VALUES (?, ?, ?)",
                     (token, path, mode))
    for name in sorted(access.resources):
        conn.execute("INSERT OR IGNORE INTO reservation_resources (token, name) VALUES (?, ?)",
                     (token, name))
    conn.execute("DELETE FROM claim_waits WHERE task_id = ?", (task_id,))
    return token


def _db_root(conn) -> Path:
    """The runtime directory of the open base (the folder of `state.sqlite`)."""
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            return Path(row[2]).parent
    return solar_runtime.runtime_root()


def _check_token(conn, task_id: str, token: Optional[str]) -> None:
    """The current reservation's token is the only proof of ownership. A task with no
    reservation (active before they existed) needs none."""
    row = conn.execute("SELECT token FROM execution_reservations WHERE task_id = ?",
                       (task_id,)).fetchone()
    if row is None:
        return
    if not token:
        raise StaleToken(f"{task_id} is reserved: its execution token is required")
    if token != row["token"]:
        raise StaleToken(f"{task_id}: that execution token is not the current one")


def _process_identity(pid: int) -> Optional[str]:
    """Start time of a process as `ps` prints it; None when it is not running."""
    import subprocess
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], capture_output=True,
                             text=True, check=False, timeout=10).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return out or None


def _provenance_problem(conn, task_id: str) -> Optional[str]:
    """A derived task needs its parent's authorization to still stand."""
    row = conn.execute("SELECT parent_id FROM task_authorizations WHERE task_id = ?",
                       (task_id,)).fetchone()
    if row is None:
        return None
    parent = conn.execute("SELECT status FROM tasks WHERE id = ?", (row["parent_id"],)).fetchone()
    if parent is None or parent["status"] not in ("queued", "active", "completed"):
        return "parent_revoked"
    if conn.execute("SELECT 1 FROM cancellation_requests WHERE task_id = ?",
                    (row["parent_id"],)).fetchone():
        return "parent_revoked"
    return None


def _claim_order(row) -> tuple:
    return (-_PRIORITY_RANK.get(row["priority"] or "", 0), row["created"] or "", row["id"])


def _eligibility(conn, row, pairs: list[list[str]], moment: datetime, *, manual: bool) -> Optional[str]:
    """Why a queued task cannot be claimed for reasons of its own, or None.

    The worker's selection rules (the recurring interval and the schedule window) are not
    applied when a person starts a task by name (`manual`). Everything else is revalidated
    at every claim, inside its transaction."""
    task_id = row["id"]
    if conn.execute("SELECT 1 FROM cancellation_requests WHERE task_id = ?", (task_id,)).fetchone():
        return "cancellation_requested"
    if _blocked(conn, pairs):
        return "blocked_by_dependency"
    if not manual:
        if not _recurring_ready(pairs, moment.timestamp()):
            return "recurring_interval"
        if not scheduled_now(_field(pairs, "scheduled_time"), _field(pairs, "scheduled_weekdays"),
                             moment, _field(pairs, "scheduled_timezone")):
            return "outside_schedule"
    reason = _approval_gate(conn, task_id, row["row_version"], pairs, row["body"])
    if reason:
        return reason
    problem = _provenance_problem(conn, task_id)
    if problem:
        return problem
    if _access_of(pairs, task_id).invalid:
        return "access_policy_invalid"
    return None


def _drain_target(conn, policy: dict, moment: datetime, exclude: Optional[str] = None) -> Optional[str]:
    """The exclusive task that has waited long enough and now holds the line: from here on
    nothing else starts until the running tasks drain and it does. The first one in claim
    order wins, so priority among exclusives is kept. A task that is not eligible for
    other reasons (dependencies, schedule, approval) never becomes the target."""
    waits = {r["task_id"]: r for r in conn.execute("SELECT * FROM claim_waits")}
    if not waits:
        return None
    now_epoch = moment.timestamp()
    marks = ",".join("?" for _ in waits)
    rows = list(conn.execute(
        f"SELECT id, status, priority, created, frontmatter, body, row_version FROM tasks "
        f"WHERE status = 'queued' AND id IN ({marks})", list(waits)))
    rows.sort(key=_claim_order)
    for row in rows:
        if row["id"] == exclude:
            continue
        if now_epoch - _epoch(waits[row["id"]]["first_blocked_at"]) < policy["exclusive_wait_seconds"]:
            continue
        pairs = json.loads(row["frontmatter"])
        if _access_of(pairs).exclusive and _eligibility(conn, row, pairs, moment, manual=False) is None:
            return row["id"]
    return None


def _note_wait(conn, task_id: str, access: _Access, reason: str, policy: dict, *,
               target: Optional[str], held: Optional[list] = None) -> None:
    """An exclusive task that cannot start starts its clock; once it is the drain target the
    reason is recorded, once, so starvation can be seen."""
    if not access.exclusive:
        return
    conn.execute("INSERT OR IGNORE INTO claim_waits (task_id, first_blocked_at, reason) "
                 "VALUES (?, ?, ?)", (task_id, _now(), reason))
    conn.execute("UPDATE claim_waits SET reason = ? WHERE task_id = ?", (reason, task_id))
    if target == task_id:
        row = conn.execute("SELECT first_blocked_at, drain_started_at FROM claim_waits "
                           "WHERE task_id = ?", (task_id,)).fetchone()
        if row and not row["drain_started_at"]:
            conn.execute("UPDATE claim_waits SET drain_started_at = ? WHERE task_id = ?",
                         (_now(), task_id))
            _audit(conn, "exclusive_drain_started", task_id=task_id,
                   first_blocked_at=row["first_blocked_at"],
                   exclusive_wait_seconds=policy["exclusive_wait_seconds"],
                   holding=sorted(item.task_id for item in (held if held is not None
                                                            else _occupancy(conn)) if item.task_id))


# ---------------------------------------------------------------------------
# Session: the API every component uses
# ---------------------------------------------------------------------------

class Session:
    """One open connection, under the shared lock, with the format checked."""

    def __init__(self, conn: sqlite3.Connection, root: Path):
        self.conn = conn
        self.root = root

    # -- tasks -------------------------------------------------------------

    def task_create(self, fields: Iterable[tuple[str, str]] = (), body: str = "",
                    status: str = "draft", task_id: Optional[str] = None,
                    actor: Optional[str] = None) -> str:
        """Create a task. `fields` are (key, value) in order; values are written
        as `key: value`. Missing `id` and `status` keys are added in front."""
        if status not in CREATE_STATUSES:
            raise TransitionRefused(f"a task is created as {'/'.join(CREATE_STATUSES)}, not {status}")
        fields = list(fields)
        for key, value in fields:
            _check_field(key, value)
        pairs = [[k, f" {v}" if v != "" else ""] for k, v in fields]
        _check_unique(pairs)
        declared = value_of(_get_pair(pairs, "id")) or None   # an empty id is no id
        if task_id and declared and declared != task_id:
            raise StateError(f"task_id {task_id!r} and frontmatter id {declared!r} differ")
        task_id = _check_id(task_id or declared or str(uuid.uuid4()))
        # A declared id is kept as it was written. Only an id this call supplies
        # is written, JSON-encoded, so value_of() reads back exactly task_id.
        if _get_pair(pairs, "id") is None:
            pairs.insert(0, ["id", " " + json.dumps(task_id, ensure_ascii=False)])
        elif not declared:
            _set_pair(pairs, "id", " " + json.dumps(task_id, ensure_ascii=False))
        _set_pair(pairs, "status", f" {status}")
        if status == "queued":
            # Creating a task already queued is the caller's own approval (the queue
            # scripts, and a parent's subtasks). It is recorded like any other, so the
            # claim finds a digest that covers exactly this content.
            for key, value in _approval_fields(self.conn, task_id, pairs, body, 1).items():
                _set_pair(pairs, key, f" {value}")
        self._insert(task_id, status, pairs, body, actor)
        return task_id

    def task_import(self, document: str, status: Optional[str] = None,
                    actor: str = IMPORT_ACTOR, log_path: Optional[str] = None,
                    source_name: Optional[str] = None) -> str:
        """Store a task document exactly as written: the pairs `parse_task_document`
        returns, untouched. Any status is accepted (this is how existing tasks
        enter). `status`, when given, wins over the frontmatter one and is written
        back into it — the folder a task sits in is the truth today."""
        pairs, body = parse_task_document(document)
        _check_unique(pairs)
        task_id = value_of(_get_pair(pairs, "id"))
        if not task_id:
            raise FormatError("an imported task needs an id in its frontmatter")
        _check_id(task_id)
        declared = value_of(_get_pair(pairs, "status"))
        final = status or declared
        if final not in STATUSES:
            raise FormatError(f"status {final!r} is not one of {', '.join(STATUSES)}")
        if final != declared:
            _set_pair(pairs, "status", f" {final}")
        imported = {k: v for k, v in (("log_path", log_path), ("source_name", source_name)) if v}
        self._insert(task_id, final, pairs, body, actor, imported)
        return task_id

    def _insert(self, task_id, status, pairs, body, actor, imported=None) -> None:
        with _transaction(self.conn) as conn:
            _write_task(conn, task_id, status, pairs, body, insert=True, imported=imported)
            conn.execute("INSERT INTO task_events (task_id, ts, from_status, to_status, actor) "
                         "VALUES (?, ?, NULL, ?, ?)", (task_id, _now(), status, actor))

    def task_get(self, task_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_dict(row) if row else None

    def task_list(self, status: Optional[str] = None) -> list[dict]:
        sql = "SELECT * FROM tasks"
        args: tuple = ()
        if status:
            sql += " WHERE status = ?"
            args = (status,)
        sql += " ORDER BY created, id"
        return [_task_dict(r) for r in self.conn.execute(sql, args)]

    def task_export(self, task_id: str) -> str:
        task = self.task_get(task_id)
        if task is None:
            raise StateError(f"no task {task_id}")
        return render_task_document(task["frontmatter"], task["body"])

    def task_set(self, task_id: str, key: str, value: str) -> None:
        """Set one frontmatter key (not `status` or `id`: those have their own rules)."""
        if key in ("status", "id"):
            raise StateError(f"{key} is not set directly; use a transition")
        _check_field(key, value)
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter, body FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise StateError(f"no task {task_id}")
            pairs = json.loads(row["frontmatter"])
            _set_pair(pairs, key, f" {value}" if value != "" else "")
            _write_task(conn, task_id, row["status"], pairs, row["body"], insert=False)

    def task_transition(self, task_id: str, to_status: str,
                        expected_from: Optional[str | Iterable[str]] = None,
                        actor: Optional[str] = None,
                        rewrite_body: Optional[Callable[[str], str]] = None,
                        expected_row_version: Optional[int] = None,
                        token: Optional[str] = None,
                        **columns: Any) -> str:
        """Move a task. Refuses a move the table does not allow, or a task that is
        no longer where the caller saw it. Returns the status it came from.

        Moving to `active` takes a reservation like a claim does (and is refused when it
        does not fit); moving out of `active` needs the reservation's `token`.

        `rewrite_body`, when given, runs on the stored body inside this same
        transaction, so a status change and a body edit commit together or not
        at all.
        """
        allowed_from = ({expected_from} if isinstance(expected_from, str)
                        else set(expected_from) if expected_from else None)
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, row_version FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            current = row["status"]
            if allowed_from is not None and current not in allowed_from:
                raise TransitionRefused(f"{task_id} is {current}, not {'/'.join(sorted(allowed_from))}")
            _check_version(task_id, row["row_version"], expected_row_version)
            if current == "active" and conn.execute(
                    "SELECT 1 FROM transitions WHERE from_status = ? AND to_status = ?",
                    (current, to_status)).fetchone():
                _check_token(conn, task_id, token)      # an illegal move is refused as one first
            return _move(conn, task_id, to_status, actor, rewrite_body=rewrite_body,
                         extra=columns or None)

    def _unchanged_scope(self, task_id: str, before: tuple) -> None:
        row = self.conn.execute(
            "SELECT object, scope, effect FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or tuple(row) != before:
            raise StateError(f"{task_id}: object, scope or effect changed")

    def task_approve(self, task_id: str, actor: Optional[str] = None,
                     expected_row_version: Optional[int] = None) -> str:
        """draft or planned -> queued. Never rewrites object, scope or effect.

        New work is approved from draft. A task already in planned, including
        one that was there before this verb existed, uses the same move.

        The approval records what was approved (`approved_digest`, `approved_at`,
        `approved_row_version` and the `approved_definition` snapshot), with or
        without `expected_row_version`: the claim refuses a task that has no
        approval covering its content. With the version the approval is also
        checked against the exact stored task, and a task that revises another is
        refused while that other can still run.
        """
        with _transaction(self.conn) as conn:
            row = conn.execute(
                "SELECT status, frontmatter, body, row_version, object, scope, effect "
                "FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] not in ("draft", "planned"):
                raise TransitionRefused(f"{task_id} is {row['status']}, not draft/planned")
            _check_version(task_id, row["row_version"], expected_row_version)
            pairs = json.loads(row["frontmatter"])
            source_id = _field(pairs, "revises_task_id") if expected_row_version is not None else None
            if source_id:
                source = conn.execute("SELECT status, frontmatter FROM tasks WHERE id = ?",
                                      (source_id,)).fetchone()
                if source is not None:
                    repeats = str(_field(json.loads(source["frontmatter"]), "recurring") or "").lower() == "true"
                    if source["status"] in ("queued", "active") or (
                            source["status"] == "completed" and repeats):
                        raise TransitionRefused(
                            f"{task_id} revises {source_id}, which can still run; archive or cancel it first")
            came = _move(conn, task_id, "queued", actor or "approve",
                         fields=_approval_fields(conn, task_id, pairs, row["body"],
                                                 row["row_version"]))
            after = conn.execute("SELECT object, scope, effect FROM tasks WHERE id = ?",
                                 (task_id,)).fetchone()
            if tuple(after) != (row["object"], row["scope"], row["effect"]):
                raise StateError(f"{task_id}: object, scope or effect changed")
        return came

    def task_return_to_draft(self, task_id: str, *, expected_row_version: int,
                             actor: Optional[str] = None,
                             reason: str = "return_to_draft") -> dict:
        """queued -> draft, withdrawing the approval, in one transaction.

        The id, the body, the schedule and the run counters stay. Only the
        `approved_*` fields go; their values are kept in `audit`
        (`task_approval_withdrawn`) next to the status event. It does not queue
        or run anything: the task needs a new approval to be claimed again.
        """
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter, body, row_version FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] != "queued":
                raise TransitionRefused(f"{task_id} is {row['status']}, not queued")
            _check_version(task_id, row["row_version"], expected_row_version)
            pairs = json.loads(row["frontmatter"])
            withdrawn = self._withdraw_approval(conn, task_id, pairs, reason, actor)
            boundary = _record_boundary(pairs, row["body"])
            _move(conn, task_id, "draft", actor or "return_to_draft", drop=APPROVAL_KEYS,
                  fields={BOUNDARY_KEY: boundary} if boundary else None)
            version = conn.execute("SELECT row_version FROM tasks WHERE id = ?",
                                   (task_id,)).fetchone()[0]
        return dict(task_id=task_id, from_status="queued", status="draft",
                    row_version=version, withdrawn=withdrawn)

    _has_run = staticmethod(_has_run)

    @staticmethod
    def _withdraw_approval(conn, task_id: str, pairs: list[list[str]], reason: str,
                           actor: Optional[str]) -> dict:
        """Record the approval that is about to be dropped. The caller drops the fields."""
        withdrawn = {key: value_of(_get_pair(pairs, key)) for key in APPROVAL_KEYS
                     if _get_pair(pairs, key) is not None and key != "approved_definition"}
        _audit(conn, "task_approval_withdrawn", task_id=task_id, reason=reason, actor=actor,
               **withdrawn)
        return withdrawn

    def task_update(self, task_id: str, *, expected_row_version: int,
                    allowed_status: Iterable[str], fields: Optional[dict] = None,
                    body: Optional[str] = None, definition: Optional[str] = None,
                    to_status: Optional[str] = None, actor: Optional[str] = None) -> dict:
        """Edit a task in one transaction. Refuses a status outside `allowed_status`
        (an active task keeps the instructions it started with) and a task that
        changed since the caller read it. Never activates: `to_status` may only be
        a move the transition table allows, and the caller names it.

        A queued task keeps its place and its approval while the edit leaves the
        approved digest as it was (a rename). An edit that changes what was approved
        sends it to draft in the same transaction and withdraws the approval
        (`task_approval_withdrawn` in `audit`): the worker cannot claim it until it
        is approved again. Run counters, `recurring_last_run` and the runtime
        sections already in the body are not touched.

        `body` replaces the whole body. `definition` replaces the instructions only
        and keeps what the runtime appended after earlier runs. Returns the new
        `row_version`, the status and the digest.
        """
        if body is not None and definition is not None:
            raise StateError("pass the whole body or the definition, not both")
        allowed = set(allowed_status)
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter, body, row_version FROM tasks "
                               "WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            current = row["status"]
            if current not in allowed:
                raise TransitionRefused(f"{task_id} is {current}, not {'/'.join(sorted(allowed))}")
            _check_version(task_id, row["row_version"], expected_row_version)
            before = json.loads(row["frontmatter"])
            pairs = json.loads(row["frontmatter"])
            for key, value in (fields or {}).items():
                if key in ("status", "id"):
                    raise StateError(f"{key} is not set directly; use a transition")
                if key in APPROVAL_KEYS:
                    raise StateError(f"{key} is written by an approval, not set")
                _check_field(key, str(value))
                _set_pair(pairs, key, f" {value}" if value != "" else "")
            new_body = row["body"] if body is None else body
            received = None
            if definition is not None:
                new_body = definition
                received = definition_text(definition, value_of(_get_pair(pairs, "title")))
                # A task that ran, or that was queued (an import brings its results in the
                # body), keeps what the runtime wrote after its instructions. A draft that
                # never ran has no such content: its sections are the author's.
                known = _boundary(before)
                if (self._has_run(conn, task_id) or current not in ("draft", "planned")
                        or known is not None or _was_imported(conn, task_id)):
                    tail = runtime_tail(row["body"], value_of(_get_pair(before, "title")), known)
                    if tail:
                        if any(_is_runtime_heading(line) for line in received.splitlines()):
                            raise StateError(
                                f"{task_id}: the instructions of a task with recorded results "
                                "cannot contain a section named " + ", ".join(RUNTIME_SECTIONS))
                        new_body = definition.rstrip("\n") + "\n\n" + tail + "\n"
                _set_pair(pairs, BOUNDARY_KEY, " " + json.dumps(received))
            withdrawn = None
            # The digest of what the caller sent, before the results are put back: a section
            # named like a runtime one in the new instructions is still an instruction.
            after = (material_digest(pairs, new_body, definition=received)
                     if received is not None else current_digest(pairs, new_body))
            # An approval that does not cover the stored content (absent, legacy, mismatch)
            # is not kept through an edit either: the task goes to draft and is approved again.
            if current == "queued" and (after != current_digest(before, row["body"])
                                        or approval_state(before, row["body"]) is not None):
                withdrawn = self._withdraw_approval(conn, task_id, before, "material_edit", actor)
                if _get_pair(pairs, BOUNDARY_KEY) is None:
                    _record_boundary(pairs, row["body"])
                for key in APPROVAL_KEYS:
                    _drop_pair(pairs, key)
                to_status = "draft"
            status = current
            if to_status and to_status != current:
                if not conn.execute("SELECT 1 FROM transitions WHERE from_status = ? AND to_status = ?",
                                    (current, to_status)).fetchone():
                    raise TransitionRefused(f"{current} -> {to_status} is not an allowed transition")
                status = to_status
                _set_pair(pairs, "status", f" {status}")
                conn.execute("INSERT INTO task_events (task_id, ts, from_status, to_status, actor) "
                             "VALUES (?, ?, ?, ?, ?)", (task_id, _now(), current, status, actor))
            old_title, new_title = (value_of(_get_pair(p, "title")) for p in (before, pairs))
            if old_title != new_title:
                _audit(conn, "task_renamed", task_id=task_id, actor=actor, status=status,
                       from_title=old_title, to_title=new_title)
            _write_task(conn, task_id, status, pairs, new_body, insert=False)
            version = conn.execute("SELECT row_version FROM tasks WHERE id = ?",
                                   (task_id,)).fetchone()[0]
        return dict(task_id=task_id, status=status, row_version=version,
                    digest=task_digest(status, pairs, new_body),
                    returned_to_draft=withdrawn is not None,
                    approval_withdrawn=withdrawn is not None)

    def task_archive(self, task_id: str, *, expected_row_version: int, reason: str,
                     actor: Optional[str] = None) -> dict:
        """Retire a task without deleting it. The row, its events and its body stay.

        A queued task (a recurrence waiting for its next run included) is
        cancelled and archived in one transaction, so it can no longer be
        claimed. An active task is refused: it stops first. A task other tasks
        wait on, or whose subtasks still run, is refused rather than releasing
        them by surprise.
        """
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter, row_version FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            status = row["status"]
            if status == "archived":
                raise TransitionRefused(f"{task_id} is already archived")
            if status == "active":
                raise TransitionRefused(
                    f"{task_id} is active; request cancellation and archive it once it stopped")
            _check_version(task_id, row["row_version"], expected_row_version)
            for other in conn.execute(
                    "SELECT id, status, frontmatter FROM tasks WHERE id != ?", (task_id,)):
                if other["status"] in TERMINAL_STATUSES:
                    continue
                if task_id in _csv(_field(json.loads(other["frontmatter"]), "blocked_by_task_ids")):
                    raise TransitionRefused(f"{other['id']} is waiting on {task_id}")
            for child in conn.execute("SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,)):
                state = conn.execute("SELECT status FROM tasks WHERE id = ?", (child[0],)).fetchone()
                if state is not None and state[0] not in TERMINAL_STATUSES:
                    raise TransitionRefused(f"subtask {child[0]} of {task_id} is still {state[0]}")
            pairs = json.loads(row["frontmatter"])
            recurring = str(_field(pairs, "recurring") or "").lower() == "true"
            if status == "queued":
                _move(conn, task_id, "cancelled", actor or "archive")
            _move(conn, task_id, "archived", actor or "archive", fields={
                "archived_at": json.dumps(_now()),
                "archived_reason": json.dumps(reason),
                "archived_from": json.dumps(status),
            })
            events = conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id = ?",
                                  (task_id,)).fetchone()[0]
            version = conn.execute("SELECT row_version FROM tasks WHERE id = ?",
                                   (task_id,)).fetchone()[0]
        return dict(task_id=task_id, from_status=status, status="archived",
                    cancelled_first=status == "queued", recurring=recurring,
                    history_events=events, row_version=version)

    def task_requeue(self, task_id: str, actor: Optional[str] = None,
                     expected_row_version: Optional[int] = None) -> str:
        """error -> queued, and drop `## Execution Error` plus everything after it.

        The status change and the body cut commit in one transaction. Object,
        scope and effect stay as they were, so the next execution reads the
        original prompt.
        """
        row = self.conn.execute(
            "SELECT object, scope, effect FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TransitionRefused(f"no task {task_id}")
        before = tuple(row)
        came = self.task_transition(task_id, "queued", expected_from="error",
                                    actor=actor or "requeue",
                                    rewrite_body=_strip_execution_error,
                                    expected_row_version=expected_row_version)
        self._unchanged_scope(task_id, before)
        return came

    def task_cancel(self, task_id: str, actor: Optional[str] = None,
                    expected_row_version: Optional[int] = None) -> dict:
        """Cancel a queued task, or record the request for an active one.

        Only `queued` and `active`, the same limit as the plan. A queued task
        moves to cancelled. An active task stays active until the worker stops
        it. The request and the status change, when there is one, are one
        transaction: a refused transition leaves no request behind. Object,
        scope and effect are left as they were.
        """
        with _transaction(self.conn) as conn:
            row = conn.execute(
                "SELECT status, frontmatter, body, object, scope, effect, row_version "
                "FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            status = row["status"]
            if status not in ("queued", "active"):
                raise TransitionRefused(f"{task_id} is {status}, not queued/active")
            _check_version(task_id, row["row_version"], expected_row_version)
            before = (row["object"], row["scope"], row["effect"])
            conn.execute(
                "INSERT OR IGNORE INTO cancellation_requests (task_id, requested_at) VALUES (?, ?)",
                (task_id, _now()))
            task_status = status
            if status == "queued":
                if not conn.execute(
                        "SELECT 1 FROM transitions WHERE from_status = ? AND to_status = ?",
                        ("queued", "cancelled")).fetchone():
                    raise TransitionRefused("queued -> cancelled is not an allowed transition")
                pairs = json.loads(row["frontmatter"])
                _set_pair(pairs, "status", " cancelled")
                _write_task(conn, task_id, "cancelled", pairs, row["body"], insert=False)
                conn.execute(
                    "INSERT INTO task_events (task_id, ts, from_status, to_status, actor) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (task_id, _now(), "queued", "cancelled", actor or "cancel"))
                task_status = "cancelled"
            after = conn.execute(
                "SELECT object, scope, effect FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if after is None or tuple(after) != before:
                raise StateError(f"{task_id}: object, scope or effect changed")
        return dict(task_id=task_id, status="cancellation_requested", task_status=task_status)

    def tasks_unapproved(self) -> list[dict]:
        """Queued tasks the worker will not claim because no approval covers them:
        `[{id, title, reason}]`, reason `absent`, `legacy` or `mismatch`. What an upgrade
        leaves behind for rows queued by an earlier version."""
        found = []
        for row in self.conn.execute(
                "SELECT id, title, frontmatter, body FROM tasks WHERE status = 'queued' "
                "ORDER BY created, id"):
            try:
                reason = approval_state(json.loads(row["frontmatter"]), row["body"])
            except ValueError:
                reason = "absent"          # a record that cannot be read carries no approval
            if reason:
                found.append(dict(id=row["id"], title=row["title"], reason=reason))
        return found

    def task_claim(self, task_id: str, worker: str) -> bool:
        """queued -> active, atomically. True: it is yours. False: it exists and is no
        longer queued (someone else got it), or its approval does not cover what is
        stored, or it does not fit next to what runs (`task_claim_detail` says which). A
        task that does not exist raises."""
        return self.task_claim_detail(task_id, worker)["claimed"]

    def task_claim_detail(self, task_id: str, worker: str, *,
                          stamp_last_run: bool = False) -> dict:
        """`task_claim` with the reason it was refused: `not_queued`, the
        `approval_digest_mismatch` reason (`absent`, `legacy`, `mismatch`), or what keeps it
        from starting (`maintenance`, `cancellation_requested`, `blocked_by_dependency`,
        `parent_revoked`, `access_policy_invalid`, `drain_barrier` and the capacity reasons
        of the reservation). A claim that is refused changes nothing in the task, so a
        recurring one keeps its cadence. Claimed, it returns the execution `token` that
        completing, releasing and cleaning up need.

        This is the manual activation: it applies the same approval, dependency,
        cancellation and reservation rules as the worker. The schedule window and the
        recurring interval are the worker's selection rules and are not applied to a
        task a person starts by name. With `stamp_last_run` a recurring task gets its
        `recurring_last_run` in the same transaction as the claim."""
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT id, status, frontmatter, body, row_version, priority, "
                               "created FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise StateError(f"no task {task_id}")
            if row["status"] != "queued":
                return dict(claimed=False, reason="not_queued")
            if maintenance_state(self.root) is not None:
                return dict(claimed=False, reason="maintenance")
            pairs = json.loads(row["frontmatter"])
            moment = datetime.now()
            reason = _eligibility(conn, row, pairs, moment, manual=True)
            if reason:
                return dict(claimed=False, reason=reason)
            policy = _policy_row(conn)
            target = _drain_target(conn, policy, moment, exclude=task_id)
            access = _access_of(pairs, task_id)
            if target:
                _note_wait(conn, task_id, access, "drain_barrier", policy, target=None)
                return dict(claimed=False, reason="drain_barrier")
            reason = _admission(access, _occupancy(conn), policy)
            if reason:
                _note_wait(conn, task_id, access, reason, policy, target=None)
                return dict(claimed=False, reason=reason)
            stamp = {}
            if stamp_last_run and str(_field(pairs, "recurring") or "").lower() == "true":
                stamp = {"recurring_last_run": _now()}
            _move(conn, task_id, "active", worker, fields=stamp,
                  extra={"claimed_by": worker, "claimed_at": _now()}, handoff=True)
            token = conn.execute("SELECT token FROM execution_reservations WHERE task_id = ?",
                                 (task_id,)).fetchone()[0]
        return dict(claimed=True, reason=None, token=token)

    def task_status(self, task_id: str) -> Optional[str]:
        """The status column. It replaced the directory the task file used to sit in."""
        row = self.conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return row[0] if row else None

    def task_field(self, task_id: str, key: str) -> Optional[str]:
        task = self.task_get(task_id)
        if task is None:
            raise StateError(f"no task {task_id}")
        return _field(task["frontmatter"], key)

    def task_find_origin(self, origin_request_id: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT id FROM tasks WHERE origin_request_id = ? ORDER BY created, id LIMIT 1",
            (origin_request_id,)).fetchone()
        return row[0] if row else None

    def task_find_subtask_key(self, key: str) -> Optional[str]:
        """The child whose frontmatter `subtask_key` is `key`, if one exists."""
        for task in self.task_list():
            if _field(task["frontmatter"], "subtask_key") == key:
                return task["id"]
        return None

    def task_unset(self, task_id: str, key: str) -> None:
        if key in ("status", "id"):
            raise StateError(f"{key} is not removed directly")
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter, body FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise StateError(f"no task {task_id}")
            pairs = json.loads(row["frontmatter"])
            _drop_pair(pairs, key)
            _write_task(conn, task_id, row["status"], pairs, row["body"], insert=False)

    def task_set_body(self, task_id: str, body: str) -> None:
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise StateError(f"no task {task_id}")
            _write_task(conn, task_id, row["status"], json.loads(row["frontmatter"]),
                        body, insert=False)

    def task_record(self, task_id: str, *, pid: Optional[int] = None,
                    log_path: Optional[str] = None, token: Optional[str] = None) -> None:
        """Remember the worker pid or the log path. Neither is a status change. Recording
        a pid claims to own the execution, so it needs the reservation's `token`."""
        extra = {}
        if pid is not None:
            extra["pid"] = pid
        if log_path is not None:
            extra["log_path"] = log_path
        if not extra:
            return
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter, body FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise StateError(f"no task {task_id}")
            if pid is not None:
                _check_token(conn, task_id, token)
            _write_task(conn, task_id, row["status"], json.loads(row["frontmatter"]),
                        row["body"], insert=False, extra=extra)

    def task_claim_next(self, worker: str, *, exclude: Iterable[str] = (),
                        now: Optional[datetime] = None) -> Optional[dict]:
        """Claim the next queued task that is ready, in one transaction.

        Order is priority (high, then normal, then low), then `created`, then id.
        A queued task with a cancellation request is cancelled and skipped. A
        task waiting on another, a recurring task still inside its interval, one
        outside its schedule window, or one whose approval does not cover what is
        stored (`approval_digest_mismatch`) is left queued. So is a task that does
        not fit next to what runs: the global capacity, a provider limit, a scope
        that a writer shares, a resource held, or an unknown (legacy) task, which
        runs alone. `exclude` skips ids the caller already tried (a hook blocked
        them and they were released). Returns the claimed task with its execution
        `token`, or None when nothing could start; `task_claim_next_detail` says why.
        Hooks are not run here.
        """
        result = self.task_claim_next_detail(worker, exclude=exclude, now=now)
        task = result["task"]
        if task is not None:
            task["token"] = result["token"]
        return task

    def task_claim_next_detail(self, worker: str, *, exclude: Iterable[str] = (),
                               now: Optional[datetime] = None) -> dict:
        """`task_claim_next` with what it learned: `{task, token, waiting}` where
        `waiting` lists `{id, reason}` for the eligible tasks that did not start."""
        moment = now or datetime.now()
        now_epoch = moment.timestamp()
        skipped = set(exclude)
        claimed: Optional[str] = None
        waiting: list[dict] = []
        with _transaction(self.conn) as conn:
            if maintenance_state(self.root) is not None:
                return dict(task=None, token=None, waiting=[dict(id=None, reason="maintenance")])
            policy = _policy_row(conn)
            rows = list(conn.execute(
                "SELECT id, status, priority, created, frontmatter, body, row_version FROM tasks "
                "WHERE status = 'queued'"))
            rows.sort(key=_claim_order)
            target = _drain_target(conn, policy, moment)
            held = _occupancy(conn)
            exclusives: set[str] = set()
            for row in rows:
                task_id = row["id"]
                if conn.execute("SELECT 1 FROM cancellation_requests WHERE task_id = ?",
                                (task_id,)).fetchone():
                    _move(conn, task_id, "cancelled", "claim-next")
                    continue
                if task_id in skipped:
                    exclusives.add(task_id)
                    continue
                pairs = json.loads(row["frontmatter"])
                if _eligibility(conn, row, pairs, moment, manual=False):
                    continue
                access = _access_of(pairs, task_id)
                if access.exclusive:
                    exclusives.add(task_id)
                if target and task_id != target:
                    waiting.append(dict(id=task_id, reason="drain_barrier"))
                    _note_wait(conn, task_id, access, "drain_barrier", policy, target=None)
                    continue
                reason = _admission(access, held, policy)
                if reason is None:
                    _move(conn, task_id, "active", worker,
                          extra={"claimed_by": worker, "claimed_at": _now()})
                    claimed = task_id
                    break
                waiting.append(dict(id=task_id, reason=reason))
                _note_wait(conn, task_id, access, reason, policy, target=target, held=held)
            if claimed is None:
                # A wait only counts while the task stays eligible: dependencies, schedule or
                # approval that stopped holding reset its clock.
                for wait in conn.execute("SELECT task_id FROM claim_waits").fetchall():
                    if wait[0] not in exclusives:
                        conn.execute("DELETE FROM claim_waits WHERE task_id = ?", (wait[0],))
            token = (conn.execute("SELECT token FROM execution_reservations WHERE task_id = ?",
                                  (claimed,)).fetchone()[0] if claimed else None)
        return dict(task=self.task_get(claimed) if claimed else None, token=token, waiting=waiting)

    def task_release(self, task_id: str, worker: str, token: Optional[str] = None) -> None:
        """Give back a task this worker just claimed, when a hook blocked it. The
        reservation goes with it; a stale `token` is refused."""
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] != "active" or row["claimed_by"] != worker:
                raise TransitionRefused(
                    f"{task_id} is not claimed by {worker}")
            _check_token(conn, task_id, token)
            _move(conn, task_id, "queued", worker,
                  extra={"claimed_by": None, "claimed_at": None})

    def task_complete(self, task_id: str, *, actor: Optional[str] = None,
                      cancelled: bool = False, token: Optional[str] = None) -> str:
        """Finish an active task. Returns the status it landed in.

        A cancellation becomes `cancelled`. Otherwise the task is `completed`
        and, when it is recurring, either archived (the run cap is reached) or
        queued again for the next run. The whole sequence is one transaction.
        Resource hooks run before this, in the caller: a hook that fails should
        `task_fail` instead.
        """
        who = actor or ("cancel" if cancelled else "complete")
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] != "active":
                raise TransitionRefused(f"{task_id} is {row['status']}, not active")
            _check_token(conn, task_id, token)
            if cancelled:
                _move(conn, task_id, "cancelled", who)
                return "cancelled"
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _move(conn, task_id, "completed", who, fields={"completed_at": stamp})
            pairs = json.loads(conn.execute(
                "SELECT frontmatter FROM tasks WHERE id = ?", (task_id,)).fetchone()[0])
            if str(_field(pairs, "recurring") or "").lower() != "true":
                return "completed"
            try:
                count = int(_field(pairs, "recurring_run_count") or "0") + 1
            except ValueError:
                count = 1
            try:
                cap = int(_field(pairs, "recurring_max_runs") or "0")
            except ValueError:
                cap = 0
            fields = {"recurring_run_count": str(count)}
            if cap > 0 and count >= cap:
                _move(conn, task_id, "archived", who, fields=fields)
                return "archived"
            _move(conn, task_id, "queued", who, fields=fields)
            return "queued"

    def task_fail(self, task_id: str, suffix: str, *, actor: Optional[str] = None,
                  fields: Optional[dict] = None, token: Optional[str] = None) -> None:
        """Move a task to error and append `suffix` to its body, together."""
        def rewrite(body: str) -> str:
            text = body.rstrip("\n")
            extra = suffix.strip("\n")
            return (text + "\n\n" + extra + "\n") if extra else body

        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] == "active":
                _check_token(conn, task_id, token)
            _move(conn, task_id, "error", actor or "fail", rewrite_body=rewrite, fields=fields)

    def task_await(self, task_id: str, child_ids: Iterable[str],
                   token: Optional[str] = None) -> None:
        """Park an active parent until the named children are terminal."""
        seen: list[str] = []
        for child in child_ids:
            if child and child not in seen:
                seen.append(child)
        if not seen:
            raise StateError("awaiting subtasks needs at least one child id")
        quoted = json.dumps(",".join(seen), ensure_ascii=False)
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] != "active":
                raise TransitionRefused(f"{task_id} is {row['status']}, not active")
            _check_token(conn, task_id, token)
            _move(conn, task_id, "queued", "await",
                  fields={"blocked_by_task_ids": quoted})

    def task_link(self, parent_id: str, child_id: str, subtask_key: Optional[str] = None) -> None:
        with _transaction(self.conn) as conn:
            conn.execute("INSERT OR REPLACE INTO task_links (parent_id, child_id, subtask_key) "
                         "VALUES (?, ?, ?)", (parent_id, child_id, subtask_key))

    def subtask_plan_import_text(self, parent_id: str, text: str) -> None:
        """The children a parent declared, stored as the JSON text it was."""
        json.loads(text)
        with _transaction(self.conn) as conn:
            conn.execute("INSERT OR REPLACE INTO subtask_plans (parent_id, plan) VALUES (?, ?)",
                         (parent_id, text))

    def subtask_plan_text(self, parent_id: str) -> Optional[str]:
        row = self.conn.execute("SELECT plan FROM subtask_plans WHERE parent_id = ?",
                                (parent_id,)).fetchone()
        return row[0] if row else None

    def subtask_plan_parents(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT parent_id FROM subtask_plans ORDER BY parent_id")]

    def cancellation_request(self, task_id: str) -> None:
        with _transaction(self.conn) as conn:
            conn.execute("INSERT OR IGNORE INTO cancellation_requests (task_id, requested_at) "
                         "VALUES (?, ?)", (task_id, _now()))

    def cancellation_requested(self, task_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM cancellation_requests WHERE task_id = ?",
                                 (task_id,)).fetchone() is not None

    def cancellation_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT task_id FROM cancellation_requests ORDER BY task_id")]

    def task_children(self, parent_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT child_id, subtask_key FROM task_links WHERE parent_id = ? ORDER BY child_id",
            (parent_id,))]

    # -- reservations ------------------------------------------------------

    def reservations(self) -> list[dict]:
        """Every reservation with what it holds. Active tasks that have none (they predate
        reservations) are listed with `token: None` and count as exclusive."""
        out = []
        for row in self.conn.execute("SELECT * FROM execution_reservations ORDER BY claimed_at, task_id"):
            item = dict(row)
            item["scopes"] = [dict(path=r[0], mode=r[1]) for r in self.conn.execute(
                "SELECT path, mode FROM reservation_scopes WHERE token = ? ORDER BY path, mode",
                (row["token"],))]
            item["resources"] = [r[0] for r in self.conn.execute(
                "SELECT name FROM reservation_resources WHERE token = ? ORDER BY name", (row["token"],))]
            out.append(item)
        for row in self.conn.execute("SELECT id FROM tasks WHERE status = 'active' AND id NOT IN "
                                     "(SELECT task_id FROM execution_reservations) ORDER BY id"):
            out.append(dict(token=None, task_id=row[0], access_class="exclusive", scopes=[],
                            resources=[], legacy_active=True))
        return out

    def reservation_for(self, task_id: str) -> Optional[dict]:
        return next((r for r in self.reservations() if r["task_id"] == task_id), None)

    def reservation_attach(self, task_id: str, token: str, *, pid: Optional[int] = None) -> None:
        """The executor says it owns this reservation: its pid and start time are what a
        later recovery checks before it decides the owner is gone."""
        pid = os.getpid() if pid is None else int(pid)
        with _transaction(self.conn) as conn:
            self._require_reserved(conn, task_id, token)
            conn.execute("UPDATE execution_reservations SET owner_pid = ?, owner_started = ?, "
                         "heartbeat_at = ?, lease_expires_at = ?, handoff = 0 WHERE task_id = ?",
                         (pid, _process_identity(pid), _now(), _lease_expiry(), task_id))

    def reservation_heartbeat(self, task_id: str, token: str) -> None:
        with _transaction(self.conn) as conn:
            self._require_reserved(conn, task_id, token)
            conn.execute("UPDATE execution_reservations SET heartbeat_at = ?, lease_expires_at = ? "
                         "WHERE task_id = ?", (_now(), _lease_expiry(), task_id))

    @staticmethod
    def _require_reserved(conn, task_id: str, token: Optional[str]) -> None:
        if conn.execute("SELECT 1 FROM execution_reservations WHERE task_id = ?",
                        (task_id,)).fetchone() is None:
            raise StaleToken(f"{task_id} holds no reservation")
        _check_token(conn, task_id, token)

    def task_adopt(self, task_id: str, worker: str, *,
                   identity: Callable[[int], Optional[str]] = _process_identity) -> dict:
        """Take over an active task nobody is running, with a new token.

        Allowed only when the previous owner cannot be running it: a manual activation no
        executor has attached to yet, or a lease that expired whose recorded process is gone
        (or is no longer the process that started). A lease that expired with its process
        still alive is not adoptable: it is reported as `owner_alive` and left alone. An
        active task that predates reservations has no owner to wait for. The old token stops
        working the moment this commits.
        """
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] != "active":
                return dict(adopted=False, reason="not_active")
            if maintenance_state(self.root) is not None:
                return dict(adopted=False, reason="maintenance")
            res = conn.execute("SELECT * FROM execution_reservations WHERE task_id = ?",
                               (task_id,)).fetchone()
            token = uuid.uuid4().hex
            if res is None:
                pairs = json.loads(row["frontmatter"])
                access = _access_of(pairs, task_id)
                if access.invalid:
                    return dict(adopted=False, reason="access_policy_invalid")
                policy = _policy_row(conn)
                reason = _admission(access, _occupancy(conn, ignore_task=task_id), policy)
                if reason:
                    return dict(adopted=False, reason=reason)
                _reserve_with(conn, task_id, pairs, worker, token, handoff=False)
            else:
                unattached = bool(res["handoff"]) and res["owner_pid"] is None
                expired = _epoch(res["lease_expires_at"]) <= time.time()
                if not unattached:
                    if not expired:
                        return dict(adopted=False, reason="lease_valid")
                    if res["owner_pid"] is not None:
                        alive = identity(res["owner_pid"])
                        if alive and (res["owner_started"] is None or alive == res["owner_started"]):
                            return dict(adopted=False, reason="owner_alive")
                conn.execute("UPDATE execution_reservations SET token = ?, worker = ?, handoff = 0, "
                             "owner_pid = NULL, owner_started = NULL, heartbeat_at = ?, "
                             "lease_expires_at = ? WHERE task_id = ?",
                             (token, worker, _now(), _lease_expiry(), task_id))
            conn.execute("UPDATE tasks SET claimed_by = ? WHERE id = ?", (worker, task_id))
            _audit(conn, "task_adopted", task_id=task_id, worker=worker,
                   previous_token_ended=res is not None)
        return dict(adopted=True, reason=None, token=token)

    # -- execution policy --------------------------------------------------

    def async_policy(self) -> dict:
        """The applied configuration: what every claim reads, in its own transaction."""
        return _policy_row(self.conn)

    def async_policy_apply(self, document: Any, *, actor: Optional[str] = None,
                           expected_digest: Optional[str] = None) -> dict:
        """Apply a validated revision to the runtime's policy, in one transaction. A
        proposal that does not validate is refused and the applied one stays. With
        `expected_digest` the document must be exactly the one that was approved."""
        with _transaction(self.conn) as conn:
            current = _policy_row(conn)
            normalized = validate_policy_document(document, current["revision"])
            digest = policy_digest(normalized)
            if expected_digest is not None and digest != expected_digest:
                raise PolicyInvalid("the proposal is not the one that was approved "
                                    "(its digest changed); nothing was applied")
            conn.execute(
                "UPDATE async_policy SET revision = ?, global_capacity = ?, provider_capacity = ?, "
                "exclusive_wait_seconds = ?, enabled_reader_profiles = ?, applied_at = ?, "
                "applied_by = ?, proposal_digest = ? WHERE id = 1",
                (normalized["revision"], normalized["global_capacity"],
                 json.dumps(normalized["provider_capacity"], sort_keys=True),
                 normalized["exclusive_wait_seconds"],
                 json.dumps(normalized["enabled_reader_profiles"]), _now(), actor, digest))
            _audit(conn, "async_policy_applied", actor=actor, revision=normalized["revision"],
                   previous_revision=current["revision"],
                   global_capacity=normalized["global_capacity"],
                   previous_global_capacity=current["global_capacity"], digest=digest)
            applied = _policy_row(conn)
        return dict(applied, digest=digest)

    def async_policy_status(self) -> dict:
        """Applied revision, the proposal file and what would change. Reads only."""
        applied = self.async_policy()
        proposal = read_proposal(self.root)
        status = dict(applied=applied, proposal=dict(present=proposal["present"],
                                                    path=proposal["path"], error=proposal["error"]),
                      pending=False, differences={}, applies=False)
        document = proposal["document"]
        if document is None:
            return status
        try:
            normalized = validate_policy_document(document, applied["revision"])
            status["applies"] = True
            status["proposal"]["digest"] = policy_digest(normalized)
        except PolicyInvalid as exc:
            status["proposal"]["error"] = str(exc)
            normalized = None
        if isinstance(document, dict):
            for key in ("global_capacity", "provider_capacity", "exclusive_wait_seconds",
                        "enabled_reader_profiles"):
                if key in document and document[key] != applied[key]:
                    status["differences"][key] = dict(applied=applied[key], proposed=document[key])
            status["pending"] = bool(status["differences"]) or (
                _is_int(document.get("revision")) and document["revision"] > applied["revision"])
        return status

    # -- provenance of a derived authorization -------------------------------

    def authorization_record(self, child_id: str, parent_id: str, child_key: str, *,
                             parent_digest: str, manifest_digest: str) -> bool:
        """Record that `child_id` was authorized by `parent_id`'s approved definition.
        The same record again is a no-op (True means it was written now); another manifest
        for the same parent and key is refused."""
        with _transaction(self.conn) as conn:
            for task in (child_id, parent_id):
                if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task,)).fetchone() is None:
                    raise StateError(f"no task {task}")
            same = conn.execute("SELECT * FROM task_authorizations WHERE parent_id = ? AND child_key = ?",
                                (parent_id, child_key)).fetchone()
            if same is not None:
                if (same["task_id"], same["manifest_digest"], same["parent_digest"]) != (
                        child_id, manifest_digest, parent_digest):
                    raise StateError(f"{parent_id}/{child_key} was authorized with other content")
                return False
            conn.execute("INSERT INTO task_authorizations (task_id, kind, parent_id, parent_digest, "
                         "manifest_digest, child_key, recorded_at) VALUES (?, 'derived', ?, ?, ?, ?, ?)",
                         (child_id, parent_id, parent_digest, manifest_digest, child_key, _now()))
        return True

    def legacy_children(self) -> list[dict]:
        """Subtasks created before derived authorizations existed: every task that names a
        parent (the frontmatter or a link) and has no authorization record. Read-only: nothing
        is backfilled from `parent_task_id`. `executable` says whether the child can be
        claimed today under its own approval; one that cannot stays out of the queue until a
        person approves it again."""
        recorded = {r[0] for r in self.conn.execute("SELECT task_id FROM task_authorizations")}
        linked = {r[0]: r[1] for r in self.conn.execute("SELECT child_id, parent_id FROM task_links")}
        found = []
        for task in self.task_list():
            pairs = task["frontmatter"]
            parent = _field(pairs, "parent_task_id") or linked.get(task["id"])
            if not parent or task["id"] in recorded:
                continue
            approval = approval_state(pairs, task["body"]) or "valid"
            found.append(dict(id=task["id"], parent_id=parent, status=task["status"],
                              approval=approval,
                              executable=task["status"] == "queued" and approval == "valid"))
        return found

    # -- audit -------------------------------------------------------------

    def audit_append(self, row: dict) -> int:
        line = json.dumps(row, ensure_ascii=True)
        with _transaction(self.conn) as conn:
            cur = conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?, ?, ?, ?)",
                               (row.get("ts"), row.get("event"), row.get("router_id"), line))
        return int(cur.lastrowid)

    def audit_import_line(self, line: str) -> int:
        """Store one audit line as written (spacing, key order, escapes)."""
        text = line.rstrip("\n")
        row = json.loads(text)
        with _transaction(self.conn) as conn:
            cur = conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?, ?, ?, ?)",
                               (row.get("ts"), row.get("event"), row.get("router_id"), text))
        return int(cur.lastrowid)

    def audit_file_register(self) -> None:
        """The audit file existed on disk, whether or not it had lines."""
        with _transaction(self.conn) as conn:
            conn.execute("INSERT OR IGNORE INTO audit_source (id) VALUES (1)")

    def audit_file_present(self) -> bool:
        return self.conn.execute("SELECT 1 FROM audit_source WHERE id = 1").fetchone() is not None

    def audit_lines(self) -> list[str]:
        """Every audit line, verbatim, in order: what an export writes back."""
        return [r[0] for r in self.conn.execute("SELECT row FROM audit ORDER BY seq")]

    def audit_rows(self, event: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
        sql, args = "SELECT row FROM audit", []
        if event:
            sql += " WHERE event = ?"
            args.append(event)
        sql += " ORDER BY seq DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return [json.loads(r[0]) for r in reversed(self.conn.execute(sql, args).fetchall())]

    # -- continuity --------------------------------------------------------

    def continuity_get(self) -> Optional[dict]:
        row = self.conn.execute("SELECT data FROM continuity WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else None

    def agent_continuity(self, planet: str, agent: str, responsibility: str,
                         task_id: str) -> dict:
        """Read one recorded task checkpoint, never choose a task implicitly."""
        task = self.task_get(task_id)
        if task is None:
            raise ValueError("continuity task not found")
        fields = {key: value_of(value) for key, value in task["frontmatter"]}
        for key, expected in (("planet", planet), ("agent", agent),
                              ("responsibility", responsibility)):
            if fields.get(key) != expected:
                raise ValueError(f"continuity {key} does not match requested identity")
        owner = _read_owner_file(self.root)
        if owner is None:
            raise ValueError("runtime owner missing")
        if fields.get("workspace_id") != owner["workspace_id"]:
            raise ValueError("continuity workspace does not match runtime owner")
        raw = fields.get("continuity_checkpoint")
        try:
            checkpoint = json.loads(raw)
        except (TypeError, ValueError):
            raise ValueError("continuity checkpoint must be a JSON object") from None
        if not isinstance(checkpoint, dict):
            raise ValueError("continuity checkpoint must be a JSON object")
        return {"workspace_id": fields["workspace_id"], "planet": planet,
                "agent": agent, "responsibility": responsibility,
                "task_id": task_id, "agent_contract": fields.get("agent_contract"),
                "continuity_checkpoint": checkpoint}

    def continuity_text(self) -> Optional[str]:
        row = self.conn.execute("SELECT data FROM continuity WHERE id = 1").fetchone()
        return row[0] if row else None

    def continuity_import_text(self, text: str) -> None:
        """Store the continuity document exactly as written."""
        json.loads(text)
        with _transaction(self.conn) as conn:
            conn.execute("INSERT INTO continuity (id, data, updated_at) VALUES (1, ?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET data = excluded.data, "
                         "updated_at = excluded.updated_at", (text, _now()))

    def continuity_update(self, change) -> dict:
        """Read-modify-write in one transaction: `change(current_or_None) -> new`."""
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT data FROM continuity WHERE id = 1").fetchone()
            data = change(json.loads(row[0]) if row else None)
            text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            conn.execute("INSERT INTO continuity (id, data, updated_at) VALUES (1, ?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET data = excluded.data, "
                         "updated_at = excluded.updated_at", (text, _now()))
        return data

    def continuity_adopt_legacy(self, workspace: Path) -> str:
        """Copy a pre-v0.25.7 record from sun/runtime into this row, once.

        The newer side wins. The legacy file is renamed to a unique backup.
        Returns "none", "adopted" or "kept". OSError means try again next time.
        """
        legacy = Path(workspace) / "sun" / "runtime" / "continuity" / "active.json"
        if not legacy.is_file():
            return "none"
        if not os.access(legacy.parent, os.W_OK):
            raise OSError(f"cannot adopt continuity from {legacy}")
        try:
            text = legacy.read_text(encoding="utf-8")
            data = json.loads(text)
            # The winner may rename the file between the read and this stat.
            # The file disappearing is the expected race, not a disk error.
            mtime = legacy.stat().st_mtime
        except FileNotFoundError:
            return "none"
        except json.JSONDecodeError as exc:
            raise OSError(f"continuity legacy is not json: {exc}") from exc
        if not isinstance(data, dict):
            raise OSError("continuity legacy is not an object")
        row = self.conn.execute("SELECT updated_at FROM continuity WHERE id = 1").fetchone()
        adopt = row is None or mtime > _epoch(row[0] or "")
        if adopt:
            self.continuity_import_text(text if text.endswith("\n") else text + "\n")
        backup = _unique_sibling(legacy, "migrated")
        try:
            legacy.rename(backup)
        except FileNotFoundError:
            return "none"
        return "adopted" if adopt else "kept"

    # -- mandate events ----------------------------------------------------

    def delegation_event_append(self, mandate: str, stream: str, row: dict) -> int:
        line = json.dumps(row, ensure_ascii=False)
        with _transaction(self.conn) as conn:
            _register_stream(conn, mandate, stream)
            cur = conn.execute("INSERT INTO delegation_events (mandate, stream, ts, row) "
                               "VALUES (?, ?, ?, ?)", (mandate, stream, row.get("ts"), line))
        return int(cur.lastrowid)

    def delegation_stream_register(self, mandate: str, stream: str) -> None:
        """Record that a stream exists, with or without events."""
        with _transaction(self.conn) as conn:
            _register_stream(conn, mandate, stream)

    def delegation_streams(self) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT mandate, stream FROM delegation_streams ORDER BY mandate, stream")]

    def delegation_event_import_line(self, mandate: str, stream: str, line: str) -> int:
        """Store one mandate event line as written."""
        text = line.rstrip("\n")
        row = json.loads(text)
        with _transaction(self.conn) as conn:
            _register_stream(conn, mandate, stream)
            cur = conn.execute("INSERT INTO delegation_events (mandate, stream, ts, row) "
                               "VALUES (?, ?, ?, ?)", (mandate, stream, row.get("ts"), text))
        return int(cur.lastrowid)

    def delegation_event_lines(self, mandate: str, stream: str = "events") -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT row FROM delegation_events WHERE mandate = ? AND stream = ? ORDER BY seq",
            (mandate, stream))]

    def delegation_events(self, mandate: str, stream: str = "events") -> list[dict]:
        return [json.loads(r[0]) for r in self.conn.execute(
            "SELECT row FROM delegation_events WHERE mandate = ? AND stream = ? ORDER BY seq",
            (mandate, stream))]

    def delegation_decide_append(self, mandate: str, stream: str, decide):
        """One transaction: `decide(events)` returns a row to append, or a list of errors."""
        with _transaction(self.conn) as conn:
            events = [json.loads(r[0]) for r in conn.execute(
                "SELECT row FROM delegation_events WHERE mandate = ? AND stream = ? ORDER BY seq",
                (mandate, stream))]
            outcome = decide(events)
            if isinstance(outcome, list):
                return outcome
            line = json.dumps(outcome, ensure_ascii=False)
            _register_stream(conn, mandate, stream)
            conn.execute("INSERT INTO delegation_events (mandate, stream, ts, row) "
                         "VALUES (?, ?, ?, ?)",
                         (mandate, stream, outcome.get("ts"), line))
            return outcome

    # -- overview ----------------------------------------------------------

    def counts(self) -> dict:
        return dict(
            tasks={r[0]: r[1] for r in self.conn.execute(
                "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY status")},
            audit=self.conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
            delegation_events=self.conn.execute("SELECT COUNT(*) FROM delegation_events").fetchone()[0],
            continuity=bool(self.conn.execute("SELECT 1 FROM continuity").fetchone()),
        )

    def console_task_counts(self) -> dict:
        """Counts the console shows, from the console_task_counts view."""
        rows = self.conn.execute(
            "SELECT state, n, recurring FROM console_task_counts").fetchall()
        return {state: {"n": n, "recurring": recurring} for state, n, recurring in rows}


def _open_ready(base: Path, auto_backup: bool) -> Session:
    """Open a sqlite session. The caller already holds the state lock."""
    path = db_path(base)
    if not path.is_file():
        raise StateUnavailable(f"{path} is missing although the format says sqlite")
    conn = _connect(path)
    try:
        version = _schema_version(conn)
        if version != SCHEMA_VERSION:
            raise StateUnavailable(
                f"state schema v{version}, this code speaks v{SCHEMA_VERSION}: "
                "the schema migration has not run")
        if auto_backup:
            backup_if_due(conn, base)
        return Session(conn, base)
    except Exception:
        conn.close()
        raise


@contextmanager
def read_session(root=None, timeout: float = DEFAULT_LOCK_TIMEOUT) -> Iterator[Session]:
    """A read that creates nothing.

    Opens the existing state.lock shared and holds it until the caller is done.
    Refuses when the lock, the owner, the format, or the schema is missing.
    Does not take the daily backup.
    """
    base = _root(root)
    with _flock_existing(base, timeout):
        _require_owner(base)
        fmt = read_format(base)
        if fmt != FORMAT_SQLITE:
            raise StateUnavailable(
                f"runtime state format is {fmt or 'unset'}, not sqlite: "
                "this runtime has not been migrated to solar-state")
        store = _open_readonly(base)
        try:
            yield store
        finally:
            store.conn.close()


@contextmanager
def session(root=None, timeout: float = DEFAULT_LOCK_TIMEOUT,
            auto_backup: bool = True) -> Iterator[Session]:
    """The door for every read and write. Holds the shared lock throughout."""
    base = _root(root)
    with _flock(base, exclusive=False, timeout=timeout):
        _require_owner(base)
        fmt = read_format(base)
        if fmt != FORMAT_SQLITE:
            raise StateUnavailable(
                f"runtime state format is {fmt or 'unset'}, not sqlite: "
                "this runtime has not been migrated to solar-state")
        store = _open_ready(base, auto_backup)
        try:
            yield store
        finally:
            store.conn.close()


@contextmanager
def operate(root=None, timeout: float = DEFAULT_LOCK_TIMEOUT,
            auto_backup: bool = True) -> Iterator[tuple]:
    """Shared lock for a caller that still has a file queue and a sqlite queue.

    The format is read inside the lock, and the lock is held until the caller
    finishes the file write or the sqlite write. `unset` and `files` yield
    `(format, None)`. `sqlite` yields `(sqlite, Session)`. Any other marker
    refuses: it is not treated as the file queue. A cutover cannot take the
    exclusive lock until this returns.
    """
    base = _root(root)
    with _flock(base, exclusive=False, timeout=timeout):
        _require_owner(base)
        fmt = read_format(base)
        if fmt not in (None, FORMAT_FILES, FORMAT_SQLITE):
            raise StateUnavailable(
                f"runtime state format is {fmt!r}: expected unset, files or sqlite")
        if fmt != FORMAT_SQLITE:
            yield fmt, None
            return
        store = _open_ready(base, auto_backup)
        try:
            yield FORMAT_SQLITE, store
        finally:
            store.conn.close()


def describe(root=None, timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """Format, schema and counts, all read under one shared lock, so a cutover is
    never seen half done. When a session would refuse, says why instead."""
    base = _root(root)
    with _flock(base, exclusive=False, timeout=timeout):
        info: dict[str, Any] = dict(root=str(base), format=read_format(base),
                                    db=str(db_path(base)), expected_schema=SCHEMA_VERSION,
                                    schema=None, ready=False, reason=None)
        path = db_path(base)
        if path.is_file():
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                info["schema"] = _schema_version(conn)
                if info["format"] == FORMAT_SQLITE and info["schema"] == SCHEMA_VERSION:
                    info["counts"] = Session(conn, base).counts()
                    info["ready"] = True
            finally:
                conn.close()
        if info["ready"]:
            try:
                _require_owner(base)
            except StateUnavailable as exc:
                info["ready"] = False
                info["reason"] = str(exc)
        elif info["format"] != FORMAT_SQLITE:
            info["reason"] = f"format is {info['format'] or 'unset'}, not sqlite"
        elif info["schema"] is None:
            info["reason"] = "the base is missing"
        else:
            info["reason"] = f"schema v{info['schema']}, this code speaks v{SCHEMA_VERSION}"
        return info


# ---------------------------------------------------------------------------
# Cutover: the only place the schema and the format change
# ---------------------------------------------------------------------------

class Cutover:
    """Held under the exclusive lock. `solar state migrate` and `rollback` use it."""

    def __init__(self, root: Path):
        self.root = root

    def upgrade_schema(self) -> dict:
        """Create or upgrade the base. An existing base is copied first."""
        path = db_path(self.root)
        existed = path.is_file()
        conn = _connect(path)
        try:
            current = _schema_version(conn)
            if current > SCHEMA_VERSION:
                raise StateUnavailable(
                    f"state schema v{current} is newer than this code (v{SCHEMA_VERSION})")
            backup = None
            if existed and current < SCHEMA_VERSION:
                backup = _backup_to(conn, backup_dir(self.root, "pre-migration"),
                                    f"state-v{current}-to-v{SCHEMA_VERSION}-{_stamp()}.sqlite")
            try:
                # All versions in one transaction (user_version is part of it): a migration
                # that fails leaves the base exactly as it was. The same loop builds a new
                # base, so a migration that cannot run inside a transaction (VACUUM, a
                # PRAGMA that commits) breaks that too; a test pins it.
                with _transaction(conn):
                    for version in range(current + 1, SCHEMA_VERSION + 1):
                        # Statement by statement: executescript() would COMMIT mid-transaction.
                        for statement in _statements(MIGRATIONS[version - 1]):
                            conn.execute(statement)
                        if version == 1:
                            conn.executemany("INSERT INTO statuses (name) VALUES (?)",
                                             [(s,) for s in STATUSES])
                            conn.executemany("INSERT INTO transitions VALUES (?, ?)", TRANSITIONS)
                        conn.execute(f"PRAGMA user_version = {version}")
            except BaseException:
                if backup is not None:
                    Path(backup).unlink(missing_ok=True)    # a copy of a base nothing changed
                raise
            return dict(from_version=current, to_version=SCHEMA_VERSION,
                        backup=str(backup) if backup else None)
        finally:
            conn.close()

    def set_format(self, value: str) -> None:
        if value not in (FORMAT_SQLITE, FORMAT_FILES):
            raise ValueError(value)
        path = format_path(self.root)
        tmp = path.with_name(f".{path.name}.{os.getpid()}")
        tmp.write_text(value + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def session(self) -> Session:
        """A session inside the cutover: no shared lock, no format check."""
        conn = _connect(db_path(self.root))
        return Session(conn, self.root)


def _statements(script: str) -> list[str]:
    cleaned = "\n".join(line.split("--", 1)[0] for line in script.splitlines())
    return [s.strip() for s in cleaned.split(";") if s.strip()]


@contextmanager
def cutover(root=None, timeout: float = DEFAULT_LOCK_TIMEOUT) -> Iterator[Cutover]:
    base = _root(root)
    with _flock(base, exclusive=True, timeout=timeout):
        _require_owner(base)
        yield Cutover(base)


# ---------------------------------------------------------------------------
# CLI (for Bash): JSON out, exit 2 on a refusal
# ---------------------------------------------------------------------------

def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="solar_state.py", description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=None, help="runtime root (default: solar-paths)")
    sub = parser.add_subparsers(dest="area", required=True)

    status = sub.add_parser("status", help="format, schema and counts, under the shared lock")
    status.add_argument("--timeout", type=float, default=DEFAULT_LOCK_TIMEOUT)
    owner = sub.add_parser("owner").add_subparsers(dest="cmd", required=True)
    owner_claim = owner.add_parser("claim")
    owner_claim.add_argument("--workspace", required=True)
    owner_claim.add_argument("--id", default=None)
    owner_claim.add_argument("--rebind", action="store_true")
    owner.add_parser("show")
    owner_replace = owner.add_parser("replace-id")
    owner_replace.add_argument("--id", required=True)
    backup = sub.add_parser("backup", help="take a copy now")
    backup.add_argument("--kind", default="daily", choices=("daily", "manual"))

    task = sub.add_parser("task").add_subparsers(dest="cmd", required=True)
    create = task.add_parser("create")
    create.add_argument("--status", default="draft", choices=CREATE_STATUSES)
    create.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    create.add_argument("--body", default=None)
    create.add_argument("--body-file", default=None)
    for name in ("get", "show"):
        task.add_parser(name).add_argument("id")
    lister = task.add_parser("list")
    lister.add_argument("--status", default=None)
    setter = task.add_parser("set")
    setter.add_argument("id")
    setter.add_argument("key")
    setter.add_argument("value")
    move = task.add_parser("transition")
    move.add_argument("id")
    move.add_argument("to", choices=STATUSES)
    move.add_argument("--from", dest="expected_from", default=None)
    move.add_argument("--actor", default=None)
    move.add_argument("--token", default=os.environ.get("SOLAR_TASK_TOKEN") or None,
                      help="execution token, needed to move an active task out of active")
    claim = task.add_parser("claim")
    claim.add_argument("id")
    claim.add_argument("--worker", required=True)
    claim.add_argument("--stamp-last-run", action="store_true",
                       help="record recurring_last_run in the claim transaction")
    task.add_parser("list-unapproved", help="queued tasks the worker will not claim, and why")
    draft = task.add_parser("return-to-draft", help="queued -> draft, approval withdrawn")
    draft.add_argument("id")
    draft.add_argument("--expected-row-version", type=int, required=True)
    nxt = task.add_parser("claim-next")
    nxt.add_argument("--worker", required=True)
    nxt.add_argument("--exclude", default="", help="comma-separated ids to skip")
    token_default = os.environ.get("SOLAR_TASK_TOKEN") or None
    release = task.add_parser("release")
    release.add_argument("id")
    release.add_argument("--worker", required=True)
    release.add_argument("--token", default=token_default)
    done = task.add_parser("complete")
    done.add_argument("id")
    done.add_argument("--cancelled", action="store_true")
    done.add_argument("--token", default=token_default)
    fail = task.add_parser("fail")
    fail.add_argument("id")
    fail.add_argument("--suffix", default="")
    fail.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    fail.add_argument("--token", default=token_default)
    waiting = task.add_parser("await")
    waiting.add_argument("id")
    waiting.add_argument("--child", action="append", default=[])
    waiting.add_argument("--token", default=token_default)
    task.add_parser("reservations", help="what is running and what each holds")
    task.add_parser("legacy-children", help="subtasks without a derived authorization record")
    adopt = task.add_parser("adopt", help="take over an active task nobody runs, with a new token")
    adopt.add_argument("id")
    adopt.add_argument("--worker", required=True)
    for name in ("attach", "heartbeat"):
        sub_cmd = task.add_parser(name)
        sub_cmd.add_argument("id")
        sub_cmd.add_argument("--token", default=token_default, required=token_default is None)
        if name == "attach":
            sub_cmd.add_argument("--pid", type=int, default=None)
    task.add_parser("status").add_argument("id")
    field = task.add_parser("field")
    field.add_argument("id")
    field.add_argument("key")
    unset = task.add_parser("unset")
    unset.add_argument("id")
    unset.add_argument("key")
    task.add_parser("write-body", help="replace the body with stdin").add_argument("id")
    origin = task.add_parser("find-origin")
    origin.add_argument("origin_request_id")
    link = task.add_parser("link")
    link.add_argument("parent")
    link.add_argument("child")
    link.add_argument("--key", default=None)
    task.add_parser("counts")
    for name in ("approve", "cancel", "requeue"):
        task.add_parser(name).add_argument("id")

    audit = sub.add_parser("audit").add_subparsers(dest="cmd", required=True)
    audit.add_parser("append", help="one JSON row on stdin")
    rows = audit.add_parser("rows")
    rows.add_argument("--event", default=None)
    rows.add_argument("--limit", type=int, default=None)

    policy = sub.add_parser("async-policy").add_subparsers(dest="cmd", required=True)
    policy.add_parser("status", help="applied revision, proposal file and differences")
    policy_apply = policy.add_parser("apply", help="apply the proposal file as a new revision")
    policy_apply.add_argument("--digest", default=None, help="digest the approval was bound to")
    sub.add_parser("maintenance", help="the update barrier, if one is held")

    cont = sub.add_parser("continuity").add_subparsers(dest="cmd", required=True)
    cont.add_parser("get")
    cont.add_parser("put", help="the whole JSON document on stdin")

    args = parser.parse_args(argv)
    root = _root(args.root)
    try:
        if args.area == "status":
            _print(describe(root, timeout=args.timeout))
            return 0
        if args.area == "owner":
            if args.cmd == "claim":
                _print(claim_owner(args.workspace, args.id, rebind=args.rebind, root=root))
            elif args.cmd == "show":
                _print(owner_record(root))
            elif args.cmd == "replace-id":
                _print(replace_owner_id(args.id, root=root))
            return 0
        if args.area == "maintenance":
            _print(dict(held=maintenance_state(root) is not None, state=maintenance_state(root)))
            return 0
        with session(root) as s:
            if args.area == "backup":
                _print(dict(path=str(backup_now(s.conn, root, args.kind))))
            elif args.area == "task":
                if args.cmd == "create":
                    fields = []
                    for item in args.field:
                        key, sep, value = item.partition("=")
                        if not sep:
                            parser.error(f"--field expects KEY=VALUE, got {item!r}")
                        fields.append((key, value))
                    body = (Path(args.body_file).read_text(encoding="utf-8")
                            if args.body_file else (args.body or ""))
                    _print(dict(id=s.task_create(fields, body, status=args.status)))
                elif args.cmd == "get":
                    task = s.task_get(args.id)
                    if task is None:
                        raise StateError(f"no task {args.id}")
                    _print(task)
                elif args.cmd == "show":
                    sys.stdout.write(s.task_export(args.id))
                elif args.cmd == "list":
                    _print([{
                        "id": t["id"], "status": t["status"], "title": t["title"],
                        "priority": t["priority"], "created": t["created"],
                        "scheduled_time": t["scheduled_time"], "recurring": bool(t["recurring"]),
                        "fields": {key: value_of(rest) for key, rest in t["frontmatter"]},
                    } for t in s.task_list(args.status)])
                elif args.cmd == "set":
                    s.task_set(args.id, args.key, args.value)
                    _print(dict(id=args.id, key=args.key))
                elif args.cmd == "transition":
                    came = s.task_transition(args.id, args.to, args.expected_from, actor=args.actor,
                                             token=args.token)
                    _print(dict(id=args.id, from_status=came, to_status=args.to))
                elif args.cmd == "claim":
                    result = s.task_claim_detail(args.id, args.worker,
                                               stamp_last_run=args.stamp_last_run)
                    _print(dict(id=args.id, **{k: v for k, v in result.items()
                                               if v is not None}))
                    return 0 if result["claimed"] else 3
                elif args.cmd == "list-unapproved":
                    _print(s.tasks_unapproved())
                elif args.cmd == "return-to-draft":
                    _print(s.task_return_to_draft(args.id, expected_row_version=args.expected_row_version,
                                                  actor="cli"))
                elif args.cmd == "claim-next":
                    excluded = [part for part in args.exclude.split(",") if part]
                    result = s.task_claim_next_detail(args.worker, exclude=excluded)
                    task = result["task"]
                    _print(dict(id=task["id"] if task else None,
                                title=task["title"] if task else None,
                                claimed=task is not None, token=result["token"],
                                waiting=result["waiting"]))
                elif args.cmd == "release":
                    s.task_release(args.id, args.worker, token=args.token)
                    _print(dict(id=args.id, status="queued"))
                elif args.cmd == "complete":
                    landed = s.task_complete(args.id, cancelled=args.cancelled, token=args.token)
                    _print(dict(id=args.id, status=landed))
                elif args.cmd == "fail":
                    fields = []
                    for item in args.field:
                        key, sep, value = item.partition("=")
                        if not sep:
                            parser.error(f"--field expects KEY=VALUE, got {item!r}")
                        fields.append((key, value))
                    s.task_fail(args.id, args.suffix, fields=dict(fields), token=args.token)
                    _print(dict(id=args.id, status="error"))
                elif args.cmd == "await":
                    s.task_await(args.id, args.child, token=args.token)
                    _print(dict(id=args.id, status="queued"))
                elif args.cmd == "reservations":
                    _print(s.reservations())
                elif args.cmd == "legacy-children":
                    _print(s.legacy_children())
                elif args.cmd == "adopt":
                    result = s.task_adopt(args.id, args.worker)
                    _print(dict(id=args.id, **result))
                    return 0 if result["adopted"] else 3
                elif args.cmd == "attach":
                    s.reservation_attach(args.id, args.token, pid=args.pid)
                    _print(dict(id=args.id))
                elif args.cmd == "heartbeat":
                    s.reservation_heartbeat(args.id, args.token)
                    _print(dict(id=args.id))
                elif args.cmd == "status":
                    status = s.task_status(args.id)
                    if status is None:
                        raise StateError(f"no task {args.id}")
                    _print(dict(id=args.id, status=status))
                elif args.cmd == "field":
                    _print(dict(id=args.id, key=args.key, value=s.task_field(args.id, args.key)))
                elif args.cmd == "unset":
                    s.task_unset(args.id, args.key)
                    _print(dict(id=args.id, key=args.key))
                elif args.cmd == "write-body":
                    s.task_set_body(args.id, sys.stdin.read())
                    _print(dict(id=args.id))
                elif args.cmd == "find-origin":
                    _print(dict(id=s.task_find_origin(args.origin_request_id)))
                elif args.cmd == "link":
                    s.task_link(args.parent, args.child, args.key)
                    _print(dict(parent=args.parent, child=args.child))
                elif args.cmd == "counts":
                    _print(s.counts()["tasks"])
                elif args.cmd == "approve":
                    came = s.task_approve(args.id)
                    _print(dict(id=args.id, from_status=came, to_status="queued"))
                elif args.cmd == "requeue":
                    came = s.task_requeue(args.id)
                    _print(dict(id=args.id, from_status=came, to_status="queued"))
                elif args.cmd == "cancel":
                    _print(s.task_cancel(args.id))
            elif args.area == "audit":
                if args.cmd == "append":
                    _print(dict(seq=s.audit_append(json.loads(sys.stdin.read()))))
                else:
                    _print(s.audit_rows(args.event, args.limit))
            elif args.area == "async-policy":
                if args.cmd == "status":
                    _print(s.async_policy_status())
                else:
                    proposal = read_proposal(root)
                    _print(s.async_policy_apply(proposal["document"], actor="cli",
                                                expected_digest=args.digest))
            elif args.area == "continuity":
                if args.cmd == "get":
                    _print(s.continuity_get())
                else:
                    document = json.loads(sys.stdin.read())
                    _print(s.continuity_update(lambda _current: document))
        return 0
    except StateError as exc:
        print(json.dumps(dict(error=type(exc).__name__, detail=str(exc))), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
