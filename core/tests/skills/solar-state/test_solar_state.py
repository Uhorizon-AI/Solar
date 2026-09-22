"""The solar-state contract: schema, transitions, claim, export, lock, format, backups."""
from __future__ import annotations

import json
import multiprocessing
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import solar_state
from solar_state import (StateBusy, StateUnavailable, TransitionRefused, cutover,
                         parse_task_document, render_task_document, session)

_SCRIPT = Path(solar_state.__file__)


def _tree(path: Path) -> set[str]:
    return {str(p.relative_to(path)) for p in path.rglob("*")}


# --- schema ------------------------------------------------------------------

def test_fresh_base_has_schema_and_transitions(ready):
    with session(ready, auto_backup=False) as s:
        assert solar_state._schema_version(s.conn) == solar_state.SCHEMA_VERSION
        moves = {tuple(r) for r in s.conn.execute("SELECT from_status, to_status FROM transitions")}
        assert moves == set(solar_state.TRANSITIONS)


def test_base_is_recreated_identically_and_touches_nothing_outside(root, tmp_path):
    outside_before = _tree(tmp_path) - {str(p.relative_to(tmp_path)) for p in root.rglob("*")}
    with cutover(root) as cut:
        cut.upgrade_schema()
    first = solar_state.schema_dump(sqlite3.connect(solar_state.db_path(root)))

    for leftover in root.glob("state.sqlite*"):
        leftover.unlink()
    with cutover(root) as cut:
        cut.upgrade_schema()
    second = solar_state.schema_dump(sqlite3.connect(solar_state.db_path(root)))

    assert first == second
    outside_after = _tree(tmp_path) - {str(p.relative_to(tmp_path)) for p in root.rglob("*")}
    assert outside_after == outside_before


def test_only_solar_paths_is_imported():
    source = _SCRIPT.read_text(encoding="utf-8")
    skills = set(re.findall(r'"(solar-[a-z-]+)"', source)) | set(re.findall(r"skills/(solar-[a-z-]+)", source))
    assert skills <= {"solar-paths"}, skills


# --- guards ------------------------------------------------------------------

def test_refuses_without_the_sqlite_format(root):
    with cutover(root) as cut:
        cut.upgrade_schema()
    with pytest.raises(StateUnavailable, match="unset"):
        with session(root):
            pass
    with cutover(root) as cut:
        cut.set_format(solar_state.FORMAT_FILES)
    with pytest.raises(StateUnavailable, match="files"):
        with session(root):
            pass


def test_refuses_an_older_schema_instead_of_upgrading(ready):
    conn = sqlite3.connect(solar_state.db_path(ready))
    conn.execute("PRAGMA user_version = 0")
    conn.close()
    with pytest.raises(StateUnavailable, match="v0"):
        with session(ready):
            pass


def test_upgrade_copies_an_existing_base_first(ready):
    conn = sqlite3.connect(solar_state.db_path(ready))
    conn.execute("PRAGMA user_version = 0")
    for table in ("delegation_events", "continuity", "audit", "task_events", "task_links",
                  "tasks", "transitions", "statuses"):
        conn.execute(f"DROP TABLE {table}")
    conn.close()
    with cutover(ready) as cut:
        result = cut.upgrade_schema()
    assert result["from_version"] == 0 and result["backup"]
    assert Path(result["backup"]).parent.name == "pre-migration"


# --- tasks -------------------------------------------------------------------

def test_transitions_follow_the_table(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("title", '"t"')], status="draft")
        with pytest.raises(TransitionRefused, match="draft -> active"):
            s.task_transition(tid, "active")
        s.task_transition(tid, "queued")
        with pytest.raises(TransitionRefused, match="is queued, not planned"):
            s.task_transition(tid, "cancelled", expected_from="planned")
        assert s.task_transition(tid, "active") == "queued"
        s.task_transition(tid, "completed")
        s.task_transition(tid, "archived")
        with pytest.raises(TransitionRefused):
            s.task_transition(tid, "queued")
        events = [tuple(r) for r in s.conn.execute(
            "SELECT from_status, to_status FROM task_events WHERE task_id = ? ORDER BY seq", (tid,))]
    assert events == [(None, "draft"), ("draft", "queued"), ("queued", "active"),
                      ("active", "completed"), ("completed", "archived")]


def test_status_lives_in_both_the_column_and_the_frontmatter(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("title", '"t"')], status="queued")
        s.task_claim(tid, "w1")
        task = s.task_get(tid)
    assert task["status"] == "active"
    assert ["status", " active"] in task["frontmatter"]
    assert task["claimed_by"] == "w1"


def test_export_is_byte_for_byte():
    original = (
        '---\n'
        'id: "6286d90e-4eb7-4f5d-a4dd-38fd1b6757e4"\n'
        'title: "Preparar one-pager: router"\n'
        'created: "2026-04-07T16:52:42+02:00"\n'
        'status: completed\n'
        'priority: normal\n'
        'recurring: false\n'
        'subtask_ids:\n'
        '  - "a"\n'
        '  - "b"\n'
        'empty_key:\n'
        'trailing: value   \n'
        "quoted_single: 'x'\n"
        'completed_at: 2026-04-07T14:55:41Z\n'
        '---\n'
        '\n'
        '# Preparar one-pager\n'
        '\n'
        '---\n'
        'A horizontal rule in the body is not the end of the frontmatter.\n'
    )
    pairs, body = parse_task_document(original)
    assert render_task_document(pairs, body) == original
    assert dict(pairs)["subtask_ids"] == '\n  - "a"\n  - "b"'


def test_imported_document_round_trips_through_the_base(ready):
    original = ('---\nid: "abc"\ntitle: "T: con dos puntos"\nstatus: queued\n'
                'priority: high\nx_custom: "keep me"\n---\n\nbody\n')
    pairs, body = parse_task_document(original)
    with session(ready, auto_backup=False) as s:
        s.task_create([(k, v.strip()) for k, v in pairs], body, status="queued")
        assert s.task_export("abc") == original
        task = s.task_get("abc")
    assert task["title"] == "T: con dos puntos"
    assert task["priority"] == "high"


def test_set_keeps_order_and_refuses_status(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("title", '"t"'), ("priority", "normal")], status="draft")
        s.task_set(tid, "priority", "high")
        s.task_set(tid, "notify_when", "completed")
        keys = [k for k, _ in s.task_get(tid)["frontmatter"]]
        with pytest.raises(solar_state.StateError):
            s.task_set(tid, "status", "active")
    assert keys == ["id", "title", "priority", "status", "notify_when"]


def _claim_many(root, ids, worker, barrier, out):
    os.environ["SOLAR_RUNTIME_ROOT"] = root
    won = []
    with solar_state.session(root, auto_backup=False) as s:
        for tid in ids:
            barrier.wait()
            if s.task_claim(tid, worker):
                won.append(tid)
    out.put((worker, won))


def test_claim_has_exactly_one_winner_in_1000_races(ready):
    rounds = 1000
    with session(ready, auto_backup=False) as s:
        ids = [s.task_create([("title", f'"t{i}"')], status="queued") for i in range(rounds)]
    ctx = multiprocessing.get_context("spawn")
    barrier, out = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=_claim_many, args=(str(ready), ids, w, barrier, out))
             for w in ("w1", "w2")]
    for p in procs:
        p.start()
    results = dict(out.get(timeout=240) for _ in procs)
    for p in procs:
        p.join(30)

    w1, w2 = set(results["w1"]), set(results["w2"])
    assert not (w1 & w2), "a task was claimed twice"
    assert w1 | w2 == set(ids), "a task was claimed by nobody"
    with session(ready, auto_backup=False) as s:
        owners = dict(s.conn.execute("SELECT id, claimed_by FROM tasks"))
    assert all(owners[t] == "w1" for t in w1) and all(owners[t] == "w2" for t in w2)


# --- lock --------------------------------------------------------------------

def _slow_writer(root, started, done_file):
    os.environ["SOLAR_RUNTIME_ROOT"] = root
    with solar_state.session(root, auto_backup=False) as s:
        started.set()
        time.sleep(0.6)
        s.task_create([("title", '"late write"')], status="draft", task_id="slow")
        Path(done_file).write_text(str(time.monotonic()))


def test_an_operation_started_before_a_cutover_finishes_before_it(ready, tmp_path):
    ctx = multiprocessing.get_context("spawn")
    started, done = ctx.Event(), tmp_path / "done"
    proc = ctx.Process(target=_slow_writer, args=(str(ready), started, str(done)))
    proc.start()
    assert started.wait(30)
    with cutover(ready, timeout=30) as cut:
        acquired = time.monotonic()
        assert done.exists(), "the cutover got the lock while an operation was still open"
        assert float(done.read_text()) <= acquired
        s = cut.session()
        assert s.task_get("slow") is not None
        s.conn.close()
    proc.join(30)


def test_an_operation_during_a_cutover_waits_and_does_not_write(ready):
    with cutover(ready):
        with pytest.raises(StateBusy):
            with session(ready, timeout=0.3, auto_backup=False) as s:
                s.task_create([("title", '"must not land"')])
    with session(ready, auto_backup=False) as s:
        assert s.task_list() == []


def test_a_dead_cutover_leaves_everything_closed(ready):
    with cutover(ready) as cut:
        cut.set_format(solar_state.FORMAT_FILES)
        # the process "dies" here: the lock goes with it, the format stays
    with pytest.raises(StateUnavailable):
        with session(ready):
            pass


# --- continuity, audit, mandate events ----------------------------------------

def test_continuity_read_modify_write_is_one_transaction(ready):
    with session(ready, auto_backup=False) as s:
        assert s.continuity_get() is None
        s.continuity_update(lambda cur: {"active_task": "a", "channels_seen": []})
        s.continuity_update(lambda cur: {**cur, "channels_seen": cur["channels_seen"] + ["telegram"]})
        assert s.continuity_get() == {"active_task": "a", "channels_seen": ["telegram"]}


def test_audit_and_mandate_events_keep_their_lines(ready):
    with session(ready, auto_backup=False) as s:
        s.audit_append({"ts": "t1", "event": "start", "router_id": "r"})
        s.audit_append({"ts": "t2", "event": "end", "router_id": "r"})
        assert [r["event"] for r in s.audit_rows()] == ["start", "end"]
        assert s.audit_rows(limit=1) == [{"ts": "t2", "event": "end", "router_id": "r"}]
        s.delegation_event_append("calendar-busy-sync", "shadow", {"ts": "t", "ok": True})
        assert s.delegation_events("calendar-busy-sync", "shadow") == [{"ts": "t", "ok": True}]
        assert s.delegation_events("calendar-busy-sync", "events") == []


# --- backups -----------------------------------------------------------------

def test_daily_copy_is_taken_when_due_and_restores(ready):
    with session(ready) as s:
        s.task_create([("title", '"t"')], status="queued")
    daily = solar_state.backup_dir(ready, "daily")
    copies = sorted(daily.glob("state-*.sqlite"))
    assert len(copies) == 1  # taken on open: there was none
    with session(ready) as s:
        s.task_create([("title", '"u"')], status="draft")
    assert len(sorted(daily.glob("state-*.sqlite"))) == 1  # not due again

    with session(ready, auto_backup=False) as s:
        manual = solar_state.backup_now(s.conn, ready, "manual")
    info = solar_state.inspect_backup(manual)
    assert info["integrity"] == "ok"
    assert info["schema_version"] == solar_state.SCHEMA_VERSION
    assert info["tasks"] == {"draft": 1, "queued": 1}


def test_daily_copies_keep_seven(ready):
    daily = solar_state.backup_dir(ready, "daily")
    with session(ready, auto_backup=False) as s:
        for _ in range(10):
            solar_state.backup_now(s.conn, ready, "daily")
    assert len(list(daily.glob("state-*.sqlite"))) == solar_state.DAILY_KEEP


def test_a_stale_daily_copy_triggers_a_new_one(ready):
    with session(ready) as _:
        pass
    daily = solar_state.backup_dir(ready, "daily")
    (old,) = daily.glob("state-*.sqlite")
    past = time.time() - solar_state.DAILY_MAX_AGE_SEC - 60
    os.utime(old, (past, past))
    time.sleep(0.01)
    with session(ready) as _:
        pass
    assert len(list(daily.glob("state-*.sqlite"))) == 2


# --- CLI ---------------------------------------------------------------------

def _cli(root, *args, stdin=None):
    return subprocess.run([sys.executable, str(_SCRIPT), "--root", str(root), *args],
                          capture_output=True, text=True, input=stdin, timeout=60)


def test_cli_create_claim_show(ready):
    made = _cli(ready, "task", "create", "--status", "queued",
                "--field", 'title="Desde Bash"', "--field", "priority=normal", "--body", "# b\n")
    assert made.returncode == 0, made.stderr
    tid = json.loads(made.stdout)["id"]

    assert _cli(ready, "task", "claim", tid, "--worker", "bash").returncode == 0
    lost = _cli(ready, "task", "claim", tid, "--worker", "other")
    assert lost.returncode == 3 and json.loads(lost.stdout)["claimed"] is False

    shown = _cli(ready, "task", "show", tid)
    assert shown.stdout.startswith(f'---\nid: "{tid}"\ntitle: "Desde Bash"\npriority: normal\nstatus: active\n---\n')

    refused = _cli(ready, "task", "transition", tid, "draft")
    assert refused.returncode == 2 and "TransitionRefused" in refused.stderr


def test_cli_refuses_with_exit_2_when_not_migrated(root):
    result = _cli(root, "task", "list")
    assert result.returncode == 2 and "StateUnavailable" in result.stderr
    status = _cli(root, "status")
    assert status.returncode == 0 and json.loads(status.stdout)["format"] is None


# --- review round 1: verbatim import, ids, claims, refusals, status ----------

_DOC = (
    '---\n'
    'id: "6286d90e-4eb7-4f5d-a4dd-38fd1b6757e4"\n'
    'title: "Preparar one-pager: router"\n'
    'status: completed\n'
    'subtask_ids:\n'
    '  - "a"\n'
    '  - "b"\n'
    'empty_key:\n'
    'trailing: value   \n'
    "quoted_single: 'x'\n"
    'origin_thread_id: "th-1"\n'
    'origin_run_id: "run-9"\n'
    '---\n'
    '\n'
    '# Body\n'
    '\n'
    '---\n'
    'a rule in the body\n'
)


def test_imported_task_goes_in_and_out_byte_for_byte(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_import(_DOC)
        assert s.task_export(tid) == _DOC
        task = s.task_get(tid)
    assert task["status"] == "completed"
    assert (task["origin_thread_id"], task["origin_run_id"]) == ("th-1", "run-9")


def test_import_status_wins_and_is_written_back(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_import(_DOC, status="archived")
        exported = s.task_export(tid)
    assert "\nstatus: archived\n" in exported
    assert exported.replace("status: archived", "status: completed") == _DOC


def test_non_canonical_json_lines_survive(ready):
    audit = ['{"ts": "t1",  "event":"start", "router_id":"r", "nota":"ñ"}',
             '{"router_id": "r", "event": "end", "ts": "t2", "esc": "\\u00f1"}']
    event = '{ "ts" : "t", "ok" : true }'
    continuity = '{\n    "active_task": "x",\n  "channels_seen": [ ]\n}\n'
    with session(ready, auto_backup=False) as s:
        for line in audit:
            s.audit_import_line(line + "\n")
        s.delegation_event_import_line("m", "shadow", event)
        s.continuity_import_text(continuity)
        assert s.audit_lines() == audit
        assert s.delegation_event_lines("m", "shadow") == [event]
        assert s.continuity_text() == continuity
        assert [r["event"] for r in s.audit_rows()] == ["start", "end"]


def test_one_id_per_task(ready):
    with session(ready, auto_backup=False) as s:
        with pytest.raises(solar_state.StateError, match="differ"):
            s.task_create([("id", '"a"'), ("title", '"t"')], task_id="b")
        with pytest.raises(solar_state.FormatError, match="twice"):
            s.task_create([("title", '"t"'), ("title", '"u"')])
        with pytest.raises(solar_state.FormatError, match="twice"):
            s.task_import('---\nid: "x"\nstatus: draft\nid: "y"\n---\n')
        with pytest.raises(solar_state.FormatError, match="needs an id"):
            s.task_import('---\nstatus: draft\n---\n')
        s.task_create([("title", '"t"')], task_id="same")
        with pytest.raises(solar_state.StateError, match="refused by the base"):
            s.task_create([("title", '"t"')], task_id="same")
        assert len(s.task_list()) == 1


def test_claim_distinguishes_lost_from_missing(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("title", '"t"')], status="draft")
        assert s.task_claim(tid, "w") is False            # exists, not queued
        with pytest.raises(solar_state.StateError, match="no task"):
            s.task_claim("does-not-exist", "w")
    missing = _cli(ready, "task", "claim", "does-not-exist", "--worker", "w")
    assert missing.returncode == 2, missing.stderr


def test_cli_duplicate_id_is_a_refusal_not_a_crash(ready):
    first = _cli(ready, "task", "create", "--field", 'id="dup"')
    assert first.returncode == 0, first.stderr
    again = _cli(ready, "task", "create", "--field", 'id="dup"')
    assert again.returncode == 2 and "Traceback" not in again.stderr


def test_transitions_only_set_allowed_columns(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("title", '"t"')], status="queued")
        for bad in ("title", "status = 'active' --", "row_version"):
            with pytest.raises(solar_state.StateError, match="not a column"):
                s.task_transition(tid, "active", **{bad: "x"})
        assert s.task_get(tid)["status"] == "queued"
        s.task_transition(tid, "active", pid=123, log_path="logs/t.log")
        task = s.task_get(tid)
    assert (task["pid"], task["log_path"]) == (123, "logs/t.log")


def test_status_reads_under_the_shared_lock_and_says_why(root):
    info = solar_state.describe(root)
    assert info["ready"] is False and "unset" in info["reason"]
    with cutover(root) as cut:
        cut.upgrade_schema()
        with pytest.raises(StateBusy):
            solar_state.describe(root, timeout=0.3)
        busy = _cli(root, "status", "--timeout", "0.3")
        assert busy.returncode == 2 and "StateBusy" in busy.stderr
        cut.set_format(solar_state.FORMAT_SQLITE)
    info = solar_state.describe(root)
    assert info["ready"] is True and info["counts"]["tasks"] == {}


def test_refusals_do_not_point_at_a_command_that_does_not_exist(root):
    with pytest.raises(StateUnavailable) as caught:
        with session(root):
            pass
    assert "solar state migrate" not in str(caught.value)


# --- review round 2: empty id, invalid keys, multi-line values ---------------

@pytest.mark.parametrize("declared", ['""', "", "''"])
def test_an_empty_id_is_no_id(ready, declared):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("id", declared), ("title", '"t"')])
        exported = s.task_export(tid)
        assert tid and exported.startswith(f'---\nid: "{tid}"\n')
        again, _ = parse_task_document(exported)
        assert solar_state.value_of(dict(again)["id"]) == tid


@pytest.mark.parametrize("key", ["", " title", "ti tle", "a:b", "x\ny", "1abc", "\nstatus"])
def test_invalid_keys_are_refused(ready, key):
    with session(ready, auto_backup=False) as s:
        with pytest.raises(solar_state.FormatError, match="not a valid key"):
            s.task_create([(key, "v")])
        tid = s.task_create([("title", '"t"')])
        with pytest.raises(solar_state.FormatError, match="not a valid key"):
            s.task_set(tid, key, "v")


@pytest.mark.parametrize("value", ["a\nstatus: active", "a\r\nb"])
def test_values_that_span_lines_are_refused_outside_import(ready, value):
    with session(ready, auto_backup=False) as s:
        with pytest.raises(solar_state.FormatError, match="spans lines"):
            s.task_create([("title", value)])
        tid = s.task_create([("title", '"t"')])
        with pytest.raises(solar_state.FormatError, match="spans lines"):
            s.task_set(tid, "note", value)


def test_whatever_create_and_set_accept_reimports_identically(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("title", '"con: dos puntos"'), ("x-key_2", "valor   ")], body="b\n")
        s.task_set(tid, "notify_when", "completed")
        doc = s.task_export(tid)
    with cutover(ready) as cut:
        other = cut.session()
        other.conn.execute("DELETE FROM task_events")
        other.conn.execute("DELETE FROM tasks")
        other.task_import(doc)
        assert other.task_export(tid) == doc
        other.conn.close()


# --- review round 3: ids that need escaping, how the block may close ---------

@pytest.mark.parametrize("tid", ['a"b', "a\\nb", "a\nb", "ñ-ü", "back\\slash"])
def test_an_explicit_id_reads_back_identical(ready, tid):
    with session(ready, auto_backup=False) as s:
        assert s.task_create([("title", '"t"')], task_id=tid) == tid
        doc = s.task_export(tid)
    pairs, _ = parse_task_document(doc)
    assert solar_state.value_of(dict(pairs)["id"]) == tid


def test_a_declared_escaped_id_is_kept_as_written(ready):
    with session(ready, auto_backup=False) as s:
        tid = s.task_create([("id", '"a\\"b"'), ("title", '"t"')])
        assert tid == 'a"b'
        doc = s.task_export(tid)
        assert doc.startswith('---\nid: "a\\"b"\ntitle: "t"\n')
    with cutover(ready) as cut:
        other = cut.session()
        other.conn.execute("DELETE FROM task_events")
        other.conn.execute("DELETE FROM tasks")
        assert other.task_import(doc) == 'a"b'
        assert other.task_export('a"b') == doc
        other.conn.close()


@pytest.mark.parametrize("text", ['---\nid: "x"\n---', '---\nid: "x"\n', '---\n---', "---\n\n---\n"])
def test_forms_that_would_not_round_trip_are_refused(text):
    with pytest.raises(solar_state.FormatError):
        parse_task_document(text)


@pytest.mark.parametrize("text", ["---\n---\n", "---\n---\nbody", '---\nid: "x"\n---\n'])
def test_accepted_forms_render_identically(text):
    pairs, body = parse_task_document(text)
    assert render_task_document(pairs, body) == text
