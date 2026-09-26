#!/usr/bin/env python3
"""The cutover between the file runtime and `solar-state`: migrate and rollback.

Both hold the exclusive state lock for their whole length and follow the same
steps (plan, decision 10):

    1. stop what Solar starts            -> the caller (hooks), not this module
    2. take the exclusive lock           -> `solar_state.cutover()`
    3. wait for what is already running  -> `in_flight()`
    4. copy the sources aside            -> `pre-state-<stamp>/` / `pre-rollback-<stamp>/`
    5. import / export
    6. verify, or undo and refuse
    7. close: format, then move the old files aside, then release

Nothing here runs by itself. `solar client update` and `solar client sync` call
it after they stop what Solar starts. The entry points still refuse unless
`SOLAR_STATE_ALLOW_CUTOVER=1`, which those commands set for that one call.

Imports nothing but `solar-state` and `solar-paths`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import solar_state as st

ALLOW_ENV = "SOLAR_STATE_ALLOW_CUTOVER"
MARKER_NAME = "state-migration.json"
ROLLBACK_MARKER = "state-rollback.json"
ROLLBACK_STAGING = ".state-rollback-staging"

FOLDERS = {
    "drafts": "draft", "planned": "planned", "queued": "queued", "active": "active",
    "completed": "completed", "error": "error", "archive": "archived", "cancelled": "cancelled",
}
STATUS_FOLDER = {status: folder for folder, status in FOLDERS.items()}
# What moves into async-tasks.migrated-<stamp>/. tmp/, hooks/ and anything
# unknown stay where they are: they are not task state.
TASK_PARTS = (*FOLDERS, "handles", "subtasks", "cancellation", "logs")
LOGS_DIR = "task-logs"
STREAMS = ("events", "shadow")
# Command lines that mean "old Solar code is still running": a script of the
# router or of the queue, however it was called (absolute, relative, bare name).
# Joined at runtime so a process check still sees the script directory, without
# this file importing either skill.
_ROUTER_SKILL = "solar-router"
_QUEUE_SKILL = "solar-async-tasks"
RUNNING_MARKERS = (
    f"skills/{_ROUTER_SKILL}/scripts/", f"skills/{_QUEUE_SKILL}/scripts/",
    "run_router.py", "execute_active.py", "execute_active.sh", "run_worker.sh",
    "create.sh", "task_lib.sh", "start_next.sh", "activate.sh", "complete.sh",
    "approve.sh", "requeue_from_error.sh", "task_cancel.py",
    "reconcile_router_audit.sh", "continuity_cli.py", "delegation_ctl.py",
)
DEFAULT_WAIT_SEC = 300.0


class CutoverRefused(st.StateError):
    """The cutover did not start, or it stopped and left everything as it was."""


def _allowed() -> None:
    if os.environ.get(ALLOW_ENV) != "1":
        raise CutoverRefused(
            f"cutover is disabled until every reader and writer is on solar-state "
            f"(set {ALLOW_ENV}=1 only on a copy of the runtime, or once the plan is complete)")


def _stamp() -> str:
    return st._stamp()  # microseconds: two attempts in one second never collide


def _inside(base: Path, rel: str) -> Path:
    """A destination this cutover may write: under `base`, no traversal, no escape.

    A task id or a source file name is data that once came from a file name, so
    it is never pasted into a path without this.
    """
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        raise CutoverRefused(f"refusing a path that leaves the runtime: {rel!r}")
    root = base.resolve()
    dest = (root / rel).resolve()
    if dest == root or root not in dest.parents:
        raise CutoverRefused(f"refusing a path that leaves the runtime: {rel!r}")
    return base / rel


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

def list_processes() -> list[tuple[int, str]]:
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True,
                         check=False).stdout
    procs = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit():
            procs.append((int(pid), cmd.strip()))
    return procs


def _handle_is_live(handle: dict, procs: dict[int, str]) -> bool:
    """Alive *and* the executor of that task: a reused pid does not count, and a
    handle whose pid is not a number is not a handle."""
    try:
        pid = int(handle.get("pid"))
    except (TypeError, ValueError):
        return False
    task_id = str(handle.get("task_id") or "")
    cmd = procs.get(pid, "")
    return bool(task_id) and "execute_active.py" in cmd and task_id in cmd


def in_flight(root: Path, lister: Callable[[], list[tuple[int, str]]] = list_processes,
              db_active: Iterable[str] = ()) -> list[str]:
    """Reasons not to cut over now. Empty means nothing is running."""
    reasons = []
    tasks = root / "async-tasks"
    active = tasks / "active"
    if active.is_dir():
        for path in sorted(active.glob("*.md")):
            reasons.append(f"task in active/: {path.name} — wait for it or cancel it")
    for task_id in db_active:
        reasons.append(f"task {task_id} is active in the base — wait for it or cancel it")
    procs = {pid: cmd for pid, cmd in lister() if pid != os.getpid()}
    for path in sorted((tasks / "handles").glob("*.json")) if (tasks / "handles").is_dir() else []:
        try:
            handle = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(handle, dict) and _handle_is_live(handle, procs):
            reasons.append(f"executor running for task {handle.get('task_id')} (pid {handle.get('pid')})")
    for pid, cmd in sorted(procs.items()):
        if any(marker in cmd for marker in RUNNING_MARKERS):
            reasons.append(f"Solar process still running: pid {pid} {cmd[:120]}")
    return reasons


def _wait_until_quiet(root: Path, wait: float, lister, db_active=lambda: ()) -> None:
    deadline = time.monotonic() + wait
    while True:
        reasons = in_flight(root, lister, db_active())
        if not reasons:
            return
        if time.monotonic() >= deadline:
            raise CutoverRefused("still running after waiting:\n- " + "\n- ".join(reasons))
        time.sleep(min(2.0, max(0.05, wait / 50)))


# ---------------------------------------------------------------------------
# Census: what the file runtime holds
# ---------------------------------------------------------------------------

@dataclass
class Census:
    tasks: list[tuple[str, Path]] = field(default_factory=list)      # (status, file)
    logs: dict[str, str] = field(default_factory=dict)               # name -> sha256
    subtask_plans: dict[str, str] = field(default_factory=dict)      # parent -> text
    cancellations: list[str] = field(default_factory=list)
    audit: list[str] = field(default_factory=list)
    audit_present: bool = False
    continuity: Optional[str] = None
    events: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for status, _ in self.tasks:
            out[status] = out.get(status, 0) + 1
        return dict(sorted(out.items()))


def census(root: Path) -> Census:
    c = Census()
    tasks = root / "async-tasks"
    for folder, status in FOLDERS.items():
        for path in sorted((tasks / folder).glob("*.md")) if (tasks / folder).is_dir() else []:
            c.tasks.append((status, path))
    for path in sorted((tasks / "logs").glob("*")) if (tasks / "logs").is_dir() else []:
        if path.is_file():
            c.logs[path.name] = _sha(path)
    for path in sorted((tasks / "subtasks").glob("*.json")) if (tasks / "subtasks").is_dir() else []:
        c.subtask_plans[path.stem] = path.read_text(encoding="utf-8")
    for path in sorted((tasks / "cancellation").glob("*.json")) if (tasks / "cancellation").is_dir() else []:
        c.cancellations.append(path.stem)
    audit = root / "router" / "audit.jsonl"
    if audit.is_file():
        c.audit, c.audit_present = _lines(audit), True
    continuity = root / "continuity" / "active.json"
    if continuity.is_file():
        c.continuity = continuity.read_text(encoding="utf-8")
    delegations = root / "delegations"
    for mandate in sorted(p for p in delegations.iterdir() if p.is_dir()) if delegations.is_dir() else []:
        for stream in STREAMS:
            path = mandate / f"{stream}.jsonl"
            if path.is_file():
                c.events[(mandate.name, stream)] = _lines(path)
    return c


def _expected_export(path: Path, status: str) -> str:
    """The original document, with the status the folder gives it."""
    text = path.read_text(encoding="utf-8")
    pairs, body = st.parse_task_document(text)
    declared = st.value_of(dict(pairs).get("status"))
    if declared == status:
        return text
    for pair in pairs:
        if pair[0] == "status":
            pair[1] = f" {status}"
            break
    else:
        pairs.append(["status", f" {status}"])
    return st.render_task_document(pairs, body)


# ---------------------------------------------------------------------------
# Import and verification
# ---------------------------------------------------------------------------

def _import(session: st.Session, root: Path, c: Census) -> list[str]:
    """Load the census into an empty base. Returns warnings (not failures)."""
    warnings = []
    for status, path in c.tasks:
        log_name = f"{path.stem}.log"
        session.task_import(path.read_text(encoding="utf-8"), status=status,
                            log_path=f"{LOGS_DIR}/{log_name}" if log_name in c.logs else None,
                            source_name=path.name)
    warnings += _link_children(session, [t["id"] for t in session.task_list()])
    for parent, text in c.subtask_plans.items():
        session.subtask_plan_import_text(parent, text)
    for task_id in c.cancellations:
        session.cancellation_request(task_id)
    if c.audit_present:
        session.audit_file_register()
    for line in c.audit:
        session.audit_import_line(line)
    if c.continuity is not None:
        session.continuity_import_text(c.continuity)
    for (mandate, stream), lines in c.events.items():
        session.delegation_stream_register(mandate, stream)
        for line in lines:
            session.delegation_event_import_line(mandate, stream, line)
    return warnings


def _verify(session: st.Session, root: Path, c: Census, logs_dir: Path) -> list[str]:
    problems = []
    counts = session.counts()["tasks"]
    if counts != c.counts():
        problems.append(f"tasks per status: base {counts} vs files {c.counts()}")
    for status, path in c.tasks:
        pairs, _ = st.parse_task_document(path.read_text(encoding="utf-8"))
        task_id = st.value_of(dict(pairs)["id"])
        if session.task_export(task_id) != _expected_export(path, status):
            problems.append(f"{path.name}: export differs from the original")
    if session.audit_lines() != c.audit:
        problems.append(f"audit: {len(session.audit_lines())} lines vs {len(c.audit)}")
    if session.continuity_text() != c.continuity:
        problems.append("continuity differs")
    if sorted(session.delegation_streams()) != sorted(c.events):
        problems.append("mandate streams differ")
    for (mandate, stream), lines in c.events.items():
        if session.delegation_event_lines(mandate, stream) != lines:
            problems.append(f"mandate events {mandate}/{stream} differ")
    for parent, text in c.subtask_plans.items():
        if session.subtask_plan_text(parent) != text:
            problems.append(f"subtask plan {parent} differs")
    if sorted(session.cancellation_ids()) != sorted(c.cancellations):
        problems.append("cancellation requests differ")
    for name, digest in c.logs.items():
        copy = logs_dir / name
        if not copy.is_file() or _sha(copy) != digest:
            problems.append(f"log {name}: copy missing or different")
    return problems


def _build_base(root: Path, c: Census, work: Path) -> tuple[Path, list[str], list[str]]:
    """Import into a throwaway base under `work`, copy the logs, verify.
    Returns (base file, warnings, problems)."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    with st.cutover(work) as cut:
        cut.upgrade_schema()
        session = cut.session()
        try:
            logs_dir = work / LOGS_DIR
            logs_dir.mkdir()
            for name in c.logs:
                shutil.copy2(root / "async-tasks" / "logs" / name, logs_dir / name)
            warnings = _import(session, root, c)
            problems = _verify(session, root, c, logs_dir)
            session.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            session.conn.close()
    return work / st.DB_NAME, warnings, problems


def _place_base(built: Path, root: Path) -> None:
    """Copy the built base into place with the backup API (WAL-safe), then swap."""
    target = st.db_path(root)
    partial = target.with_name(f".{target.name}.placing")
    src = sqlite3.connect(f"file:{built}?mode=ro", uri=True)
    dst = sqlite3.connect(str(partial))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for leftover in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
        leftover.unlink(missing_ok=True)
    os.replace(partial, target)


def _drop_base(root: Path) -> None:
    for name in (st.DB_NAME, st.DB_NAME + "-wal", st.DB_NAME + "-shm"):
        (root / name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Moving the old files aside (the last step, and resumable)
# ---------------------------------------------------------------------------

def _aside(path: Path, stamp: str) -> Path:
    return path.with_name(f"{path.name}.migrated-{stamp}")


def _move_old_files(root: Path, stamp: str) -> list[str]:
    moved = []
    tasks = root / "async-tasks"
    holder = root / f"async-tasks.migrated-{stamp}"
    for part in TASK_PARTS:
        src = tasks / part
        if src.exists():
            holder.mkdir(exist_ok=True)
            os.replace(src, holder / part)
            moved.append(f"async-tasks/{part}")
    singles = [root / "router" / "audit.jsonl", root / "continuity" / "active.json"]
    delegations = root / "delegations"
    if delegations.is_dir():
        singles += [m / f"{s}.jsonl" for m in sorted(delegations.iterdir()) if m.is_dir() for s in STREAMS]
    for src in singles:
        if src.exists():
            os.replace(src, _aside(src, stamp))
            moved.append(str(src.relative_to(root)))
    return moved


def _marker(root: Path) -> Path:
    return root / MARKER_NAME


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def rehearse(root: Optional[Path] = None, work: Optional[Path] = None) -> dict:
    """Steps 4–6 against a copy, without the lock and without touching the
    runtime: import into a throwaway base and verify. Safe on a live runtime."""
    base = st._root(root)
    scratch = Path(work) if work else Path(tempfile.mkdtemp(prefix="solar-state-rehearsal-"))
    c = census(base)
    try:
        _, warnings, problems = _build_base(base, c, scratch / "base")
    finally:
        shutil.rmtree(scratch if not work else scratch / "base", ignore_errors=True)
    return dict(tasks=c.counts(), logs=len(c.logs), audit=len(c.audit),
                mandate_events=sum(map(len, c.events.values())),
                subtask_plans=len(c.subtask_plans), warnings=warnings, problems=problems,
                ok=not problems)


def _failer(_fail_at: Optional[str]):
    """Test hook. `step` raises (the cleanup code runs); `kill:step` exits the
    process on the spot, like a SIGKILL (nothing runs)."""
    def fail(step: str) -> None:
        if _fail_at == step:
            raise RuntimeError(f"simulated crash at {step}")
        if _fail_at == f"kill:{step}":
            os._exit(9)
    return fail


def _is_stamp(stamp: str) -> bool:
    """`solar_state._stamp()` is YYYYMMDDTHHMMSSFFFFFFZ, one path segment."""
    return (len(stamp) == 22 and stamp[8] == "T" and stamp.endswith("Z")
            and stamp[:8].isdigit() and stamp[9:21].isdigit())


def _check_migrated_base(base: Path) -> str:
    """Before trusting STATE_FORMAT=sqlite: the marker, the base and its schema."""
    marker = _marker(base)
    if not marker.is_file():
        raise CutoverRefused("format says sqlite but there is no migration marker: refusing to move files")
    try:
        stamp = json.loads(marker.read_text(encoding="utf-8"))["stamp"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise CutoverRefused(f"the migration marker is unreadable ({exc}): refusing to move files") from None
    if not isinstance(stamp, str) or not stamp.strip():
        raise CutoverRefused("the migration marker has no stamp: refusing to move files")
    if not _is_stamp(stamp):
        raise CutoverRefused(f"migration stamp {stamp!r} is not one this cutover writes: "
                             "refusing to move files")
    path = st.db_path(base)
    if not path.is_file():
        raise CutoverRefused("format says sqlite but the base is missing: refusing to move files")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise CutoverRefused(f"the base is unreadable ({exc})") from None
    try:
        if st._schema_version(conn) != st.SCHEMA_VERSION:
            raise CutoverRefused(f"base schema v{st._schema_version(conn)}, "
                                 f"this code speaks v{st.SCHEMA_VERSION}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CutoverRefused("the base does not pass its integrity check")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = {"tasks", "task_links", "task_events", "audit", "audit_source", "continuity",
                   "delegation_events", "delegation_streams", "subtask_plans",
                   "cancellation_requests", "statuses", "transitions"} - tables
        if missing:
            raise CutoverRefused(f"the base is missing tables: {', '.join(sorted(missing))}")
    except sqlite3.Error as exc:
        raise CutoverRefused(f"the base is unreadable ({exc})") from None
    finally:
        conn.close()
    return stamp


def _append_tail(have: list[str], found: list[str], what: str, changed: list[str]) -> list[str]:
    """Lines written to a file after the base took over. Only a clean continuation
    is accepted: shorter, truncated or rewritten goes to `changed`."""
    if found[:len(have)] != have:
        changed.append(f"{what} is not a plain continuation of what the base holds "
                       f"({len(found)} lines in the file, {len(have)} in the base)")
        return []
    return found[len(have):]


def _link_children(session: st.Session, task_ids: Iterable[str]) -> list[str]:
    """`subtask_ids: "key=id,key=id"` in the frontmatter is the parent-child record."""
    warnings = []
    known = {r[0] for r in session.conn.execute("SELECT id FROM tasks")}
    for task_id in task_ids:
        task = session.task_get(task_id)
        raw = st.value_of(dict(task["frontmatter"]).get("subtask_ids")) or ""
        for item in filter(None, (part.strip() for part in raw.split(","))):
            key, _, child = item.partition("=")
            child = child.strip()
            if child in known:
                session.task_link(task_id, child, key.strip() or None)
            else:
                warnings.append(f"{task_id}: child {child!r} is not among the tasks")
    return warnings


def _kept_source(base: Path, rel: str, stamp: str) -> bool:
    """True when `rel` is still in place, or this cutover already moved it aside."""
    live = base / rel
    if rel.startswith("async-tasks/"):
        aside = base / f"async-tasks.migrated-{stamp}" / rel[len("async-tasks/"):]
    else:
        aside = _aside(live, stamp)
    return live.is_file() or aside.is_file()


def _note_missing_sources(session: st.Session, base: Path, stamp: str, changed: list[str]) -> None:
    """A source the base holds must still be on disk: live, or already renamed
    `*.migrated-<stamp>`. Gone from both means someone deleted it."""
    rels = []
    for task in session.task_list():
        folder = STATUS_FOLDER[task["status"]]
        name = task["source_name"] or f"{task['id']}.md"
        rels.append(f"async-tasks/{folder}/{name}")
    for parent in session.subtask_plan_parents():
        rels.append(f"async-tasks/subtasks/{parent}.json")
    for task_id in session.cancellation_ids():
        rels.append(f"async-tasks/cancellation/{task_id}.json")
    logs = base / LOGS_DIR
    for path in sorted(logs.glob("*")) if logs.is_dir() else []:
        if path.is_file():
            rels.append(f"async-tasks/logs/{path.name}")
    if session.audit_lines() or session.audit_file_present():
        rels.append("router/audit.jsonl")
    if session.continuity_text() is not None:
        rels.append("continuity/active.json")
    for mandate, stream in session.delegation_streams():
        rels.append(f"delegations/{mandate}/{stream}.jsonl")
    for rel in rels:
        if not _kept_source(base, rel, stamp):
            changed.append(f"{rel} is neither in place nor set aside")


def _catch_up(session: st.Session, base: Path, c: Census, stamp: str) -> dict:
    """What the files hold after the base took over: bring in what is new, refuse
    anything that changed or disappeared. Nothing is moved aside unnoticed."""
    added = dict(tasks=0, logs=0, audit=0, mandate_events=0)
    changed: list[str] = []
    _note_missing_sources(session, base, stamp, changed)
    logs = base / LOGS_DIR
    logs.mkdir(exist_ok=True)
    for name, digest in c.logs.items():
        copy = logs / name
        if not copy.exists():
            shutil.copy2(base / "async-tasks" / "logs" / name, copy)
            added["logs"] += 1
        elif _sha(copy) != digest:
            changed.append(f"log {name} differs from task-logs/{name}")

    known = {r[0] for r in session.conn.execute("SELECT id FROM tasks")}
    for status, path in c.tasks:
        text = path.read_text(encoding="utf-8")
        pairs, _ = st.parse_task_document(text)
        task_id = st.value_of(dict(pairs).get("id"))
        if task_id in known:
            if session.task_export(task_id) != _expected_export(path, status):
                changed.append(f"{path.name} changed after the migration")
            continue
        log_name = f"{path.stem}.log"
        session.task_import(text, status=status, source_name=path.name,
                            log_path=f"{LOGS_DIR}/{log_name}" if log_name in c.logs else None)
        added["tasks"] += 1

    for parent, text in c.subtask_plans.items():
        stored = session.subtask_plan_text(parent)
        if stored is None:
            session.subtask_plan_import_text(parent, text)
        elif stored != text:
            changed.append(f"subtask plan {parent}.json changed after the migration")
    for task_id in c.cancellations:
        session.cancellation_request(task_id)

    audit_tail: list[str] = []
    if c.audit_present:
        audit_tail = _append_tail(session.audit_lines(), c.audit, "router/audit.jsonl", changed)
    stream_tails = {}
    for (mandate, stream), lines in c.events.items():
        session.delegation_stream_register(mandate, stream)
        stream_tails[(mandate, stream)] = _append_tail(
            session.delegation_event_lines(mandate, stream), lines,
            f"delegations/{mandate}/{stream}.jsonl", changed)
    if c.continuity is not None and c.continuity != session.continuity_text():
        changed.append("continuity/active.json changed after the migration")
    if changed:
        raise CutoverRefused("the files changed after the migration; decide by hand:\n- "
                             + "\n- ".join(changed))

    for line in audit_tail:
        session.audit_import_line(line)
        added["audit"] += 1
    for (mandate, stream), tail in stream_tails.items():
        for line in tail:
            session.delegation_event_import_line(mandate, stream, line)
            added["mandate_events"] += 1
    # Every task, not only the ones just imported: a parent already in the base
    # may name a child that arrived with this resume. task_link replaces, so
    # running it again does not duplicate the rows from the first import.
    added["warnings"] = _link_children(session, [row["id"] for row in session.task_list()])
    return added


def migrate(root: Optional[Path] = None, wait: float = DEFAULT_WAIT_SEC,
            lister: Callable[[], list[tuple[int, str]]] = list_processes,
            _fail_at: Optional[str] = None) -> dict:
    """Files -> base. The caller has stopped what Solar starts (step 1)."""
    _allowed()
    base = st._root(root)
    fail = _failer(_fail_at)

    with st.cutover(base, timeout=wait) as cut:
        if st.read_format(base) == st.FORMAT_SQLITE:
            # A migration that already changed the format: finish it, never blindly.
            stamp = _check_migrated_base(base)
            _wait_until_quiet(base, wait, lister)
            session = cut.session()
            try:
                added = _catch_up(session, base, census(base), stamp)
            finally:
                session.conn.close()
            moved = _move_old_files(base, stamp)
            return dict(already=True, moved=moved, caught_up=added)

        _wait_until_quiet(base, wait, lister)
        stamp = _stamp()
        c = census(base)

        backup = base / f"pre-state-{stamp}"
        backup.mkdir()
        for rel in ("async-tasks", "router/audit.jsonl", "continuity", "delegations"):
            src = base / rel
            if src.is_dir():
                shutil.copytree(src, backup / rel)
            elif src.is_file():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, backup / rel)
        fail("after-copy")

        _drop_base(base)  # a base left by an earlier attempt is never trusted
        work = base / ".state-import"
        built, warnings, problems = _build_base(base, c, work)
        fail("after-import")
        if problems:
            shutil.rmtree(work, ignore_errors=True)
            raise CutoverRefused("verification failed, nothing changed:\n- " + "\n- ".join(problems))

        logs_target = base / LOGS_DIR
        if logs_target.exists():
            shutil.rmtree(logs_target)
        shutil.copytree(work / LOGS_DIR, logs_target)
        _place_base(built, base)
        shutil.rmtree(work, ignore_errors=True)
        fail("after-place")

        _marker(base).write_text(json.dumps({"stamp": stamp}), encoding="utf-8")
        cut.set_format(st.FORMAT_SQLITE)
        fail("after-format")
        moved = _move_old_files(base, stamp)
        return dict(already=False, stamp=stamp, tasks=c.counts(), logs=len(c.logs),
                    audit=len(c.audit), mandate_events=sum(map(len, c.events.values())),
                    backup=str(backup), moved=moved, warnings=warnings)


def _undo_placed(base: Path) -> None:
    """Remove what a killed rollback put in place — only files that are still
    byte for byte what it wrote. Anything else refuses."""
    marker = base / ROLLBACK_MARKER
    if not marker.is_file():
        return
    try:
        planned = json.loads(marker.read_text(encoding="utf-8"))["planned"]
        assert isinstance(planned, dict)
    except (OSError, ValueError, TypeError, KeyError, AssertionError) as exc:
        raise CutoverRefused(f"the rollback marker is unreadable ({exc}): clean it up by hand") from None
    for rel in planned:
        _inside(base, rel)
    changed = [rel for rel, digest in planned.items()
               if (base / rel).is_file() and _sha(base / rel) != digest]
    if changed:
        raise CutoverRefused("a killed rollback left files that have changed since:\n- " + "\n- ".join(changed))
    for rel in planned:
        (base / rel).unlink(missing_ok=True)
    marker.unlink()


def _finish_rollback(base: Path) -> None:
    _drop_base(base)
    shutil.rmtree(base / ROLLBACK_STAGING, ignore_errors=True)
    _marker(base).unlink(missing_ok=True)
    (base / ROLLBACK_MARKER).unlink(missing_ok=True)


def rollback(root: Optional[Path] = None, wait: float = DEFAULT_WAIT_SEC,
             lister: Callable[[], list[tuple[int, str]]] = list_processes,
             _fail_at: Optional[str] = None) -> dict:
    """Base -> files. The caller has stopped what Solar starts and will go back
    to the previous version after this returns.

    Everything is written to a staging folder and verified there first. Only
    then the files move into place, with a marker listing each one and its
    hash, so a rollback killed halfway can be undone and run again."""
    _allowed()
    base = st._root(root)
    fail = _failer(_fail_at)
    fmt = st.read_format(base)

    if fmt == st.FORMAT_FILES and (base / ROLLBACK_MARKER).is_file():
        with st.cutover(base, timeout=wait):   # killed after the format changed: finish
            _finish_rollback(base)
        return dict(already=True)
    if fmt != st.FORMAT_SQLITE:
        raise CutoverRefused(f"format is {fmt or 'unset'}: nothing to roll back")

    with st.cutover(base, timeout=wait) as cut:
        session = cut.session()
        try:
            active = lambda: [r[0] for r in session.conn.execute(  # noqa: E731
                "SELECT id FROM tasks WHERE status = 'active'")]
            _wait_until_quiet(base, wait, lister, active)
            _undo_placed(base)                                   # leftovers of a killed attempt
            staging = base / ROLLBACK_STAGING
            shutil.rmtree(staging, ignore_errors=True)
            stamp = _stamp()

            # Every file the rollback will write, as (relative path, source).
            entries: list[tuple[str, object]] = []
            expected: dict[str, int] = {}
            for task in session.task_list():
                folder = STATUS_FOLDER[task["status"]]
                name = task["source_name"] or f"{task['id']}.md"
                entries.append((f"async-tasks/{folder}/{name}", session.task_export(task["id"])))
                expected[folder] = expected.get(folder, 0) + 1
            for parent in session.subtask_plan_parents():
                entries.append((f"async-tasks/subtasks/{parent}.json", session.subtask_plan_text(parent)))
            for task_id in session.cancellation_ids():
                entries.append((f"async-tasks/cancellation/{task_id}.json",
                                json.dumps({"task_id": task_id, "status": "cancellation_requested"})))
            logs_src = base / LOGS_DIR
            for path in sorted(logs_src.glob("*")) if logs_src.is_dir() else []:
                if path.is_file():
                    entries.append((f"async-tasks/logs/{path.name}", path))
            lines = session.audit_lines()
            if lines or session.audit_file_present():
                entries.append(("router/audit.jsonl", "".join(f"{l}\n" for l in lines)))
            text = session.continuity_text()
            if text is not None:
                entries.append(("continuity/active.json", text))
            for mandate, stream in session.delegation_streams():   # an empty stream comes back empty
                ev = session.delegation_event_lines(mandate, stream)
                entries.append((f"delegations/{mandate}/{stream}.jsonl", "".join(f"{l}\n" for l in ev)))

            # Ids and file names came from disk once: they are data, not paths.
            seen: dict[str, str] = {}
            for rel, _ in entries:
                _inside(base, rel)
                _inside(staging, rel)
                if rel in seen:
                    raise CutoverRefused(f"two rows would write the same file: {rel}")
                seen[rel] = rel
            occupied = [rel for rel, _ in entries if (base / rel).exists()]
            if occupied:
                raise CutoverRefused("would overwrite files that exist:\n- " + "\n- ".join(occupied))

            backup = base / f"pre-rollback-{stamp}"
            backup.mkdir()
            st._backup_to(session.conn, backup, st.DB_NAME)

            for rel, src in entries:
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(src, Path):
                    shutil.copy2(src, dest)
                else:
                    dest.write_text(src, encoding="utf-8")
            fail("after-export")

            problems = []
            for folder, count in expected.items():
                found = len(list((staging / "async-tasks" / folder).glob("*.md")))
                if found != count:
                    problems.append(f"{folder}/: {found} files, base has {count}")
            for rel, src in entries:
                if isinstance(src, Path) and _sha(staging / rel) != _sha(src):
                    problems.append(f"{rel} differs")
            if lines and _lines(staging / "router" / "audit.jsonl") != lines:
                problems.append("audit differs")
            if problems:
                raise CutoverRefused("verification failed:\n- " + "\n- ".join(problems))

            planned = {rel: _sha(staging / rel) for rel, _ in entries}
            (base / ROLLBACK_MARKER).write_text(json.dumps({"stamp": stamp, "planned": planned}),
                                                encoding="utf-8")
            for i, (rel, _) in enumerate(entries):
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging / rel, base / rel)
                if i == len(entries) // 2:
                    fail("mid-place")
        except BaseException:
            # A normal failure cleans up here; a kill is cleaned up by the next run.
            try:
                _undo_placed(base)
            finally:
                shutil.rmtree(base / ROLLBACK_STAGING, ignore_errors=True)
            raise
        finally:
            session.conn.close()

        cut.set_format(st.FORMAT_FILES)
        fail("after-format")
        _finish_rollback(base)
        return dict(already=False, stamp=stamp, tasks=expected, logs=len(list(logs_src.glob("*"))),
                    audit=len(lines), backup=str(backup))


def _cli(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="solar_state_cutover.py",
                                     description="Cutover between the file runtime and solar-state.")
    parser.add_argument("--root", default=None, help="runtime root (default: solar-paths)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rehearse", help="import into a throwaway base and verify; touches nothing")
    for name in ("migrate", "rollback"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--wait", type=float, default=DEFAULT_WAIT_SEC)
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else None
    try:
        if args.cmd == "rehearse":
            result = rehearse(root)
        elif args.cmd == "migrate":
            result = migrate(root, wait=args.wait)
        else:
            result = rollback(root, wait=args.wait)
    except st.StateError as exc:
        print(json.dumps(dict(error=type(exc).__name__, detail=str(exc)), ensure_ascii=False),
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
