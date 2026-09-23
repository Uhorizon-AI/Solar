"""Cutover between the file runtime and solar-state: migrate, rollback, rehearse."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
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
