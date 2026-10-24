"""Issue #39: terminal task state never proves that the execution is over."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest

import solar_state as st
from dead_process import dead_pid
from test_reservations import access, claim, make, set_policy, store, verified_profile  # noqa: F401


@contextmanager
def process():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    try:
        yield child
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)


@pytest.mark.parametrize("capacity", [1, 3, 5])
def test_result_does_not_release_owner_or_allow_conflicting_manual_worker_or_adoption(store, capacity):
    set_policy(store, global_capacity=capacity)
    a = make(store, "A", policy=access(resources=["shared"]))
    b = make(store, "B", policy=access(resources=["shared"]))
    token = claim(store, a)["token"]
    with process() as owner:
        store.reservation_attach(a, token, pid=owner.pid)
        store.task_complete(a, token=token)
        assert store.task_status(a) == "completed"
        assert store.reservation_for(a)["phase"] == "ending"
        assert not claim(store, b)["claimed"]
        assert store.task_claim_next("worker") is None
        taken = store.task_adopt(a, "recover")
        assert taken == dict(adopted=False, released=False, reason="owner_alive")
        with pytest.raises(st.StaleToken, match="ending"):
            store.reservation_heartbeat(a, token)
    recovered = store.task_adopt(a, "recover")
    assert recovered == dict(adopted=False, released=True, reason="ending_released")
    assert store.task_status(a) == "completed" and store.reservation_for(a) is None
    assert claim(store, b)["claimed"]


def test_command_group_stays_held_after_owner_dies_and_state_reopens(store, ready):
    set_policy(store, global_capacity=5)
    a = make(store, "A", policy=access(resources=["shared"]))
    b = make(store, "B", policy=access(resources=["shared"]))
    token = claim(store, a)["token"]
    with process() as command:
        with process() as owner:
            store.reservation_attach(a, token, pid=owner.pid)
            store.task_record(a, pid=command.pid, token=token)
            store.task_complete(a, token=token)
        with st.session(ready, auto_backup=False) as reopened:
            taken = reopened.task_adopt(a, "recover")
            assert not taken["adopted"] and not taken["released"]
            assert taken["reason"] == "cleanup_unverifiable"
            assert not claim(reopened, b)["claimed"]
    assert store.task_adopt(a, "recover")["released"]
    assert store.task_status(a) == "completed"


def test_unknown_group_query_keeps_reservation_and_approval(store):
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    store.reservation_attach(a, token, pid=dead_pid())
    store.task_complete(a, token=token)
    before = store.task_export(a)
    result = store.task_adopt(a, "recover", groups=lambda group: None)
    assert result["reason"] == "cleanup_unverifiable"
    assert store.reservation_for(a)["token"] == token and store.task_export(a) == before
    assert store.task_adopt(a, "recover")["released"]


def test_queued_recurrence_cannot_claim_itself_before_ending_is_released(store):
    set_policy(store, global_capacity=5)
    a = make(store, "A", policy=access(), recurring="true", recurring_min_interval="0")
    token = claim(store, a)["token"]
    with process() as owner:
        store.reservation_attach(a, token, pid=owner.pid)
        assert store.task_complete(a, token=token) == "queued"
        assert claim(store, a) == dict(claimed=False, reason="execution_ending")
        assert store.task_claim_next("worker") is None
    assert store.task_adopt(a, "recover")["released"]
    assert claim(store, a)["claimed"]


def v6(store):
    store.conn.execute("DROP TABLE token_observations")
    store.conn.execute("DROP TABLE token_attempts")
    store.conn.execute("ALTER TABLE execution_reservations DROP COLUMN execution_id")
    store.conn.execute("DROP TABLE execution_lifecycle")
    store.conn.execute("DROP TABLE execution_groups")
    store.conn.execute("DROP TABLE execution_cleanup_holds")
    store.conn.execute("PRAGMA user_version = 6")


@pytest.mark.parametrize("bad", [False, True])
def test_v6_cutover_imports_legacy_holds_once_and_preserves_applied_policy(ready, bad):
    with st.session(ready, auto_backup=False) as store:
        set_policy(store, global_capacity=3)
        expected = store.async_policy()
        v6(store)
    legacy = ready / st.CLEANUP_HOLDS_NAME
    legacy.parent.mkdir(parents=True, exist_ok=True)
    held = dict(task_id="ghost", access_class="exclusive", pgids=[dead_pid()])
    legacy.write_text("{broken" if bad else json.dumps(dict(holds=[held])))
    with st.cutover(ready) as cut:
        result = cut.upgrade_schema()
    assert result["from_version"] == 6 and result["to_version"] == st.SCHEMA_VERSION and result["backup"]
    assert not legacy.exists() and legacy.with_suffix(".json.migrated-v7").exists()
    holds = st.cleanup_holds(ready)
    assert holds[0].get("unreadable") if bad else holds == [held]
    with st.session(ready, auto_backup=False) as reopened:
        assert reopened.async_policy() == expected
        b = make(reopened, "B", policy=access())
        assert not claim(reopened, b)["claimed"]
    with st.cutover(ready) as cut:
        assert cut.upgrade_schema()["backup"] is None
    assert st.cleanup_holds(ready) == holds


def test_interrupted_v7_import_rolls_back_schema_and_keeps_legacy_source(ready, monkeypatch):
    with st.session(ready, auto_backup=False) as store:
        v6(store)
    legacy = ready / st.CLEANUP_HOLDS_NAME
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(dict(holds=[dict(task_id="ghost", access_class="exclusive")])))
    original = legacy.read_bytes()
    monkeypatch.setattr(st, "MIGRATIONS", st.MIGRATIONS[:-1] + (st.MIGRATIONS[-1] + "; INVALID SQL",))
    import sqlite3
    with st.cutover(ready) as cut, pytest.raises(sqlite3.Error):
        cut.upgrade_schema()
    with sqlite3.connect(st.db_path(ready)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'execution_cleanup_holds'").fetchone()
    assert legacy.read_bytes() == original


def test_every_recorded_command_group_is_retained_even_after_a_later_pid_is_recorded(store):
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    with process() as first_command:
        with process() as second_command:
            with process() as owner:
                store.reservation_attach(a, token, pid=owner.pid)
                store.task_record(a, pid=first_command.pid, token=token)
                store.task_record(a, pid=second_command.pid, token=token)
                store.task_complete(a, token=token)
        assert first_command.pid in store.reservation_for(a)["pgids"]
        assert not store.task_adopt(a, "recover")["released"]
    assert store.task_adopt(a, "recover")["released"]


def test_blocked_execution_counts_one_place_even_with_an_additional_cleanup_hold(store, ready):
    set_policy(store, global_capacity=3)
    a = make(store, "A", policy=access(resources=["shared"]))
    token = claim(store, a)["token"]
    with process() as owner:
        store.reservation_attach(a, token, pid=owner.pid)
        store.task_complete(a, token=token)
        st.cleanup_holds_write(ready, [dict(task_id=a, pgids=[owner.pid], access_class="declared")])
        b = make(store, "B", policy=access())
        c = make(store, "C", policy=access())
        assert claim(store, b)["claimed"]
        assert claim(store, c)["claimed"]
    assert store.task_adopt(a, "recover")["released"]


def test_ending_owner_that_exited_but_has_not_been_waited_for_is_not_alive(store):
    """A supervisor restart may inherit an unreaped executor; zombies have no effects."""
    import time
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    owner = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read(1)"],
                             stdin=subprocess.PIPE, start_new_session=True)
    try:
        store.reservation_attach(a, token, pid=owner.pid)
        store.task_complete(a, token=token)
        owner.stdin.write(b'x')
        owner.stdin.flush()
        until = time.monotonic() + 5
        while st._process_identity(owner.pid) is not None:
            assert time.monotonic() < until, "executor did not exit"
            time.sleep(.01)
        assert store.task_adopt(a, "recover")["released"]
    finally:
        owner.stdin.close()
        owner.wait(timeout=10)


def test_legacy_owner_without_recorded_groups_cannot_be_adopted_on_a_guess(store):
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    store.reservation_attach(a, token, pid=dead_pid())
    store.conn.execute("DELETE FROM execution_groups WHERE token = ?", (token,))
    store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z'")
    assert store.task_adopt(a, "recover") == dict(adopted=False, reason="cleanup_unverifiable")
    assert store.reservation_for(a)["token"] == token


def test_capacity_projection_distinguishes_result_completion_from_execution_release(store):
    import runtime_views
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    with process() as owner:
        store.reservation_attach(a, token, pid=owner.pid)
        store.task_complete(a, token=token)
        projected = runtime_views.console_capacity(store)
        assert projected["running"][0]["phase"] == "ending"
        assert projected["running"][0]["id"] == a
    assert store.task_adopt(a, "recover")["released"]
    assert runtime_views.console_capacity(store)["running"] == []
