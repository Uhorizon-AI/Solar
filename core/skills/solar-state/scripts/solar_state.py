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
import os
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

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
BACKUP_DIR = "state-backups"
DAILY_KEEP = 7
DAILY_MAX_AGE_SEC = 24 * 3600
DEFAULT_LOCK_TIMEOUT = float(os.environ.get("SOLAR_STATE_LOCK_TIMEOUT", "30"))

STATUSES = ("draft", "planned", "queued", "active", "completed", "error", "archived", "cancelled")

# Every move the async-tasks scripts make today, and nothing else.
TRANSITIONS = (
    ("draft", "planned"), ("draft", "queued"), ("draft", "cancelled"), ("draft", "archived"),
    ("planned", "queued"), ("planned", "draft"), ("planned", "cancelled"), ("planned", "archived"),
    ("queued", "active"), ("queued", "error"), ("queued", "cancelled"),
    ("active", "completed"), ("active", "error"), ("active", "cancelled"),
    ("active", "queued"),        # a parent goes back to wait for its subtasks
    ("completed", "queued"),     # recurring task, next run
    ("completed", "archived"),   # recurring task, max runs reached
    ("error", "queued"), ("error", "archived"), ("error", "cancelled"),
    ("cancelled", "archived"),
)
CREATE_STATUSES = ("draft", "planned", "queued")

# Frontmatter keys projected to columns: the ones transitions and queries use.
COLUMN_KEYS = (
    "title", "priority", "created", "updated", "completed_at", "scheduled_time",
    "provider", "parent_task_id", "origin_channel", "origin_chat_id",
    "origin_request_id", "origin_thread_id", "origin_run_id",
    "object", "scope", "effect", "notify_when", "recurring",
)
# Internal columns a transition may set besides the status. Nothing else reaches SQL.
TRANSITION_COLUMNS = ("claimed_by", "claimed_at", "pid", "log_path")

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


class FormatError(StateError):
    """A task document that does not follow the frontmatter contract."""


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


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

@contextmanager
def _flock(root: Path, exclusive: bool, timeout: float) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / LOCK_NAME, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle.fileno(), mode)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        kind = "exclusive" if exclusive else "shared"
                        raise StateBusy(f"{kind} state lock not granted in {timeout:g}s "
                                        "(a cutover may be running)") from None
                    time.sleep(0.02)
        yield
    finally:
        handle.close()  # closing releases the flock


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


def _projection(pairs: list[list[str]]) -> dict[str, Any]:
    cols: dict[str, Any] = {key: value_of(_get_pair(pairs, key)) for key in COLUMN_KEYS}
    cols["recurring"] = 1 if str(cols["recurring"] or "").lower() == "true" else 0
    return cols


def _write_task(conn, task_id: str, status: str, pairs, body: str, *, insert: bool,
                extra: Optional[dict] = None) -> None:
    cols = _projection(pairs)
    for name, value in (extra or {}).items():
        if name not in TRANSITION_COLUMNS:
            raise StateError(f"{name} is not a column a transition may set")
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


def _task_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["frontmatter"] = json.loads(data["frontmatter"])
    return data


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
        task_id = task_id or declared or str(uuid.uuid4())
        # A declared id is kept as it was written. Only an id this call supplies
        # is written, JSON-encoded, so value_of() reads back exactly task_id.
        if _get_pair(pairs, "id") is None:
            pairs.insert(0, ["id", " " + json.dumps(task_id, ensure_ascii=False)])
        elif not declared:
            _set_pair(pairs, "id", " " + json.dumps(task_id, ensure_ascii=False))
        _set_pair(pairs, "status", f" {status}")
        self._insert(task_id, status, pairs, body, actor)
        return task_id

    def task_import(self, document: str, status: Optional[str] = None,
                    actor: str = "import") -> str:
        """Store a task document exactly as written: the pairs `parse_task_document`
        returns, untouched. Any status is accepted (this is how existing tasks
        enter). `status`, when given, wins over the frontmatter one and is written
        back into it — the folder a task sits in is the truth today."""
        pairs, body = parse_task_document(document)
        _check_unique(pairs)
        task_id = value_of(_get_pair(pairs, "id"))
        if not task_id:
            raise FormatError("an imported task needs an id in its frontmatter")
        declared = value_of(_get_pair(pairs, "status"))
        final = status or declared
        if final not in STATUSES:
            raise FormatError(f"status {final!r} is not one of {', '.join(STATUSES)}")
        if final != declared:
            _set_pair(pairs, "status", f" {final}")
        self._insert(task_id, final, pairs, body, actor)
        return task_id

    def _insert(self, task_id, status, pairs, body, actor) -> None:
        with _transaction(self.conn) as conn:
            _write_task(conn, task_id, status, pairs, body, insert=True)
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
                        actor: Optional[str] = None, **columns: Any) -> str:
        """Move a task. Refuses a move the table does not allow, or a task that is
        no longer where the caller saw it. Returns the status it came from."""
        allowed_from = ({expected_from} if isinstance(expected_from, str)
                        else set(expected_from) if expected_from else None)
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, frontmatter, body FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            current = row["status"]
            if allowed_from is not None and current not in allowed_from:
                raise TransitionRefused(f"{task_id} is {current}, not {'/'.join(sorted(allowed_from))}")
            if not conn.execute("SELECT 1 FROM transitions WHERE from_status = ? AND to_status = ?",
                                (current, to_status)).fetchone():
                raise TransitionRefused(f"{current} -> {to_status} is not an allowed transition")
            pairs = json.loads(row["frontmatter"])
            _set_pair(pairs, "status", f" {to_status}")
            _write_task(conn, task_id, to_status, pairs, row["body"], insert=False, extra=columns)
            conn.execute("INSERT INTO task_events (task_id, ts, from_status, to_status, actor) "
                         "VALUES (?, ?, ?, ?, ?)", (task_id, _now(), current, to_status, actor))
        return current

    def task_claim(self, task_id: str, worker: str) -> bool:
        """queued -> active, atomically. True: it is yours. False: it exists and is no
        longer queued (someone else got it). A task that does not exist raises."""
        if self.conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
            raise StateError(f"no task {task_id}")
        try:
            self.task_transition(task_id, "active", expected_from="queued", actor=worker,
                                 claimed_by=worker, claimed_at=_now())
        except TransitionRefused:
            return False
        return True

    def task_link(self, parent_id: str, child_id: str, subtask_key: Optional[str] = None) -> None:
        with _transaction(self.conn) as conn:
            conn.execute("INSERT OR REPLACE INTO task_links (parent_id, child_id, subtask_key) "
                         "VALUES (?, ?, ?)", (parent_id, child_id, subtask_key))

    def task_children(self, parent_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT child_id, subtask_key FROM task_links WHERE parent_id = ? ORDER BY child_id",
            (parent_id,))]

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

    # -- mandate events ----------------------------------------------------

    def delegation_event_append(self, mandate: str, stream: str, row: dict) -> int:
        line = json.dumps(row, ensure_ascii=False)
        with _transaction(self.conn) as conn:
            cur = conn.execute("INSERT INTO delegation_events (mandate, stream, ts, row) "
                               "VALUES (?, ?, ?, ?)", (mandate, stream, row.get("ts"), line))
        return int(cur.lastrowid)

    def delegation_event_import_line(self, mandate: str, stream: str, line: str) -> int:
        """Store one mandate event line as written."""
        text = line.rstrip("\n")
        row = json.loads(text)
        with _transaction(self.conn) as conn:
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

    # -- overview ----------------------------------------------------------

    def counts(self) -> dict:
        return dict(
            tasks={r[0]: r[1] for r in self.conn.execute(
                "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY status")},
            audit=self.conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
            delegation_events=self.conn.execute("SELECT COUNT(*) FROM delegation_events").fetchone()[0],
            continuity=bool(self.conn.execute("SELECT 1 FROM continuity").fetchone()),
        )


@contextmanager
def session(root=None, timeout: float = DEFAULT_LOCK_TIMEOUT,
            auto_backup: bool = True) -> Iterator[Session]:
    """The door for every read and write. Holds the shared lock throughout."""
    base = _root(root)
    with _flock(base, exclusive=False, timeout=timeout):
        fmt = read_format(base)
        if fmt != FORMAT_SQLITE:
            raise StateUnavailable(
                f"runtime state format is {fmt or 'unset'}, not sqlite: "
                "this runtime has not been migrated to solar-state")
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
            yield Session(conn, base)
        finally:
            conn.close()


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
        if not info["ready"]:
            if info["format"] != FORMAT_SQLITE:
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
            for version in range(current + 1, SCHEMA_VERSION + 1):
                with _transaction(conn):
                    # Statement by statement: executescript() would COMMIT mid-transaction.
                    for statement in _statements(MIGRATIONS[version - 1]):
                        conn.execute(statement)
                    if version == 1:
                        conn.executemany("INSERT INTO statuses (name) VALUES (?)",
                                         [(s,) for s in STATUSES])
                        conn.executemany("INSERT INTO transitions VALUES (?, ?)", TRANSITIONS)
                    conn.execute(f"PRAGMA user_version = {version}")
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
    claim = task.add_parser("claim")
    claim.add_argument("id")
    claim.add_argument("--worker", required=True)

    audit = sub.add_parser("audit").add_subparsers(dest="cmd", required=True)
    audit.add_parser("append", help="one JSON row on stdin")
    rows = audit.add_parser("rows")
    rows.add_argument("--event", default=None)
    rows.add_argument("--limit", type=int, default=None)

    cont = sub.add_parser("continuity").add_subparsers(dest="cmd", required=True)
    cont.add_parser("get")
    cont.add_parser("put", help="the whole JSON document on stdin")

    args = parser.parse_args(argv)
    root = _root(args.root)
    try:
        if args.area == "status":
            _print(describe(root, timeout=args.timeout))
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
                    _print([{k: t[k] for k in ("id", "status", "title", "priority", "created")}
                            for t in s.task_list(args.status)])
                elif args.cmd == "set":
                    s.task_set(args.id, args.key, args.value)
                    _print(dict(id=args.id, key=args.key))
                elif args.cmd == "transition":
                    came = s.task_transition(args.id, args.to, args.expected_from, actor=args.actor)
                    _print(dict(id=args.id, from_status=came, to_status=args.to))
                elif args.cmd == "claim":
                    won = s.task_claim(args.id, args.worker)
                    _print(dict(id=args.id, claimed=won))
                    return 0 if won else 3
            elif args.area == "audit":
                if args.cmd == "append":
                    _print(dict(seq=s.audit_append(json.loads(sys.stdin.read()))))
                else:
                    _print(s.audit_rows(args.event, args.limit))
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
