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
from typing import Any, Callable, Iterable, Iterator, Optional

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
                  now: datetime) -> bool:
    """Whether a task may start at `now`. Same window the queue used on files.

    No schedule means always. `scheduled_time: now` means always. A weekday
    list uses ISO days (Monday is 1). A clock time is ready within fifteen
    minutes, wrapping midnight.
    """
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
          extra: Optional[dict] = None) -> str:
    """One allowed transition. The caller already holds the transaction."""
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
    _write_task(conn, task_id, to_status, pairs, body, insert=False, extra=extra)
    conn.execute("INSERT INTO task_events (task_id, ts, from_status, to_status, actor) "
                 "VALUES (?, ?, ?, ?, ?)", (task_id, _now(), current, to_status, actor))
    return current


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
        self._insert(task_id, status, pairs, body, actor)
        return task_id

    def task_import(self, document: str, status: Optional[str] = None,
                    actor: str = "import", log_path: Optional[str] = None,
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
                        **columns: Any) -> str:
        """Move a task. Refuses a move the table does not allow, or a task that is
        no longer where the caller saw it. Returns the status it came from.

        `rewrite_body`, when given, runs on the stored body inside this same
        transaction, so a status change and a body edit commit together or not
        at all.
        """
        allowed_from = ({expected_from} if isinstance(expected_from, str)
                        else set(expected_from) if expected_from else None)
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            current = row["status"]
            if allowed_from is not None and current not in allowed_from:
                raise TransitionRefused(f"{task_id} is {current}, not {'/'.join(sorted(allowed_from))}")
            return _move(conn, task_id, to_status, actor, rewrite_body=rewrite_body,
                         extra=columns or None)

    def _unchanged_scope(self, task_id: str, before: tuple) -> None:
        row = self.conn.execute(
            "SELECT object, scope, effect FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or tuple(row) != before:
            raise StateError(f"{task_id}: object, scope or effect changed")

    def task_approve(self, task_id: str, actor: Optional[str] = None) -> str:
        """draft or planned -> queued. Never rewrites object, scope or effect.

        New work is approved from draft. A task already in planned, including
        one that was there before this verb existed, uses the same move.
        """
        row = self.conn.execute(
            "SELECT object, scope, effect FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TransitionRefused(f"no task {task_id}")
        before = tuple(row)
        came = self.task_transition(task_id, "queued", expected_from=("draft", "planned"),
                                    actor=actor or "approve")
        self._unchanged_scope(task_id, before)
        return came

    def task_requeue(self, task_id: str, actor: Optional[str] = None) -> str:
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
                                    rewrite_body=_strip_execution_error)
        self._unchanged_scope(task_id, before)
        return came

    def task_cancel(self, task_id: str, actor: Optional[str] = None) -> dict:
        """Cancel a queued task, or record the request for an active one.

        Only `queued` and `active`, the same limit as the plan. A queued task
        moves to cancelled. An active task stays active until the worker stops
        it. The request and the status change, when there is one, are one
        transaction: a refused transition leaves no request behind. Object,
        scope and effect are left as they were.
        """
        with _transaction(self.conn) as conn:
            row = conn.execute(
                "SELECT status, frontmatter, body, object, scope, effect FROM tasks WHERE id = ?",
                (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            status = row["status"]
            if status not in ("queued", "active"):
                raise TransitionRefused(f"{task_id} is {status}, not queued/active")
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
                    log_path: Optional[str] = None) -> None:
        """Remember the worker pid or the log path. Neither is a status change."""
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
            _write_task(conn, task_id, row["status"], json.loads(row["frontmatter"]),
                        row["body"], insert=False, extra=extra)

    def task_claim_next(self, worker: str, *, exclude: Iterable[str] = (),
                        now: Optional[datetime] = None) -> Optional[dict]:
        """Claim the next queued task that is ready, in one transaction.

        Order is priority (high, then normal, then low), then `created`, then id.
        A queued task with a cancellation request is cancelled and skipped. A
        task waiting on another, a recurring task still inside its interval, or
        one outside its schedule window is left queued. `exclude` skips ids the
        caller already tried (a hook blocked them and they were released).
        Returns the claimed task, or None when nothing is ready. Hooks are not
        run here.
        """
        moment = now or datetime.now()
        now_epoch = moment.timestamp()
        skipped = set(exclude)
        claimed: Optional[str] = None
        with _transaction(self.conn) as conn:
            rows = list(conn.execute(
                "SELECT id, priority, created, frontmatter FROM tasks WHERE status = 'queued'"))
            rows.sort(key=lambda row: (
                -_PRIORITY_RANK.get(row["priority"] or "", 0), row["created"] or "", row["id"]))
            for row in rows:
                task_id = row["id"]
                if conn.execute("SELECT 1 FROM cancellation_requests WHERE task_id = ?",
                                (task_id,)).fetchone():
                    _move(conn, task_id, "cancelled", "claim-next")
                    continue
                if task_id in skipped:
                    continue
                pairs = json.loads(row["frontmatter"])
                if _blocked(conn, pairs):
                    continue
                if not _recurring_ready(pairs, now_epoch):
                    continue
                if not scheduled_now(_field(pairs, "scheduled_time"),
                                     _field(pairs, "scheduled_weekdays"), moment):
                    continue
                _move(conn, task_id, "active", worker,
                      extra={"claimed_by": worker, "claimed_at": _now()})
                claimed = task_id
                break
        return self.task_get(claimed) if claimed else None

    def task_release(self, task_id: str, worker: str) -> None:
        """Give back a task this worker just claimed, when a hook blocked it."""
        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            if row["status"] != "active" or row["claimed_by"] != worker:
                raise TransitionRefused(
                    f"{task_id} is not claimed by {worker}")
            _move(conn, task_id, "queued", worker,
                  extra={"claimed_by": None, "claimed_at": None})

    def task_complete(self, task_id: str, *, actor: Optional[str] = None,
                      cancelled: bool = False) -> str:
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
                  fields: Optional[dict] = None) -> None:
        """Move a task to error and append `suffix` to its body, together."""
        def rewrite(body: str) -> str:
            text = body.rstrip("\n")
            extra = suffix.strip("\n")
            return (text + "\n\n" + extra + "\n") if extra else body

        with _transaction(self.conn) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TransitionRefused(f"no task {task_id}")
            _move(conn, task_id, "error", actor or "fail", rewrite_body=rewrite, fields=fields)

    def task_await(self, task_id: str, child_ids: Iterable[str]) -> None:
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
    nxt = task.add_parser("claim-next")
    nxt.add_argument("--worker", required=True)
    nxt.add_argument("--exclude", default="", help="comma-separated ids to skip")
    release = task.add_parser("release")
    release.add_argument("id")
    release.add_argument("--worker", required=True)
    done = task.add_parser("complete")
    done.add_argument("id")
    done.add_argument("--cancelled", action="store_true")
    fail = task.add_parser("fail")
    fail.add_argument("id")
    fail.add_argument("--suffix", default="")
    fail.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    waiting = task.add_parser("await")
    waiting.add_argument("id")
    waiting.add_argument("--child", action="append", default=[])
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
                    came = s.task_transition(args.id, args.to, args.expected_from, actor=args.actor)
                    _print(dict(id=args.id, from_status=came, to_status=args.to))
                elif args.cmd == "claim":
                    won = s.task_claim(args.id, args.worker)
                    _print(dict(id=args.id, claimed=won))
                    return 0 if won else 3
                elif args.cmd == "claim-next":
                    excluded = [part for part in args.exclude.split(",") if part]
                    task = s.task_claim_next(args.worker, exclude=excluded)
                    _print(dict(id=task["id"] if task else None,
                                title=task["title"] if task else None,
                                claimed=task is not None))
                elif args.cmd == "release":
                    s.task_release(args.id, args.worker)
                    _print(dict(id=args.id, status="queued"))
                elif args.cmd == "complete":
                    landed = s.task_complete(args.id, cancelled=args.cancelled)
                    _print(dict(id=args.id, status=landed))
                elif args.cmd == "fail":
                    fields = []
                    for item in args.field:
                        key, sep, value = item.partition("=")
                        if not sep:
                            parser.error(f"--field expects KEY=VALUE, got {item!r}")
                        fields.append((key, value))
                    s.task_fail(args.id, args.suffix, fields=dict(fields))
                    _print(dict(id=args.id, status="error"))
                elif args.cmd == "await":
                    s.task_await(args.id, args.child)
                    _print(dict(id=args.id, status="queued"))
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
