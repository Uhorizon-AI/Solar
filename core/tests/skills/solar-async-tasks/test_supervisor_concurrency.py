"""The supervisor fills the places the applied policy allows, and never more.

Overlap is proved with a synchronisation barrier and start/end events written by the executor
doubles: every executor starts, none may finish until all of them have started. The `active` status
of the console is never the evidence. The doubles never call a provider.
"""
from __future__ import annotations

import calendar

import threading
import time

import pytest

from supervisor_support import wait_until  # first: it puts the skills on sys.path
import solar_state

# Serial: these tests kill real processes and process groups and wait on sub-second sweeps and
# leases. Next to three other busy workers on a CI runner they failed intermittently
# (a lost execution reported as an uncertain group; a stuck start still "active" after its lease),
# so they run alone in the second pass of core/tests/run_suite.sh. Their assertions are unchanged.
pytestmark = pytest.mark.serial


def _all_started_before_any_ended(rig, tasks):
    starts = [rig.first("start", t) for t in tasks]
    ends = [rig.first("end", t) for t in tasks]
    return max(starts) < min(ends)


@pytest.mark.parametrize("limit", [3, 5])
def test_executions_really_overlap_up_to_the_limit(rig, limit):
    rig.apply_policy(global_capacity=limit)
    tasks = [rig.reader(f"Review {i}", provider="claude",
                        spec=dict(barrier=dict(name="g", parties=limit))) for i in range(limit)]
    with rig.running():
        wait_until(lambda: all(rig.status(t) == "completed" for t in tasks), 60, what="all to complete")
    assert len(rig.events("start")) == limit and rig.max_overlap() == limit
    assert _all_started_before_any_ended(rig, tasks)
    assert rig.events("barrier_timeout") == []


def test_the_same_provider_runs_five_at_once_when_its_limit_allows_it(rig):
    rig.apply_policy(global_capacity=5, provider_capacity={"codex": 5})
    tasks = [rig.reader(f"Codex {i}", provider="codex",
                        spec=dict(barrier=dict(name="same", parties=5))) for i in range(5)]
    with rig.running():
        wait_until(lambda: all(rig.status(t) == "completed" for t in tasks), 60, what="five codex runs")
    assert rig.max_overlap() == 5 and _all_started_before_any_ended(rig, tasks)


def test_a_provider_limit_below_the_global_capacity_is_respected(rig):
    rig.apply_policy(global_capacity=5, provider_capacity={"codex": 2})
    codex = [rig.reader(f"Codex {i}", provider="codex", spec=dict(gate="go", hold=0.2)) for i in range(4)]
    other = rig.reader("Claude one", provider="claude", spec=dict(gate="go", hold=0.2))
    with rig.running():
        wait_until(lambda: len(rig.events("start")) >= 3, 30, what="three starts")
        time.sleep(0.6)                       # room for a third codex to start if the limit leaked
        assert len(rig.events("start")) == 3          # two codex plus the claude one
        started = {r["task"] for r in rig.events("start")}
        assert other in started and len(started & set(codex)) == 2
        rig.gate("go")
        wait_until(lambda: all(rig.status(t) == "completed" for t in codex + [other]), 60)


def test_capacity_one_stays_sequential_and_old_tasks_still_run(rig):
    tasks = [rig.legacy(f"Legacy {i}", spec=dict(hold=0.15)) for i in range(3)]
    with rig.running():
        wait_until(lambda: all(rig.status(t) == "completed" for t in tasks), 60)
    assert rig.max_overlap() == 1
    order = [e["task"] for e in rig.events("start")]
    assert sorted(order) == sorted(tasks)
    ends = {e["task"]: e["t"] for e in rig.events("end")}
    starts = {e["task"]: e["t"] for e in rig.events("start")}
    for earlier, later in zip(order, order[1:]):
        assert ends[earlier] <= starts[later], "a second legacy task started before the first ended"


def test_legacy_tasks_never_overlap_even_with_capacity_five(rig):
    rig.apply_policy(global_capacity=5)
    legacy = [rig.legacy(f"Legacy {i}", spec=dict(hold=0.2)) for i in range(3)]
    with rig.running():
        wait_until(lambda: all(rig.status(t) == "completed" for t in legacy), 60)
    assert rig.max_overlap() == 1


def test_a_free_place_is_filled_within_a_second_of_one_ending(rig):
    rig.apply_policy(global_capacity=3)
    first = [rig.reader(f"First {i}", spec=dict(gate=f"g{i}")) for i in range(3)]
    fourth = rig.reader("Fourth", spec=dict(gate="never"))
    with rig.running(poll=1.0) as sup:        # the floor the contract allows
        wait_until(lambda: len(rig.events("start")) == 3, 30, what="three running")
        assert rig.status(fourth) == "queued"
        rig.gate("g0")
        wait_until(lambda: rig.events("start", fourth), 5, what="the fourth to start")
        dispatched = next(t for task, t in sup.dispatch_log if task == fourth)
        gap = dispatched - rig.first("end", first[0])
        assert 0 <= gap <= 1.0, f"the free place was filled after {gap:.2f}s"
        for name in ("g1", "g2", "never"):
            rig.gate(name)
        wait_until(lambda: rig.status(fourth) == "completed", 30)


def test_claims_and_manual_activation_never_exceed_the_capacity(rig):
    rig.apply_policy(global_capacity=3)
    tasks = [rig.reader(f"Race {i}", spec=dict(hold=0.25)) for i in range(12)]
    peaks = []
    stop = threading.Event()

    def watcher():
        while not stop.is_set():
            peaks.append(len(rig.reservations()))
            time.sleep(0.01)

    def activator(ids):
        for task_id in ids:
            with solar_state.session() as store:
                store.task_claim_detail(task_id, "manual-activation")

    seen = threading.Thread(target=watcher, daemon=True)
    seen.start()
    with rig.running(poll=0.1):
        racers = [threading.Thread(target=activator, args=(tasks[i::4],)) for i in range(4)]
        for racer in racers:
            racer.start()
        for racer in racers:
            racer.join()
        wait_until(lambda: all(rig.status(t) == "completed" for t in tasks), 90, what="all twelve")
    stop.set()
    seen.join()
    assert max(peaks) <= 3 and rig.max_overlap() <= 3
    for task_id in tasks:                       # one owner each: exactly one start per task
        assert len(rig.events("start", task_id)) == 1


@pytest.mark.parametrize("before", [3, 5])
def test_lowering_the_capacity_neither_kills_nor_loses_results(rig, before):
    rig.apply_policy(global_capacity=before)
    running = [rig.reader(f"Run {i}", spec=dict(gate="release")) for i in range(before)]
    waiting = rig.reader("Zz after", spec=dict(gate="release"))  # ids sort in claim order
    with rig.running(poll=0.1):
        wait_until(lambda: len(rig.events("start")) == before, 30)
        rig.apply_policy(global_capacity=1)
        time.sleep(0.6)
        assert all(rig.status(t) == "active" for t in running), "the running executions were touched"
        assert rig.status(waiting) == "queued"
        rig.gate("release")
        wait_until(lambda: all(rig.status(t) == "completed" for t in running + [waiting]), 60)
    assert len(rig.events("completed")) == before + 1
    assert rig.events("end", waiting)[0]["t"] >= max(rig.first("end", t) for t in running)


def test_a_steady_flow_of_readers_does_not_starve_an_exclusive_task(rig):
    rig.apply_policy(global_capacity=3, exclusive_wait_seconds=1)
    # The readers must overlap without ever ending together: if all of them end at the same instant the
    # machine is idle and the exclusive task (next in claim order) simply runs, with nothing to starve.
    early = [rig.reader(f"Early {i}", spec=dict(hold=hold)) for i, hold in enumerate((0.5, 0.7, 0.9))]
    exclusive = rig.legacy("Needs the machine", spec=dict(hold=0.1))
    stop = threading.Event()
    added: list[str] = []

    def feed():                              # a continuous flow of new readers
        n = 0
        while not stop.is_set():
            added.append(rig.reader(f"Flow {n}", spec=dict(hold=0.45 + 0.1 * (n % 4))))
            n += 1
            time.sleep(0.1)

    feeder = threading.Thread(target=feed, daemon=True)
    with rig.running(poll=0.1):
        feeder.start()
        wait_until(lambda: rig.status(exclusive) == "completed", 90, what="the exclusive task to run")
        stop.set()
        feeder.join()
        wait_until(lambda: all(rig.status(t) == "completed" for t in early + added), 90)
    # The moment the drain barrier opened is the persisted audit event, read once everything has ended:
    # it cannot be missed by a poll that happened to run late. Its stamp has one-second resolution, so the
    # barrier opened at some instant in [stamp, stamp + 1).
    with solar_state.session() as store:
        events = store.conn.execute("SELECT ts FROM audit WHERE event = 'exclusive_drain_started' "
                                    "AND json_extract(row, '$.task_id') = ?", (exclusive,)).fetchall()
    assert events, "the drain barrier never opened although readers kept arriving"
    opened = calendar.timegm(time.strptime(events[0][0], "%Y-%m-%dT%H:%M:%SZ"))
    began, finished = rig.first("start", exclusive), rig.first("end", exclusive)
    assert began >= opened - 0.01
    readers_started = [e["t"] for e in rig.events("start") if e["task"] != exclusive]
    # once the barrier was open (plus the resolution of its stamp and the time to notice it) no reader was
    # admitted until the exclusive task ended
    assert [t for t in readers_started if opened + 1.0 + 0.15 < t < finished] == []
    # and nothing overlapped the exclusive run itself
    assert [t for t in readers_started if began <= t <= finished] == []
    with solar_state.session() as store:
        recorded = store.conn.execute("SELECT count(*) FROM audit WHERE event = 'exclusive_drain_started'").fetchone()[0]
    assert recorded == 1


def test_a_manual_activation_is_taken_over_and_run_exactly_once(rig):
    rig.apply_policy(global_capacity=3)
    manual = rig.reader("Manual", spec=dict(hold=0.1))
    with solar_state.session() as store:
        claimed = store.task_claim_detail(manual, "activate-1")   # what activate.sh does; no executor yet
    assert claimed["claimed"]
    with rig.running(poll=0.2, sweep=0.3):
        wait_until(lambda: rig.status(manual) == "completed", 30, what="the activation to run")
    assert len(rig.events("start", manual)) == 1
