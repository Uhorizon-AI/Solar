"""Failure, cancellation, timeout, restart and cleanup of supervised executions.

Executor doubles stand in for `execute_active.sh`; nothing calls a provider. The rules under test:
no execution runs twice, a place is not given up before the end of the execution is proved, an owner
that cannot be identified stays blocked (never replaced on a guess), and a failed cleanup blocks the
affected resource without touching the others.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from supervisor_support import alive, wait_until  # first: it puts the skills on sys.path
import solar_state
import supervisor as supervisor_mod
import supervisor_lib as lib
from dead_process import dead_pid


def _body(rig, task_id):
    with solar_state.session() as store:
        return store.task_get(task_id)["body"]


# ---------------------------------------------------------------------------
# failure
# ---------------------------------------------------------------------------

def test_an_executor_that_dies_after_starting_is_failed_and_never_retried(rig):
    task = rig.legacy("Dies midway", spec=dict(outcome="crash_after_attach"))
    with rig.running():
        wait_until(lambda: rig.status(task) == "error", 30, what="the task to be failed")
        time.sleep(0.6)                                    # a retry would show up as a second launch
    assert len(rig.events("launched", task)) == 1
    assert "executor_exited" in _body(rig, task) and "uncertain" in _body(rig, task)
    assert rig.reservations() == []                        # the place went back


def test_an_executor_that_never_starts_gives_the_place_back_and_is_failed_after_three_tries(rig):
    task = rig.legacy("Never starts", spec=dict(outcome="crash_before_attach"))
    with rig.running():
        wait_until(lambda: rig.status(task) == "error", 30, what="the task to give up")
    assert len(rig.events("launched", task)) == 3          # nothing ran: retried, then reported
    assert "executor_start_failed" in _body(rig, task) and rig.reservations() == []


def test_a_failed_neighbour_does_not_cancel_an_independent_task(rig):
    rig.apply_policy(global_capacity=3)
    broken = rig.reader("Broken", spec=dict(outcome="crash_after_attach", barrier=dict(name="b", parties=2)))
    fine = rig.reader("Fine", spec=dict(barrier=dict(name="b", parties=2), hold=0.2))
    with rig.running():
        wait_until(lambda: rig.status(fine) == "completed" and rig.status(broken) == "error", 30)
    assert len(rig.events("completed", fine)) == 1


# ---------------------------------------------------------------------------
# cancellation and timeout
# ---------------------------------------------------------------------------

def test_cancelling_stops_only_that_group_and_frees_the_place_after_it_is_gone(rig):
    rig.apply_policy(global_capacity=3)
    doomed = rig.reader("Doomed", spec=dict(outcome="hang", straggler=True))
    sibling = rig.reader("Sibling", spec=dict(gate="never"))
    with rig.running(cancel_grace=0.5):
        wait_until(lambda: len(rig.events("start")) == 2, 30)
        doomed_pid = rig.events("start", doomed)[0]["pid"]
        straggler = int((rig.double_dir / f"straggler-{doomed}.pid").read_text())
        sibling_pid = rig.events("start", sibling)[0]["pid"]
        with solar_state.session() as store:
            store.cancellation_request(doomed)
        # the instant the task leaves `active`, its whole group must already be gone
        wait_until(lambda: rig.status(doomed) == "cancelled", 30, interval=0.005, what="the cancellation")
        assert not alive(doomed_pid) and not alive(straggler), "the place was freed before the group ended"
        assert alive(sibling_pid) and rig.status(sibling) == "active", "a neighbour's group was touched"
        rig.gate("never")
        wait_until(lambda: rig.status(sibling) == "completed", 30)


def test_an_execution_whose_lease_ran_out_is_stopped_and_reported(rig):
    task = rig.legacy("Silent", spec=dict(outcome="hang", straggler=True))
    with rig.running(sweep=0.3):
        wait_until(lambda: rig.events("hang", task), 30)
        pid = rig.events("hang", task)[0]["pid"]
        with solar_state.session() as store:             # the lease it renews stopped being renewed
            store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z' "
                               "WHERE task_id = ?", (task,))
        wait_until(lambda: rig.status(task) == "error", 30, what="the timeout to be handled")
        assert not alive(pid)
    assert "lease_expired" in _body(rig, task) and rig.reservations() == []


# ---------------------------------------------------------------------------
# restart: no double execution, no premature release
# ---------------------------------------------------------------------------

def test_a_restarted_supervisor_adopts_running_executions_and_runs_nothing_twice(rig):
    rig.apply_policy(global_capacity=3)
    tasks = [rig.reader(f"Long {i}", spec=dict(gate="release")) for i in range(2)]
    first = rig.build()
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("code", first.run()), daemon=True)
    thread.start()
    rig.threads.append(thread)
    wait_until(lambda: len(rig.events("start")) == 2, 30)
    rig.stop_abruptly(first, thread)                       # the supervisor goes away; the executions live on
    assert all(rig.status(t) == "active" for t in tasks)
    with rig.running() as second:
        wait_until(lambda: len(second.children) == 2, 30, what="both executions adopted")
        assert all(c.adopted for c in second.children.values())
        time.sleep(0.5)
        assert len(rig.events("launched")) == 2, "an adopted execution was dispatched again"
        rig.gate("release")
        wait_until(lambda: all(rig.status(t) == "completed" for t in tasks), 30)
    assert len(rig.events("completed")) == 2


def test_a_claim_nobody_dispatched_goes_back_to_the_queue_and_runs_once(rig):
    rig.apply_policy(global_capacity=3)
    task = rig.reader("Orphan claim", spec=dict(hold=0.1))
    with solar_state.session() as store:
        claimed = store.task_claim_next("supervisor-dead")
        token = claimed["token"]
    lib.write_json_atomic(rig.ctx.children_file, {"version": 1, "executions": [
        {"task_id": task, "token": token, "worker": "supervisor-dead", "pid": None, "pgid": None,
         "started": None, "dispatched_epoch": time.time(), "access": {}}]}, mode=0o600)
    with rig.running():
        wait_until(lambda: rig.status(task) == "completed", 30, what="the claim to be given back and run")
    assert len(rig.events("start", task)) == 1


def test_an_executor_gone_with_live_strangers_in_its_group_is_blocked_not_killed(rig):
    task = rig.legacy("Group left behind", spec=dict(gate="never"))
    with solar_state.session() as store:
        token = store.task_claim_next("supervisor-dead")["token"]
        gone = dead_pid()
        store.reservation_attach(task, token, pid=gone)
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    try:
        lib.write_json_atomic(rig.ctx.children_file, {"version": 1, "executions": [
            {"task_id": task, "token": token, "worker": "supervisor-dead", "pid": gone, "pgid": stranger.pid,
             "started": None, "dispatched_epoch": time.time(), "access": {}}]}, mode=0o600)
        with rig.running(sweep=0.3) as sup:
            wait_until(lambda: task in sup.blocked, 30, what="the group to be blocked")
            assert sup.blocked[task]["reason"] == "group_uncertain"
            time.sleep(0.8)
            assert alive(stranger.pid), "a process that cannot be proved to be the execution's was killed"
            assert rig.status(task) == "active" and rig.events("launched", task) == []
            stranger.kill()
            stranger.wait()
            wait_until(lambda: rig.status(task) == "error", 30, what="the task to be failed once the group is gone")
            assert task not in sup.blocked
    finally:
        if stranger.poll() is None:
            stranger.kill()
            stranger.wait()
    assert "executor_lost" in _body(rig, task) and len(rig.events("launched", task)) == 0


def test_an_owner_that_cannot_be_identified_is_blocked_and_left_alone(rig, monkeypatch):
    task = rig.legacy("Unknown owner", spec=dict(gate="never"))
    with solar_state.session() as store:
        token = store.task_claim_next("someone-else")["token"]
        store.reservation_attach(task, token, pid=dead_pid())
    real = lib.matches
    monkeypatch.setattr(lib, "matches", lambda pid, started: ("unknown", {"reason": "ps denied"})
                        if pid else real(pid, started))
    with rig.running(sweep=0.2) as sup:
        wait_until(lambda: task in sup.blocked, 30)
        assert sup.blocked[task]["reason"] == "owner_unverifiable"
        time.sleep(0.5)
        assert rig.status(task) == "active" and rig.events("launched", task) == []
        monkeypatch.setattr(lib, "matches", real)           # the table answers again: judged once more
        wait_until(lambda: task not in sup.blocked, 30)
    assert rig.status(task) == "active"                      # its lease still stands: nobody replaced it


# ---------------------------------------------------------------------------
# cleanup that cannot be proved
# ---------------------------------------------------------------------------

def test_a_failed_cleanup_blocks_that_resource_for_every_entry_point_and_survives_a_restart(rig, monkeypatch):
    rig.apply_policy(global_capacity=3)
    held = rig.reader("Holds demo", resources=["demo"], spec=dict(hold=0.1))
    real_members = supervisor_mod.group_members
    stuck = {"on": True}

    def members(pgid):
        launched = [e["pid"] for e in rig.events("launched", held)]
        if stuck["on"] and pgid in launched:
            return [pgid]                                     # something in that group never goes away
        return real_members(pgid)

    monkeypatch.setattr(supervisor_mod, "group_members", members)
    with rig.running(sweep=0.3, term_grace=0.2, kill_wait=0.2) as sup:
        wait_until(lambda: held in sup.blocked, 30, what="the cleanup to be blocked")
        assert sup.blocked[held]["reason"] == "cleanup_failed"
        same = rig.reader("Wants demo", resources=["demo"], spec=dict(hold=0.05))
        other = rig.reader("Wants other", resources=["other"], spec=dict(hold=0.05))
        wait_until(lambda: rig.status(other) == "completed", 30, what="the unrelated task to run")
        time.sleep(0.6)
        assert rig.status(same) == "queued" and rig.events("launched", same) == []
        # not only the supervisor's claims: a manual activation is refused by the state itself
        with solar_state.session() as store:
            assert store.task_claim_detail(same, "activate-1") == dict(claimed=False, reason="resource:demo")
        assert bool(solar_state.cleanup_holds(rig.runtime))
    # the supervisor restarts: the hold is still there, for it and for a manual activation
    with rig.running(sweep=0.3, term_grace=0.2, kill_wait=0.2) as again:
        wait_until(lambda: held in again.blocked, 30, what="the blocked execution to be remembered")
        time.sleep(0.6)
        assert rig.status(same) == "queued"
        with solar_state.session() as store:
            assert store.task_claim_detail(same, "activate-2")["reason"] == "resource:demo"
        stuck["on"] = False                                    # recovery: the group is really gone
        wait_until(lambda: rig.status(same) == "completed", 30, what="the resource to be free again")
        assert held not in again.blocked
    assert not solar_state.cleanup_holds(rig.runtime)


def test_a_failed_check_of_the_commands_group_keeps_the_hold_through_sweeps_and_a_restart(rig, monkeypatch):
    rig.apply_policy(global_capacity=3)
    held = rig.reader("Left a command", resources=["demo"], spec=dict(provider_leave=True, hold=0.1))
    real_members = supervisor_mod.group_members
    stuck = {"on": True}

    def members(pgid):
        provider = [e["provider_pid"] for e in rig.events("provider", held)]
        if stuck["on"] and pgid in provider:
            return [pgid]                       # the command's group cannot be proved gone
        return real_members(pgid)

    monkeypatch.setattr(supervisor_mod, "group_members", members)
    with rig.running(sweep=0.2, term_grace=0.2, kill_wait=0.2) as sup:
        wait_until(lambda: held in sup.blocked, 30, what="the cleanup to be blocked")
        entry = sup.blocked[held]
        provider_pid = rig.events("provider", held)[0]["provider_pid"]
        assert provider_pid in entry["pgids"] and len(entry["pgids"]) == 2     # both groups are remembered
        same = rig.reader("Wants demo", resources=["demo"], spec=dict(hold=0.05))
        time.sleep(1.0)                          # several sweeps: the executor's group is empty, the command's is not
        assert held in sup.blocked and rig.status(same) == "queued"
        with solar_state.session() as store:
            assert store.task_claim_detail(same, "activate-1")["reason"] == "resource:demo"
    with rig.running(sweep=0.2, term_grace=0.2, kill_wait=0.2) as again:        # and across a restart
        wait_until(lambda: held in again.blocked, 30)
        time.sleep(0.8)
        assert held in again.blocked and rig.status(same) == "queued"
        stuck["on"] = False
        wait_until(lambda: rig.status(same) == "completed", 30, what="the resource to be free once both groups are gone")


def test_an_execution_keeps_its_place_from_the_dispatch_until_it_is_proved_over(rig):
    """Even with no supervisor running when the executor finishes, nothing conflicting is admitted."""
    rig.apply_policy(global_capacity=3)
    held = rig.reader("Runs", resources=["demo"], spec=dict(gate="release"))
    same = rig.reader("Wants demo", resources=["demo"], spec=dict(hold=0.05))
    first = rig.build()
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("code", first.run()), daemon=True)
    thread.start()
    rig.threads.append(thread)
    wait_until(lambda: rig.events("start", held), 30)
    rig.stop_abruptly(first, thread)                           # the supervisor goes away while it runs
    rig.gate("release")
    wait_until(lambda: rig.status(held) == "completed", 30)      # result committed, execution still held
    assert rig.reservations_of(held)["phase"] == "ending"
    with solar_state.session() as store:
        assert store.task_claim_detail(same, "activate-1") == dict(claimed=False, reason="resource:demo")
    # The schema must recover this even when the supervisor's per-process files are gone.
    rig.ctx.children_file.unlink(missing_ok=True)
    rig.ctx.blocked_file.unlink(missing_ok=True)
    with rig.running(sweep=0.2):                               # a new supervisor proves it over, then it is free
        wait_until(lambda: rig.status(same) == "completed", 30)
    assert len(rig.events("launched", held)) == 1
    assert not solar_state.cleanup_holds(rig.runtime)


def _previous_hold(rig, task_id, pgids, **extra):
    entry = dict(task_id=task_id, while_reserved=True, pgids=pgids, access_class="declared", provider="codex",
                 scopes=[], resources=["demo"])
    entry.update(extra)
    solar_state.cleanup_holds_write(rig.runtime, [entry])


def test_a_previous_hold_whose_groups_are_all_gone_is_dropped_at_start(rig):
    gone = dead_pid()
    _previous_hold(rig, "ghost", [gone])
    with rig.running() as sup:
        assert "ghost" not in sup.blocked, "a hold with nothing left alive must not block the supervisor"
    assert lib.observe(rig.ctx)["reason"] != "recovery_required"
    assert not solar_state.cleanup_holds(rig.runtime)


def test_a_previous_hold_with_a_live_group_stays_blocked_until_it_is_empty(rig):
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    try:
        _previous_hold(rig, "ghost", [dead_pid(), stranger.pid])
        with rig.running(sweep=0.2) as sup:
            assert sup.blocked["ghost"]["reason"] == "cleanup_unverified"
            assert stranger.pid in sup.blocked["ghost"]["pgids"]
            time.sleep(0.8)
            assert "ghost" in sup.blocked and bool(solar_state.cleanup_holds(rig.runtime))
            stranger.kill()
            stranger.wait()
            wait_until(lambda: "ghost" not in sup.blocked, 30, what="the hold to clear once the group is empty")
    finally:
        if stranger.poll() is None:
            stranger.kill()
            stranger.wait()


def test_a_previous_hold_that_cannot_be_checked_stays_blocked(rig, monkeypatch):
    monkeypatch.setattr(supervisor_mod, "group_members", lambda pgid: None)       # ps does not answer
    _previous_hold(rig, "ghost", [dead_pid()])
    with rig.running(sweep=0.2) as sup:
        time.sleep(0.8)
        assert sup.blocked["ghost"]["reason"] == "cleanup_unverified"


def test_the_commands_group_is_in_the_hold_while_the_execution_runs(rig):
    rig.apply_policy(global_capacity=3)
    task = rig.reader("Runs a command", spec=dict(provider_leave=True, gate="release"))
    with rig.running():
        try:
            provider = wait_until(lambda: rig.events("provider", task), 30)[0]
            executor = wait_until(lambda: rig.events("launched", task), 30)[0]
            expected = [executor["pid"], provider["provider_pid"]]
            # In-memory discovery precedes the atomic publication of cleanup holds.
            # Wait for the persistent contract consumed by admission, not that interval.
            wait_until(lambda: any(h["task_id"] == task and h["pgids"] == expected
                                   for h in solar_state.cleanup_holds(rig.runtime)),
                       10, what="both owned groups to be published in the cleanup hold")
        finally:
            rig.gate("release")  # a failed assertion must still let the fixture drain
        wait_until(lambda: rig.status(task) == "completed", 30)


def test_a_process_table_that_does_not_answer_is_not_an_empty_group(rig, monkeypatch):
    task = rig.legacy("Group in doubt", spec=dict(gate="never"))
    with solar_state.session() as store:
        token = store.task_claim_next("supervisor-dead")["token"]
        store.reservation_attach(task, token, pid=dead_pid())
    lib.write_json_atomic(rig.ctx.children_file, {"version": 1, "executions": [
        {"task_id": task, "token": token, "worker": "supervisor-dead", "pid": dead_pid(), "pgid": 424242,
         "started": None, "dispatched_epoch": time.time(), "access": {}}]}, mode=0o600)
    monkeypatch.setattr(supervisor_mod, "group_members", lambda pgid: None)     # ps would not answer
    with rig.running(sweep=0.2) as sup:
        wait_until(lambda: task in sup.blocked, 30)
        assert sup.blocked[task]["reason"] == "group_uncertain" and "could not be asked" in sup.blocked[task]["detail"]
        time.sleep(0.6)
        assert rig.status(task) == "active" and rig.reservations_of(task) is not None, \
            "the reservation was given up without being able to check the group"


def test_what_is_still_being_collected_is_not_claimed_again(rig):
    sup = rig.build()
    sup.children["recurring"] = supervisor_mod.Execution("recurring", "t", "w")
    assert "recurring" in sup._exclude()


def test_an_executor_that_hangs_before_taking_its_execution_is_stopped_when_its_lease_runs_out(rig):
    task = rig.legacy("Stuck at the door", spec=dict(outcome="hang_before_attach"))
    with rig.running(sweep=0.3, cooldown=30) as sup:
        wait_until(lambda: rig.events("hang_before_attach", task), 30)
        pid = rig.events("hang_before_attach", task)[0]["pid"]
        with solar_state.session() as store:
            store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z' "
                               "WHERE task_id = ?", (task,))
        # The counter increments before _give_back commits the queue transition.
        # Observe both results instead of treating an in-memory counter as a commit.
        wait_until(lambda: sup.start_failures.get(task) == 1 and rig.status(task) == "queued",
                   30, what="the stuck start to be given back to the queue")
        assert not alive(pid)
        assert rig.status(task) == "queued", "nothing ran, so the claim goes back to the queue"


# ---------------------------------------------------------------------------
# drain and maintenance
# ---------------------------------------------------------------------------

def test_a_drain_stops_dispatching_waits_for_the_running_and_loses_nothing(rig):
    rig.apply_policy(global_capacity=2)
    running = [rig.reader(f"Run {i}", spec=dict(gate="release")) for i in range(2)]
    later = rig.reader("Zz later", spec=dict(hold=0.05))
    sup = rig.build()
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("code", sup.run()), daemon=True)
    thread.start()
    rig.threads.append(thread)
    wait_until(lambda: len(rig.events("start")) == 2, 30)
    sup._request_drain("test")
    time.sleep(0.8)
    assert thread.is_alive() and rig.status(later) == "queued", "it exited early or dispatched while draining"
    rig.gate("release")
    thread.join(30)
    assert not thread.is_alive() and box["code"] == 0
    assert all(rig.status(t) == "completed" for t in running) and rig.status(later) == "queued"
    document = lib.read_json(rig.ctx.identity_file)
    assert document["state"] == "stopped" and document["children"] == []


def test_nothing_is_dispatched_while_an_update_holds_the_barrier(rig):
    task = rig.legacy("Waits for the update", spec=dict(hold=0.05))
    barrier = rig.runtime / "maintenance.json"
    barrier.write_text(json.dumps(dict(operation="update")))
    with rig.running():
        time.sleep(1.0)
        assert rig.status(task) == "queued" and rig.events("launched") == []
        barrier.unlink()
        wait_until(lambda: rig.status(task) == "completed", 30)


def test_a_resource_hook_that_blocks_gives_the_claim_back(rig):
    task = rig.legacy("Needs demo", cleanup_required="true", resources="demo", spec=dict(hold=0.05))
    hook = rig.task_root / "hooks" / "demo" / "pre_start.sh"
    hook.parent.mkdir(parents=True)
    flag = rig.tmp / "demo-free"
    hook.write_text(f"#!/bin/bash\n[ -f '{flag}' ]\n")
    hook.chmod(0o755)
    def claim_was_given_back():
        # Observe a committed transition, not the queued row between retries.
        with solar_state.session() as store:
            return store.conn.execute(
                "SELECT 1 FROM task_events WHERE task_id = ? AND from_status = 'active' "
                "AND to_status = 'queued' LIMIT 1", (task,)).fetchone() is not None

    with rig.running():
        wait_until(claim_was_given_back, 30, what="the blocked hook to give its claim back")
        assert rig.events("launched") == []
    # Draining ends retries before asserting their stable final state.
    assert rig.status(task) == "queued" and rig.reservations() == []
    flag.write_text("1")
    with rig.running():
        wait_until(lambda: rig.status(task) == "completed", 30)
    assert len(rig.events("start", task)) == 1
