"""A portable planet database for minimal execution facts, never CRM copies."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from _memory_common import directory_lock, file_hash, locked_parent, name, planet_root, within

SCHEMA = """
PRAGMA user_version = 1;
CREATE TABLE metadata (planet TEXT PRIMARY KEY, need TEXT NOT NULL, approval_sha256 TEXT NOT NULL);
CREATE TABLE facts (
 agent TEXT NOT NULL, responsibility TEXT NOT NULL, event_id TEXT NOT NULL,
 result TEXT NOT NULL, source TEXT NOT NULL, source_sha256 TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 PRIMARY KEY(agent, responsibility, event_id));
"""


def location(workspace, planet, agent):
    _, root, _ = planet_root(workspace, planet, agent)
    return root, within(root, ".solar/agent-memory.sqlite")


def validate(conn, planet):
    if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("unsupported fact schema; migration requires a backup and reviewed version")
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("fact database integrity failed")
    rows = conn.execute("SELECT planet FROM metadata").fetchall()
    if rows != [(planet,)]:
        raise ValueError("fact database belongs to another planet")


def initialize(workspace, planet, agent, need):
    if not isinstance(need, str) or not 10 <= len(need.strip()) <= 1024:
        raise ValueError("an observed execution-memory need is required")
    workspace = Path(workspace).resolve()
    reference, separator, anchor = need.partition("#")
    if not separator or not anchor or not reference.startswith(("sun/plans/", "sun/delegations/")):
        raise ValueError("need must reference an existing approval in sun/plans or sun/delegations, with an anchor")
    approval = within(workspace, reference)
    if not approval.is_file() or approval.stat().st_size > 262144:
        raise ValueError("need approval file is missing or oversized")
    headings = [line.lstrip("#").strip().lower() for line in approval.read_text().splitlines() if line.startswith("#")]
    slugs = [re.sub(r"[^\w -]", "", heading).replace(" ", "-") for heading in headings]
    if anchor not in slugs:
        raise ValueError("need approval anchor not found")
    root, dest = location(workspace, planet, agent)
    if (root / ".git").exists():
        ignore = root / ".gitignore"
        if not ignore.is_file() or ".solar/" not in ignore.read_text().splitlines():
            raise ValueError("planet Git must explicitly ignore .solar/ before initialization")
    with locked_parent(dest):
        if dest.exists():
            raise ValueError("fact database already exists")
        fd, temp = tempfile.mkstemp(dir=dest.parent, prefix=".facts-")
        os.close(fd)
        try:
            with closing(sqlite3.connect(temp)) as conn, conn:
                conn.executescript(SCHEMA)
                conn.execute("INSERT INTO metadata VALUES (?, ?, ?)", (planet, need, file_hash(approval)))
            os.replace(temp, dest)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return {"created": True, "path": str(dest), "schema": 1}


@contextmanager
def opened(workspace, planet, agent, write=False):
    root, path = location(workspace, planet, agent)
    if not path.is_file():
        raise ValueError("fact database absent; initialize explicitly after need is approved")
    lock_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    conn = None
    try:
        directory_lock(lock_fd, exclusive=write)
        conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=5)
        validate(conn, planet)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn, root, path
        if write:
            conn.commit()
    except BaseException:
        if write and conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
        os.close(lock_fd)


def append(workspace, planet, agent, responsibility, event_id, result, source, observed_at):
    name(responsibility)
    name(event_id)
    if result not in {"succeeded", "failed", "corrected"}:
        raise ValueError("fact result must be succeeded, failed or corrected")
    moment = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment > datetime.now(timezone.utc):
        raise ValueError("observed_at must be a past timezone-aware instant")
    with opened(workspace, planet, agent, write=True) as (conn, root, _):
        path = within(root, source)
        if not path.is_file() or len(source) > 512:
            raise ValueError("fact requires an existing source inside its planet")
        row = (agent, responsibility, event_id, result, source, file_hash(path), observed_at)
        existing = conn.execute("SELECT * FROM facts WHERE agent=? AND responsibility=? AND event_id=?", row[:3]).fetchone()
        if existing is not None and existing != row:
            raise ValueError("event identity already has different content")
        conn.execute("INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?,?)", row)
        return {"created": existing is None, "event_id": event_id}


def read(workspace, planet, agent, responsibility):
    name(responsibility)
    with opened(workspace, planet, agent) as (conn, root, _):
        rows = conn.execute("SELECT event_id,result,source,source_sha256,observed_at FROM facts WHERE agent=? AND responsibility=? ORDER BY observed_at,event_id", (agent, responsibility)).fetchall()
        fields = ("event_id", "result", "source", "source_sha256", "observed_at")
        facts = []
        for row in rows:
            fact = dict(zip(fields, row))
            path = within(root, fact["source"])
            fact["source_verified"] = path.is_file() and file_hash(path) == fact["source_sha256"]
            facts.append(fact)
        return {"planet": planet, "agent": agent, "responsibility": responsibility, "facts": facts}


def backup(workspace, planet, agent):
    with opened(workspace, planet, agent) as (conn, root, path):
        directory = within(root, ".solar/backups")
        directory.mkdir(parents=True, exist_ok=True)
        fd, target = tempfile.mkstemp(dir=directory, suffix=".sqlite", prefix="facts-")
        os.close(fd)
        try:
            with closing(sqlite3.connect(target)) as copy:
                conn.backup(copy)
                validate(copy, planet)
        except BaseException:
            os.unlink(target)
            raise
    return {"path": str(target), "sha256": file_hash(type(path)(target)), "schema": 1}


def restore_backup(workspace, planet, agent, source, expected_current_sha256):
    root, dest = location(workspace, planet, agent)
    source = within(root, source)
    if not source.is_relative_to(root / ".solar/backups") or not source.is_file():
        raise ValueError("restore source must be an existing planet fact backup")
    with locked_parent(dest):
        if not dest.is_file() or file_hash(dest) != expected_current_sha256:
            raise ValueError("current database changed; restore refused")
        fd, temp = tempfile.mkstemp(dir=dest.parent, prefix=".restore-")
        os.close(fd)
        try:
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
                validate(original, planet)
                with closing(sqlite3.connect(temp)) as copy:
                    original.backup(copy)
                    validate(copy, planet)
            # Never delete the current state to force rollback.
            directory = within(root, ".solar/backups")
            directory.mkdir(parents=True, exist_ok=True)
            preserve_fd, previous = tempfile.mkstemp(dir=directory, prefix="pre-restore-", suffix=".sqlite")
            with os.fdopen(preserve_fd, "wb") as stream:
                stream.write(dest.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            preserved = {"path": previous, "sha256": file_hash(Path(previous))}
            os.replace(temp, dest)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return {"restored": True, "previous_state_backup": preserved}
