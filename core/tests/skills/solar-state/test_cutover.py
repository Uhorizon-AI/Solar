"""Cutover between the file runtime and solar-state: migrate, rollback, rehearse."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import solar_state as st
import solar_state_cutover as cut

_SCRIPT = Path(cut.__file__)

AUDIT = ['{"ts": "t1",  "event":"start", "router_id":"r1", "nota":"ñ"}',
         '{"router_id": "r1", "event": "end", "ts": "t2"}']
CONTINUITY = '{\n  "active_task": "x",\n  "channels_seen": ["telegram"]\n}\n'


def _task(tid: str, status: str, extra: str = "", title: str = "t") -> str:
    return f'---\nid: "{tid}"\ntitle: "{title}"\nstatus: {status}\npriority: normal\n{extra}---\n\n# {title}\n'


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A file runtime shaped like the real one."""
    root = tmp_path / "runtime"
    tasks = root / "async-tasks"
    _write(tasks / "completed" / "parent-task.md",
           _task("p1", "completed", 'subtask_ids: "a=c1,b=c2"\n', "Parent"))
    _write(tasks / "completed" / "child-one.md", _task("c1", "completed", 'parent_task_id: "p1"\n'))
    _write(tasks / "completed" / "child-two.md", _task("c2", "completed", 'parent_task_id: "p1"\n'))
    _write(tasks / "drafts" / "a-draft.md", _task("d1", "draft"))
    _write(tasks / "queued" / "queued-one.md", _task("q1", "queued", 'origin_channel: telegram\n'))
    _write(tasks / "archive" / "old-recurring.md", _task("r1", "queued", "recurring: true\n"))  # folder wins
    _write(tasks / "error" / "broken.md", _task("e1", "error"))
    _write(tasks / "logs" / "parent-task.log", "log of the parent\n")
    _write(tasks / "logs" / "orphan.log", "a log without a task\n")
    _write(tasks / "subtasks" / "p1.json", '[\n  {"title": "A", "provider": "codex"}\n]')
    _write(tasks / "cancellation" / "q1.json", json.dumps({"task_id": "q1", "status": "cancellation_requested"}))
    _write(tasks / "handles" / "p1.json", json.dumps({"pid": 999999, "task_id": "p1"}))
    _write(tasks / "tmp" / "scratch.md", "not a task\n")
    _write(tasks / "hooks" / "chrome" / "pre_start.sh", "#!/bin/sh\n")
    _write(root / "router" / "audit.jsonl", "".join(f"{l}\n" for l in AUDIT))
    _write(root / "router" / "conversations" / "c.jsonl", "private to the router\n")
    _write(root / "continuity" / "active.json", CONTINUITY)
    _write(root / "delegations" / "example-mandate" / "events.jsonl", '{ "ts": "e1" }\n')
    _write(root / "delegations" / "example-mandate" / "shadow.jsonl", '{"ts": "s1", "ok": true}\n')
    _write(root / "delegations" / "quiet-mandate" / "events.jsonl", "")   # exists, empty
    monkeypatch.setenv(cut.ALLOW_ENV, "1")
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(root))
    from runtime_owner import claim_test_owner
    claim_test_owner(root, tmp_path / "workspace", monkeypatch=monkeypatch)
    return root


def quiet():
    return []


def _snapshot(root: Path) -> dict[str, str]:
    """What a rollback must give back (handles of dead processes are dropped)."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_file() and not rel.startswith(("async-tasks/handles", "async-tasks/tmp",
                                                  "async-tasks/hooks", "router/conversations")):
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _source_snapshot(root: Path) -> dict[str, str]:
    snap = _snapshot(root)
    return {k: v for k, v in snap.items()
            if k.startswith(("async-tasks/", "router/audit.jsonl", "continuity/active.json", "delegations/"))
            and ".migrated-" not in k}


# --- gate --------------------------------------------------------------------

def test_cutover_is_disabled_by_default(runtime, monkeypatch):
    monkeypatch.delenv(cut.ALLOW_ENV)
    with pytest.raises(cut.CutoverRefused, match="disabled"):
        cut.migrate(runtime, lister=quiet)
    assert st.read_format(runtime) is None


def test_cutover_imports_only_its_own_skill():
    source = _SCRIPT.read_text(encoding="utf-8")
    assert set(re.findall(r"skills/(solar-[a-z-]+)", source)) <= {"solar-router", "solar-async-tasks"}
    imports = set(re.findall(r"^import (\w+)|^from (\w+)", source, re.M))
    names = {a or b for a, b in imports}
    assert names <= {"__future__", "hashlib", "json", "os", "shutil", "sqlite3", "subprocess", "sys",
                     "tempfile", "time", "dataclasses", "pathlib", "typing", "solar_state", "argparse"}


# --- migrate -----------------------------------------------------------------

def test_migrate_moves_everything_into_the_base(runtime):
    before = _source_snapshot(runtime)
    result = cut.migrate(runtime, lister=quiet)

    assert st.read_format(runtime) == st.FORMAT_SQLITE
    assert result["tasks"] == {"archived": 1, "completed": 3, "draft": 1, "error": 1, "queued": 1}
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_get("r1")["status"] == "archived"                    # the folder wins
        assert "\nstatus: archived\n" in s.task_export("r1")
        assert s.task_get("p1")["log_path"] == "task-logs/parent-task.log"
        assert s.task_get("p1")["source_name"] == "parent-task.md"
        assert s.task_children("p1") == [{"child_id": "c1", "subtask_key": "a"},
                                         {"child_id": "c2", "subtask_key": "b"}]
        assert s.subtask_plan_text("p1") == '[\n  {"title": "A", "provider": "codex"}\n]'
        assert s.cancellation_ids() == ["q1"]
        assert s.audit_lines() == AUDIT
        assert s.continuity_text() == CONTINUITY
        assert s.delegation_event_lines("example-mandate", "events") == ['{ "ts": "e1" }']

    stamp = result["stamp"]
    holder = runtime / f"async-tasks.migrated-{stamp}"
    assert (holder / "completed" / "parent-task.md").is_file()
    assert (runtime / "async-tasks" / "tmp" / "scratch.md").is_file()              # stays
    assert (runtime / "async-tasks" / "hooks" / "chrome" / "pre_start.sh").is_file()  # stays
    assert not (runtime / "router" / "audit.jsonl").exists()
    assert (runtime / "router" / f"audit.jsonl.migrated-{stamp}").is_file()
    assert (runtime / "router" / "conversations" / "c.jsonl").is_file()           # private, stays
    assert (runtime / "continuity" / f"active.json.migrated-{stamp}").is_file()
    assert (runtime / "task-logs" / "orphan.log").read_text() == "a log without a task\n"

    copy = runtime / f"pre-state-{stamp}"
    assert _source_snapshot(copy) == before


def test_rollback_gives_back_the_original_tree(runtime):
    before = _source_snapshot(runtime)
    cut.migrate(runtime, lister=quiet)
    result = cut.rollback(runtime, lister=quiet)

    assert st.read_format(runtime) == st.FORMAT_FILES
    assert not st.db_path(runtime).exists()
    after = _source_snapshot(runtime)
    fixed = runtime / "async-tasks" / "archive" / "old-recurring.md"
    assert "\nstatus: archived\n" in fixed.read_text()          # the corrected status survives
    before.pop("async-tasks/archive/old-recurring.md")
    after.pop("async-tasks/archive/old-recurring.md")
    assert after == before
    assert Path(result["backup"], st.DB_NAME).is_file()


def test_migrate_after_a_rollback_works_again(runtime):
    cut.migrate(runtime, lister=quiet)
    cut.rollback(runtime, lister=quiet)
    result = cut.migrate(runtime, lister=quiet)
    assert result["already"] is False
    with st.session(runtime, auto_backup=False) as s:
        assert sum(s.counts()["tasks"].values()) == 7


@pytest.mark.parametrize("step", ["after-copy", "after-import", "after-place", "after-format"])
def test_a_migration_killed_at_any_step_completes_when_run_again(runtime, step):
    with pytest.raises(RuntimeError, match=step):
        cut.migrate(runtime, lister=quiet, _fail_at=step)
    if step != "after-format":
        assert st.read_format(runtime) != st.FORMAT_SQLITE
        with pytest.raises(st.StateUnavailable):
            with st.session(runtime):
                pass
        assert (runtime / "async-tasks" / "completed" / "parent-task.md").is_file()  # untouched

    cut.migrate(runtime, lister=quiet)
    assert st.read_format(runtime) == st.FORMAT_SQLITE
    with st.session(runtime, auto_backup=False) as s:
        assert s.counts()["tasks"] == {"archived": 1, "completed": 3, "draft": 1, "error": 1, "queued": 1}
        assert s.audit_lines() == AUDIT
    assert not (runtime / "async-tasks" / "completed").exists()
    assert not (runtime / ".state-import").exists()


def test_a_failed_verification_changes_nothing(runtime, monkeypatch):
    before = _source_snapshot(runtime)
    monkeypatch.setattr(cut, "_verify", lambda *a: ["export differs"])
    with pytest.raises(cut.CutoverRefused, match="nothing changed"):
        cut.migrate(runtime, lister=quiet)
    assert st.read_format(runtime) is None
    assert not st.db_path(runtime).exists()
    assert _source_snapshot(runtime) == before


def test_migrating_twice_only_finishes_what_is_pending(runtime):
    cut.migrate(runtime, lister=quiet)
    again = cut.migrate(runtime, lister=quiet)
    assert again["already"] is True and again["moved"] == []
    assert again["caught_up"] == {"tasks": 0, "logs": 0, "audit": 0, "mandate_events": 0,
                                  "warnings": []}


# --- what blocks a cutover ---------------------------------------------------

def test_an_active_task_blocks_the_migration(runtime):
    _write(runtime / "async-tasks" / "active" / "running.md", _task("a1", "active"))
    with pytest.raises(cut.CutoverRefused, match="running.md"):
        cut.migrate(runtime, wait=0.1, lister=quiet)
    assert st.read_format(runtime) is None


def test_a_live_executor_blocks_but_a_reused_pid_does_not(runtime):
    _write(runtime / "async-tasks" / "handles" / "q1.json", json.dumps({"pid": 4242, "task_id": "q1"}))
    live = lambda: [(4242, "python3 /x/core/skills/solar-async-tasks/scripts/execute_active.py f q1")]  # noqa: E731
    reused = lambda: [(4242, "/Applications/Some.app/Contents/MacOS/Some")]  # noqa: E731
    with pytest.raises(cut.CutoverRefused, match="executor running for task q1"):
        cut.migrate(runtime, wait=0.1, lister=live)
    assert cut.in_flight(runtime, reused) == []
    assert cut.migrate(runtime, wait=0.1, lister=reused)["already"] is False


def test_old_solar_code_still_running_blocks(runtime):
    running = lambda: [(77, "python3 /home/u/.local/share/solar/core/skills/solar-router/scripts/run_router.py")]  # noqa: E731
    with pytest.raises(cut.CutoverRefused, match="pid 77"):
        cut.migrate(runtime, wait=0.1, lister=running)


def test_rollback_refuses_to_overwrite_files(runtime):
    cut.migrate(runtime, lister=quiet)
    _write(runtime / "router" / "audit.jsonl", '{"event": "written after the migration"}\n')
    with pytest.raises(cut.CutoverRefused, match="router/audit.jsonl"):
        cut.rollback(runtime, lister=quiet)
    assert st.read_format(runtime) == st.FORMAT_SQLITE


def test_a_rollback_killed_during_export_leaves_the_base_as_truth(runtime):
    cut.migrate(runtime, lister=quiet)
    with pytest.raises(RuntimeError, match="after-export"):
        cut.rollback(runtime, lister=quiet, _fail_at="after-export")
    assert st.read_format(runtime) == st.FORMAT_SQLITE
    assert not list((runtime / "async-tasks").rglob("*.md")) or \
        all("tmp" in p.parts for p in (runtime / "async-tasks").rglob("*.md"))
    with st.session(runtime, auto_backup=False) as s:
        assert sum(s.counts()["tasks"].values()) == 7
    cut.rollback(runtime, lister=quiet)
    assert st.read_format(runtime) == st.FORMAT_FILES


# --- rehearsal ---------------------------------------------------------------

def test_rehearsal_verifies_without_touching_the_runtime(runtime, monkeypatch):
    monkeypatch.delenv(cut.ALLOW_ENV)          # a rehearsal does not need the gate
    before = {str(p.relative_to(runtime)): p.stat().st_mtime_ns for p in runtime.rglob("*")}
    result = cut.rehearse(runtime)
    after = {str(p.relative_to(runtime)): p.stat().st_mtime_ns for p in runtime.rglob("*")}
    assert result["ok"] and result["problems"] == []
    assert result["tasks"]["completed"] == 3 and result["audit"] == 2
    assert after == before


def test_cli(runtime, monkeypatch):
    rehearsal = subprocess.run([sys.executable, str(_SCRIPT), "--root", str(runtime), "rehearse"],
                               capture_output=True, text=True, timeout=60)
    assert rehearsal.returncode == 0, rehearsal.stderr
    assert json.loads(rehearsal.stdout)["ok"] is True
    env = {k: v for k, v in __import__("os").environ.items() if k != cut.ALLOW_ENV}
    refused = subprocess.run([sys.executable, str(_SCRIPT), "--root", str(runtime), "migrate"],
                             capture_output=True, text=True, timeout=60, env=env)
    assert refused.returncode == 2 and "disabled" in refused.stderr


def test_cli_migrate_prints_a_readable_line_before_the_json(runtime):
    done = subprocess.run([sys.executable, str(_SCRIPT), "--root", str(runtime), "migrate"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    first_line, _, rest = done.stdout.partition("\n")
    assert first_line.startswith("Migrated 7 task(s)")
    assert json.loads(rest)["already"] is False

    again = subprocess.run([sys.executable, str(_SCRIPT), "--root", str(runtime), "migrate"],
                           capture_output=True, text=True, timeout=60)
    assert again.returncode == 0, again.stderr
    first_line, _, rest = again.stdout.partition("\n")
    assert first_line == "Already migrated. Nothing new to bring in."
    assert json.loads(rest)["already"] is True


def test_rehearsal_leaves_no_scratch_behind(runtime, monkeypatch, tmp_path):
    scratch_root = tmp_path / "tmp"
    scratch_root.mkdir()
    monkeypatch.setattr(cut.tempfile, "tempdir", str(scratch_root))
    assert cut.rehearse(runtime)["ok"]
    assert list(scratch_root.iterdir()) == []


# --- review round 1: fail-closed resume, catch-up, killed rollback, detection --

def _kill(runtime: Path, fn: str, step: str) -> int:
    code = (f"import sys; sys.path.insert(0, {str(_SCRIPT.parent)!r}); import solar_state_cutover as c; "
            f"c.{fn}({str(runtime)!r}, lister=lambda: [], _fail_at='kill:{step}')")
    env = dict(__import__("os").environ, **{cut.ALLOW_ENV: "1", "SOLAR_RUNTIME_ROOT": str(runtime)})
    return subprocess.run([sys.executable, "-c", code], env=env, timeout=120).returncode


@pytest.mark.parametrize("breakage", ["no-marker", "no-base", "old-schema"])
def test_a_sqlite_format_is_not_trusted_blindly(runtime, breakage):
    with pytest.raises(RuntimeError):
        cut.migrate(runtime, lister=quiet, _fail_at="after-format")
    if breakage == "no-marker":
        (runtime / cut.MARKER_NAME).unlink()
    elif breakage == "no-base":
        st.db_path(runtime).unlink()
    else:
        import sqlite3
        conn = sqlite3.connect(st.db_path(runtime))
        conn.execute("PRAGMA user_version = 1")
        conn.close()
    with pytest.raises(cut.CutoverRefused, match="refusing|schema"):
        cut.migrate(runtime, lister=quiet)
    assert (runtime / "async-tasks" / "completed" / "parent-task.md").is_file()   # nothing moved


def test_a_resumed_migration_brings_in_what_old_code_wrote_meanwhile(runtime):
    with pytest.raises(RuntimeError):
        cut.migrate(runtime, lister=quiet, _fail_at="after-format")
    _write(runtime / "async-tasks" / "queued" / "late.md", _task("late1", "queued"))
    _write(runtime / "async-tasks" / "logs" / "late.log", "late log\n")
    with (runtime / "router" / "audit.jsonl").open("a") as fh:
        fh.write('{"event": "late", "ts": "t3"}\n')
    result = cut.migrate(runtime, lister=quiet)
    assert result["caught_up"] == {"tasks": 1, "logs": 1, "audit": 1, "mandate_events": 0,
                                   "warnings": []}
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_get("late1")["log_path"] == "task-logs/late.log"
        assert s.audit_lines()[-1] == '{"event": "late", "ts": "t3"}'
    assert not (runtime / "async-tasks" / "queued").exists()


def test_a_completed_migration_tolerates_a_part_recreated_empty_afterward(runtime):
    """`ensure_dirs` (or a stale process) can rebuild an empty `async-tasks/<part>`
    after a migration already moved it aside. A resume must not try a directory-
    level replace onto the holder it already filled — reproduces the ENOTEMPTY
    crash seen against a live runtime on 2026-09-26."""
    cut.migrate(runtime, lister=quiet)
    holder = next(runtime.glob("async-tasks.migrated-*"))
    assert (holder / "queued").is_file() is False and (holder / "queued").is_dir()
    (runtime / "async-tasks" / "queued").mkdir(parents=True)   # recreated, empty

    result = cut.migrate(runtime, lister=quiet)

    assert result["already"] is True
    assert not (runtime / "async-tasks" / "queued").exists()
    assert [p.name for p in (holder / "queued").iterdir()] == ["queued-one.md"]


def test_a_recreated_part_merges_new_files_instead_of_failing(runtime):
    """The recreated folder is not always empty: old code can also drop a new
    file into it before the resume runs. That file must reach the holder, not
    be lost to the same ENOTEMPTY failure."""
    cut.migrate(runtime, lister=quiet)
    holder = next(runtime.glob("async-tasks.migrated-*"))
    _write(runtime / "async-tasks" / "error" / "second.md", _task("e2", "error"))

    result = cut.migrate(runtime, lister=quiet)

    assert result["already"] is True
    assert not (runtime / "async-tasks" / "error").exists()
    assert {p.name for p in (holder / "error").iterdir()} == {"broken.md", "second.md"}
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_get("e2")["status"] == "error"


def _without_sqlite_sidecars(tree: dict) -> dict:
    return {rel: kind for rel, kind in tree.items()
            if not rel.endswith(("-wal", "-shm"))}


def test_a_finished_migration_leaves_later_base_changes_alone(runtime):
    """The fixture runtime, never the machine one. Files already set aside stay there."""
    cut.migrate(runtime, lister=quiet)
    holder = next(runtime.glob("async-tasks.migrated-*"))
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_transition("q1", "error", expected_from="queued") == "queued"
        s.task_record("q1", log_path="task-logs/q1.log")
    _write(runtime / "task-logs" / "q1.log", "born after the migration\n")
    before = _without_sqlite_sidecars(_inventory(runtime))
    aside_before = _inventory(holder)

    result = cut.migrate(runtime, lister=quiet)

    assert result["already"] is True
    assert result["moved"] == []
    assert result["caught_up"] == {"tasks": 0, "logs": 0, "audit": 0,
                                   "mandate_events": 0, "warnings": []}
    assert _without_sqlite_sidecars(_inventory(runtime)) == before
    assert _inventory(holder) == aside_before
    assert not (runtime / "async-tasks" / "error").exists()
    assert not (runtime / "async-tasks" / "logs").exists()
    assert (runtime / "task-logs" / "q1.log").read_text() == "born after the migration\n"
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_get("q1")["status"] == "error"
        assert s.task_get("q1")["log_path"] == "task-logs/q1.log"


def test_an_interrupted_migration_still_refuses_a_real_file_change(runtime):
    _resume_setup(runtime)
    live = runtime / "async-tasks" / "completed" / "parent-task.md"
    assert live.is_file()
    _write(live, _task("p1", "completed", title="Rewritten"))
    with pytest.raises(cut.CutoverRefused, match="decide by hand") as caught:
        cut.migrate(runtime, lister=quiet)
    assert "parent-task.md changed after the migration" in str(caught.value)
    assert not list(runtime.glob("async-tasks.migrated-*"))
    assert live.is_file()
    assert "Rewritten" in live.read_text(encoding="utf-8")


def test_a_source_deleted_before_the_move_is_still_refused(tmp_path, monkeypatch):
    """Only an audit file, killed before the move, then the file is deleted.

    Nothing live remains, and nothing was set aside. That is not a finished
    migration: the resume still refuses the missing source.
    """
    root = tmp_path / "runtime"
    _write(root / "router" / "audit.jsonl", "".join(f"{line}\n" for line in AUDIT))
    monkeypatch.setenv(cut.ALLOW_ENV, "1")
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(root))
    from runtime_owner import claim_test_owner
    claim_test_owner(root, tmp_path / "workspace", monkeypatch=monkeypatch)
    with pytest.raises(RuntimeError):
        cut.migrate(root, lister=quiet, _fail_at="after-format")
    (root / "router" / "audit.jsonl").unlink()
    marker = json.loads((root / cut.MARKER_NAME).read_text())
    assert marker.get("moved") is not True
    assert not cut._legacy_files_in_place(root)
    with pytest.raises(cut.CutoverRefused, match="router/audit.jsonl is neither in place nor set aside"):
        cut.migrate(root, lister=quiet)
    assert not list(root.glob("**/*migrated-*"))


def test_one_aside_file_is_not_a_finished_move(tmp_path, monkeypatch):
    """Killed before the move, then only the audit is set aside and continuity is deleted.

    The original list still names continuity. That is not a finished move,
    and the check does not read the current base.
    """
    root = tmp_path / "runtime"
    _write(root / "router" / "audit.jsonl", "".join(f"{line}\n" for line in AUDIT))
    _write(root / "continuity" / "active.json", CONTINUITY)
    monkeypatch.setenv(cut.ALLOW_ENV, "1")
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(root))
    from runtime_owner import claim_test_owner
    claim_test_owner(root, tmp_path / "workspace", monkeypatch=monkeypatch)
    with pytest.raises(RuntimeError):
        cut.migrate(root, lister=quiet, _fail_at="after-format")
    stamp = json.loads((root / cut.MARKER_NAME).read_text())["stamp"]
    audit = root / "router" / "audit.jsonl"
    audit.rename(audit.with_name(f"audit.jsonl.migrated-{stamp}"))
    (root / "continuity" / "active.json").unlink()
    assert not cut._legacy_files_in_place(root)
    assert cut._move_finished(root, stamp) is False
    with pytest.raises(cut.CutoverRefused, match="continuity/active.json is neither in place nor set aside"):
        cut.migrate(root, lister=quiet)
    assert json.loads((root / cut.MARKER_NAME).read_text()).get("moved") is not True


def test_an_interrupted_marker_write_keeps_the_previous_marker(runtime, monkeypatch):
    cut.migrate(runtime, lister=quiet)
    marker = runtime / cut.MARKER_NAME
    previous = marker.read_text(encoding="utf-8")
    stamp = json.loads(previous)["stamp"]

    def killed_replace(*_args, **_kwargs):
        raise OSError("killed during replace")

    monkeypatch.setattr(cut.os, "replace", killed_replace)
    with pytest.raises(OSError, match="killed during replace"):
        cut._write_marker(marker, json.dumps({"stamp": stamp, "moved": True, "broken": True}))
    assert marker.read_text(encoding="utf-8") == previous
    assert not list(marker.parent.glob(".state-migration.json.*.tmp"))
    assert cut._check_migrated_base(runtime) == stamp


def test_an_older_marker_still_settles_when_the_aside_names_exist(runtime):
    """A migration that finished before `moved` was recorded. The aside names
    are the evidence. The base may already have drifted."""
    cut.migrate(runtime, lister=quiet)
    marker_path = runtime / cut.MARKER_NAME
    stamp = json.loads(marker_path.read_text())["stamp"]
    marker_path.write_text(json.dumps({"stamp": stamp}), encoding="utf-8")
    holder = next(runtime.glob("async-tasks.migrated-*"))
    aside_before = _inventory(holder)
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_transition("q1", "error", expected_from="queued") == "queued"
    result = cut.migrate(runtime, lister=quiet)
    assert result["already"] is True
    assert result["moved"] == []
    assert _inventory(holder) == aside_before
    assert json.loads(marker_path.read_text()) == {"stamp": stamp, "moved": True}
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_get("q1")["status"] == "error"


def test_foreign_metadata_does_not_reopen_catch_up(runtime):
    cut.migrate(runtime, lister=quiet)
    holder = next(runtime.glob("async-tasks.migrated-*"))
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_transition("q1", "error", expected_from="queued") == "queued"
    queued = runtime / "async-tasks" / "queued"
    queued.mkdir()
    (queued / ".DS_Store").write_bytes(b"\x00\x00")
    aside_before = _inventory(holder)
    result = cut.migrate(runtime, lister=quiet)
    assert result["already"] is True
    assert result["moved"] == []
    assert result["caught_up"] == {"tasks": 0, "logs": 0, "audit": 0,
                                   "mandate_events": 0, "warnings": []}
    assert _inventory(holder) == aside_before
    assert not (holder / "queued" / ".DS_Store").exists()
    assert (queued / ".DS_Store").is_file()
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_get("q1")["status"] == "error"


def test_a_resumed_migration_refuses_a_rewritten_audit(runtime):
    with pytest.raises(RuntimeError):
        cut.migrate(runtime, lister=quiet, _fail_at="after-format")
    _write(runtime / "router" / "audit.jsonl", '{"event": "something else"}\n')
    with pytest.raises(cut.CutoverRefused, match="not a plain continuation"):
        cut.migrate(runtime, lister=quiet)
    assert (runtime / "router" / "audit.jsonl").is_file()


def test_a_resumed_migration_waits_for_running_code(runtime):
    with pytest.raises(RuntimeError):
        cut.migrate(runtime, lister=quiet, _fail_at="after-format")
    running = lambda: [(5, "python3 core/skills/solar-router/scripts/run_router.py")]  # noqa: E731
    with pytest.raises(cut.CutoverRefused, match="pid 5"):
        cut.migrate(runtime, wait=0.1, lister=running)


@pytest.mark.parametrize("step", ["after-export", "mid-place", "after-format"])
def test_a_rollback_killed_for_real_completes_when_run_again(runtime, step):
    before = _source_snapshot(runtime)
    cut.migrate(runtime, lister=quiet)
    assert _kill(runtime, "rollback", step) == 9
    cut.rollback(runtime, lister=quiet)
    assert st.read_format(runtime) == st.FORMAT_FILES
    assert not st.db_path(runtime).exists()
    assert not (runtime / cut.ROLLBACK_MARKER).exists()
    assert not (runtime / cut.ROLLBACK_STAGING).exists()
    after = _source_snapshot(runtime)
    before.pop("async-tasks/archive/old-recurring.md")
    after.pop("async-tasks/archive/old-recurring.md")
    assert after == before


def test_a_killed_rollback_never_deletes_a_file_someone_changed(runtime):
    cut.migrate(runtime, lister=quiet)
    assert _kill(runtime, "rollback", "mid-place") == 9
    planned = json.loads((runtime / cut.ROLLBACK_MARKER).read_text())["planned"]
    placed = next(rel for rel in planned if (runtime / rel).is_file())
    (runtime / placed).write_text("edited by hand after the kill\n")
    with pytest.raises(cut.CutoverRefused, match="changed since"):
        cut.rollback(runtime, lister=quiet)
    assert (runtime / placed).read_text() == "edited by hand after the kill\n"


def test_a_migration_killed_for_real_completes_when_run_again(runtime):
    assert _kill(runtime, "migrate", "after-place") == 9
    cut.migrate(runtime, lister=quiet)
    with st.session(runtime, auto_backup=False) as s:
        assert sum(s.counts()["tasks"].values()) == 7


@pytest.mark.parametrize("cmd", [
    "python3 core/skills/solar-router/scripts/run_router.py",
    "bash skills/solar-async-tasks/scripts/start_next.sh",
    "python3 run_router.py",
    "bash ./run_worker.sh",
    "bash create.sh",
    "bash task_lib.sh",
    "bash start_next.sh",
    "bash activate.sh",
    "bash complete.sh",
    "bash approve.sh",
    "bash requeue_from_error.sh",
    "python3 task_cancel.py",
    "bash reconcile_router_audit.sh",
    "python3 continuity_cli.py",
    "python3 delegation_ctl.py",
])
def test_old_code_is_seen_however_it_was_called(runtime, cmd):
    assert cut.in_flight(runtime, lambda: [(9, cmd)])


@pytest.mark.parametrize("pid", ["abc", None, "", [1]])
def test_a_malformed_handle_is_ignored_not_fatal(runtime, pid):
    _write(runtime / "async-tasks" / "handles" / "bad.json", json.dumps({"pid": pid, "task_id": "q1"}))
    assert cut.in_flight(runtime, quiet) == []


# --- review round 2: containment, catch-up compares, marker integrity ---------

def _resume_setup(runtime):
    with pytest.raises(RuntimeError):
        cut.migrate(runtime, lister=quiet, _fail_at="after-format")


def test_a_rollback_never_writes_outside_the_runtime(runtime, tmp_path):
    cut.migrate(runtime, lister=quiet)
    # The API refuses such an id, so put it in the base the hard way: the cutover
    # must not trust what it reads either.
    with st.session(runtime, auto_backup=False) as s:
        s.task_create([("title", '"escape"')], task_id="escape", status="draft")
        s.conn.execute("UPDATE tasks SET source_name = ? WHERE id = 'escape'",
                       ("../../../../escaped.md",))
    with pytest.raises(cut.CutoverRefused, match="leaves the runtime"):
        cut.rollback(runtime, lister=quiet)
    assert not (tmp_path.parent / "escaped.md").exists()
    assert not list(tmp_path.glob("**/escaped.md"))
    assert st.read_format(runtime) == st.FORMAT_SQLITE


def test_a_rollback_refuses_two_rows_writing_the_same_file(runtime):
    cut.migrate(runtime, lister=quiet)
    with st.session(runtime, auto_backup=False) as s:
        s.task_create([("title", '"one"')], task_id="one", status="draft")
        s.task_create([("title", '"two"')], task_id="two", status="draft")
        s.conn.execute("UPDATE tasks SET source_name = 'clash.md' WHERE id IN ('one', 'two')")
    with pytest.raises(cut.CutoverRefused, match="same file"):
        cut.rollback(runtime, lister=quiet)
    assert st.read_format(runtime) == st.FORMAT_SQLITE


@pytest.mark.parametrize("break_it, message", [
    (lambda r: _write(r / "async-tasks" / "completed" / "parent-task.md",
                      _task("p1", "completed", title="Rewritten")), "parent-task.md changed"),
    (lambda r: _write(r / "async-tasks" / "logs" / "parent-task.log", "log of the parent\nmore\n"),
     "log parent-task.log differs"),
    (lambda r: _write(r / "async-tasks" / "subtasks" / "p1.json", "[]"), "subtask plan p1.json changed"),
    (lambda r: _write(r / "router" / "audit.jsonl", ""), "router/audit.jsonl is not a plain continuation"),
    (lambda r: (r / "router" / "audit.jsonl").unlink(),
     "router/audit.jsonl is neither in place nor set aside"),
    (lambda r: _write(r / "delegations" / "example-mandate" / "events.jsonl", ""),
     "delegations/example-mandate/events.jsonl is not a plain continuation"),
    (lambda r: _write(r / "continuity" / "active.json", '{"active_task": "other"}'),
     "continuity/active.json changed"),
])
def test_a_resumed_migration_refuses_files_that_changed(runtime, break_it, message):
    _resume_setup(runtime)
    break_it(runtime)
    with pytest.raises(cut.CutoverRefused, match="decide by hand") as caught:
        cut.migrate(runtime, lister=quiet)
    assert message in str(caught.value)
    assert (runtime / "async-tasks" / "completed").is_dir()     # nothing was moved aside


def test_a_late_task_keeps_its_children(runtime):
    _resume_setup(runtime)
    _write(runtime / "async-tasks" / "queued" / "late-parent.md",
           _task("lp", "queued", 'subtask_ids: "x=c1"\n'))
    result = cut.migrate(runtime, lister=quiet)
    assert result["caught_up"]["tasks"] == 1
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_children("lp") == [{"child_id": "c1", "subtask_key": "x"}]


def test_a_late_task_pointing_at_nothing_is_reported_not_linked(runtime):
    _resume_setup(runtime)
    _write(runtime / "async-tasks" / "queued" / "late-parent.md",
           _task("lp", "queued", 'subtask_ids: "x=ghost"\n'))
    result = cut.migrate(runtime, lister=quiet)
    assert result["caught_up"]["warnings"] == ["lp: child 'ghost' is not among the tasks"]


@pytest.mark.parametrize("marker, message", [
    ("not json at all", "unreadable"),
    ('{"other": 1}', "unreadable"),
    ('{"stamp": ""}', "no stamp"),
    ('{"stamp": 7}', "no stamp"),
])
def test_a_corrupt_migration_marker_refuses(runtime, marker, message):
    _resume_setup(runtime)
    _write(runtime / cut.MARKER_NAME, marker)
    with pytest.raises(cut.CutoverRefused, match=message):
        cut.migrate(runtime, lister=quiet)
    assert (runtime / "async-tasks" / "completed" / "parent-task.md").is_file()


def test_a_base_that_lost_a_table_refuses(runtime):
    _resume_setup(runtime)
    import sqlite3
    conn = sqlite3.connect(st.db_path(runtime))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TABLE subtask_plans")
    conn.close()
    with pytest.raises(cut.CutoverRefused, match="missing tables: subtask_plans"):
        cut.migrate(runtime, lister=quiet)


def test_a_late_child_of_an_existing_parent_gets_linked(runtime):
    """The parent already named the child at the first import; the child file
    shows up only on the resume. The link has to be created then."""
    _write(runtime / "async-tasks" / "completed" / "parent-task.md",
           _task("p1", "completed", 'subtask_ids: "a=c1,b=c2,c=late1"\n', "Parent"))
    _resume_setup(runtime)
    with st.session(runtime, auto_backup=False) as s:
        assert [row["child_id"] for row in s.task_children("p1")] == ["c1", "c2"]
    _write(runtime / "async-tasks" / "queued" / "late.md", _task("late1", "queued"))
    cut.migrate(runtime, lister=quiet)
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_children("p1") == [
            {"child_id": "c1", "subtask_key": "a"},
            {"child_id": "c2", "subtask_key": "b"},
            {"child_id": "late1", "subtask_key": "c"},
        ]


def test_a_refused_resume_still_links_the_late_parent_on_the_next_run(runtime):
    """A late parent is stored before the refusal. The next run must still link it."""
    _resume_setup(runtime)
    _write(runtime / "async-tasks" / "queued" / "late-parent.md",
           _task("lp", "queued", 'subtask_ids: "x=c1"\n'))
    _write(runtime / "async-tasks" / "completed" / "parent-task.md",
           _task("p1", "completed", title="Rewritten"))
    with pytest.raises(cut.CutoverRefused, match="decide by hand"):
        cut.migrate(runtime, lister=quiet)
    with st.session(runtime, auto_backup=False) as s:
        (runtime / "async-tasks" / "completed" / "parent-task.md").write_text(
            s.task_export("p1"), encoding="utf-8")
    cut.migrate(runtime, lister=quiet)
    with st.session(runtime, auto_backup=False) as s:
        assert s.task_children("lp") == [{"child_id": "c1", "subtask_key": "x"}]


def test_a_stamp_that_leaves_the_runtime_refuses(runtime):
    _resume_setup(runtime)
    _write(runtime / cut.MARKER_NAME, json.dumps({"stamp": "../../../escaped"}))
    outside = runtime.parent / "escaped"
    with pytest.raises(cut.CutoverRefused, match="stamp"):
        cut.migrate(runtime, lister=quiet)
    assert not outside.exists()
    assert not (runtime / "escaped").exists()
    assert (runtime / "async-tasks" / "completed" / "parent-task.md").is_file()


def test_an_unreadable_base_refuses(runtime):
    _resume_setup(runtime)
    st.db_path(runtime).write_bytes(b"this is not a sqlite database")
    with pytest.raises(cut.CutoverRefused, match="unreadable"):
        cut.migrate(runtime, lister=quiet)
    assert (runtime / "async-tasks" / "completed" / "parent-task.md").is_file()


def test_a_deleted_continuity_file_refuses_the_resume(runtime):
    _resume_setup(runtime)
    (runtime / "continuity" / "active.json").unlink()
    with pytest.raises(cut.CutoverRefused, match="continuity/active.json is neither in place nor set aside"):
        cut.migrate(runtime, lister=quiet)
    assert (runtime / "async-tasks" / "completed").is_dir()


def test_a_continuity_file_already_set_aside_is_not_a_deletion(runtime):
    _resume_setup(runtime)
    stamp = json.loads((runtime / cut.MARKER_NAME).read_text())["stamp"]
    src = runtime / "continuity" / "active.json"
    src.rename(src.with_name(f"active.json.migrated-{stamp}"))
    assert cut.migrate(runtime, lister=quiet)["already"] is True


def test_a_source_already_set_aside_is_not_a_deletion(runtime):
    _resume_setup(runtime)
    stamp = json.loads((runtime / cut.MARKER_NAME).read_text())["stamp"]
    src = runtime / "router" / "audit.jsonl"
    src.rename(src.with_name(f"audit.jsonl.migrated-{stamp}"))
    assert cut.migrate(runtime, lister=quiet)["already"] is True


def test_an_empty_audit_file_comes_back_on_rollback(runtime):
    audit = runtime / "router" / "audit.jsonl"
    audit.write_text("", encoding="utf-8")
    cut.migrate(runtime, lister=quiet)
    with st.session(runtime, auto_backup=False) as s:
        assert s.audit_lines() == []
        assert s.audit_file_present()
    cut.rollback(runtime, lister=quiet)
    assert audit.is_file()
    assert audit.read_bytes() == b""


def test_a_corrupt_rollback_marker_refuses(runtime):
    cut.migrate(runtime, lister=quiet)
    assert _kill(runtime, "rollback", "mid-place") == 9
    _write(runtime / cut.ROLLBACK_MARKER, "{oops")
    with pytest.raises(cut.CutoverRefused, match="rollback marker is unreadable"):
        cut.rollback(runtime, lister=quiet)


def test_a_finished_rollback_deletes_the_cutover_marker(tmp_path):
    base = tmp_path / "runtime"
    base.mkdir()
    (base / st.CUTOVER_MARKER).write_text('{"identity": "x"}\n', encoding="utf-8")
    cut._finish_rollback(base)
    assert not (base / st.CUTOVER_MARKER).exists()


def _inventory(root: Path) -> dict:
    found = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            found[rel] = ("symlink", os.readlink(path))
        elif path.is_dir():
            found[rel] = ("dir",)
        elif path.is_file():
            found[rel] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
    return found


def _console():
    scripts = Path(st.__file__).resolve().parents[2] / "solar-app" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import console_data
    return console_data


def test_a_console_read_creates_nothing(runtime, monkeypatch):
    cut.migrate(runtime, lister=quiet)
    console = _console()
    monkeypatch.setattr(console, "port_taken_by_other", lambda port=9000: False)
    before = _inventory(runtime)
    workspace = Path(os.environ["SOLAR_WORKSPACE"])
    import runtime_views
    with st.read_session(runtime) as store:
        runtime_views.console_tasks(store)
        runtime_views.console_executions(store)
        runtime_views.console_continuity(store)
        runtime_views.console_mandate_events(store)
        runtime_views.console_last_activity(store)
    console.health(workspace)
    console.tasks(workspace)
    console.executions(workspace)
    console.continuity(workspace)
    console.mandates(workspace)
    console.ides(workspace)
    console.ingress(workspace)
    console.requester(workspace)
    assert _inventory(runtime) == before
    assert not (runtime / st.BACKUP_DIR).exists()


def test_a_read_does_not_proceed_during_a_cutover(runtime):
    cut.migrate(runtime, lister=quiet)
    started = threading.Event()
    release = threading.Event()

    def hold():
        with st.cutover(runtime):
            started.set()
            assert release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    assert started.wait(2)
    before = _inventory(runtime)
    with pytest.raises(st.StateBusy):
        with st.read_session(runtime, timeout=0.2) as store:
            raise AssertionError(store.console_task_counts())
    assert _inventory(runtime) == before
    release.set()
    thread.join(5)
    assert not thread.is_alive()


def test_a_missing_lock_is_refused_without_creating_it(root):
    with pytest.raises(st.StateUnavailable, match="state.lock"):
        with st.read_session(root, timeout=0.2):
            pass
    assert _inventory(root) == {}


def test_a_missing_owner_format_or_schema_is_refused_without_new_files(ready):
    owner = ready / st.OWNER_NAME
    saved_owner = owner.read_bytes()
    owner.unlink()
    before = _inventory(ready)
    with pytest.raises(st.StateUnavailable, match="owner"):
        with st.read_session(ready, timeout=0.2):
            pass
    assert _inventory(ready) == before
    owner.write_bytes(saved_owner)

    fmt = ready / st.FORMAT_NAME
    saved_fmt = fmt.read_bytes()
    fmt.unlink()
    before = _inventory(ready)
    with pytest.raises(st.StateUnavailable, match="format"):
        with st.read_session(ready, timeout=0.2):
            pass
    assert _inventory(ready) == before
    fmt.write_bytes(saved_fmt)

    with st.session(ready, auto_backup=False) as store:
        store.conn.execute("PRAGMA user_version=0")
        store.conn.commit()
    before = _inventory(ready)
    with pytest.raises(st.StateUnavailable, match="schema"):
        with st.read_session(ready, timeout=0.2):
            pass
    assert _inventory(ready) == before
