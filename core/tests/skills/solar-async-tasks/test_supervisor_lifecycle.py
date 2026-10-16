"""The resident supervisor as the scripts start, observe and stop it: real processes, temporary
runtimes, local deterministic tasks (no provider), and a tick that is a plain subprocess.

Nothing here touches the machine runtime, port 9000 or a LaunchAgent: a LaunchAgent tick is simulated
by running the orchestrator once as a child process whose pipes are captured, which is exactly what
would hang if the supervisor inherited them.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from supervisor_support import Rig, alive, wait_until  # first: it puts the skills on sys.path
import solar_state
import supervisor_lib as lib
from runtime_owner import claim_test_owner

FAST = {"SOLAR_SUPERVISOR_HANDSHAKE_SECONDS": "1.0"}


def _mark(rig, body: str, marker: Path) -> str:
    return rig.local_script(f'echo "start $*" >> "{marker}"\n{body}\necho "end $*" >> "{marker}"\n')


def _lines(marker: Path) -> list[str]:
    return marker.read_text().splitlines() if marker.is_file() else []


def _ready(rig, **env):
    out = rig.script("ensure_async_tasks.sh", extra_env=env)
    assert out.returncode == 0, out.stdout + out.stderr
    return rig.answer(out)


# ---------------------------------------------------------------------------
# one supervisor per runtime
# ---------------------------------------------------------------------------

def test_two_simultaneous_ensures_start_a_single_supervisor(rig):
    results = []

    def tick():
        # a machine-wide worker guard override must not matter: ownership is the runtime's own lock
        results.append(rig.script("ensure_async_tasks.sh",
                                  extra_env={"SOLAR_TASK_WORKER_LOCK": str(rig.tmp / "somewhere-else.lock")}))

    ticks = [threading.Thread(target=tick) for _ in range(2)]
    for t in ticks:
        t.start()
    for t in ticks:
        t.join(60)
    answers = [rig.answer(r) for r in results]
    assert all(r.returncode in (0, 10) for r in results), [r.stdout + r.stderr for r in results]
    assert sum(1 for a in answers if a.get("launched")) == 1, "both ticks started a candidate"
    wait_until(lambda: rig.identity() and rig.identity()["state"] == "ready", 20)
    time.sleep(0.5)
    assert (rig.ctx.support / "supervisor.log").read_text().count("] ready:") == 1
    assert rig.ctx.lock_file == rig.runtime / "async-tasks" / ".locks" / "supervisor.lock"
    assert len({a["identity"]["pid"] for a in answers}) == 1


def test_two_candidates_racing_for_the_lock_leave_exactly_one_supervisor(rig):
    candidates = [subprocess.Popen([sys.executable, str(lib.HERE / "supervisor.py"), "run"], env=rig.env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, start_new_session=True) for _ in range(2)]
    try:
        wait_until(lambda: any(c.poll() is not None for c in candidates), 20, what="the loser to leave")
        loser = next(c for c in candidates if c.poll() is not None)
        winner = next(c for c in candidates if c is not loser)
        assert loser.returncode == 0 and "another supervisor owns this runtime" in loser.stdout.read()
        wait_until(lambda: rig.supervisor_pid() == winner.pid, 20, what="the winner's identity")
        assert winner.poll() is None
    finally:
        for c in candidates:
            if c.poll() is None:
                c.kill()
                c.wait()


def test_two_runtimes_have_independent_locks(tmp_path, monkeypatch):
    first = Rig(tmp_path / "a", monkeypatch, name="a")
    second = Rig(tmp_path / "b", monkeypatch, name="b")
    try:
        a = _ready(first)
        b = _ready(second)
        assert a["identity"]["pid"] != b["identity"]["pid"]
        assert first.ctx.lock_file != second.ctx.lock_file
        assert a["identity"]["runtime"] == str(first.runtime) and b["identity"]["runtime"] == str(second.runtime)
        stop = first.script("stop_supervisor.sh", "--drain", "--timeout", "20")
        assert stop.returncode == 0, stop.stdout
        assert second.supervisor_pid() == b["identity"]["pid"], "stopping one runtime's supervisor touched the other"
    finally:
        first.cleanup()
        second.cleanup()


def test_ensure_observes_and_never_touches_the_supervisor_lock_or_pid(rig):
    _ready(rig)
    ident_before = rig.identity()
    lock_before = rig.ctx.lock_file.read_text()
    # the supervisor holds the lock: an observer taking it would fail; it must not even try
    with open(rig.ctx.lock_file, "a+") as probe:
        with pytest.raises(BlockingIOError):
            fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    for _ in range(3):
        assert rig.script("check_async_tasks.sh").returncode == 0
        assert rig.script("ensure_async_tasks.sh").returncode == 0
    assert rig.ctx.lock_file.read_text() == lock_before
    assert rig.identity()["pid"] == ident_before["pid"] and rig.identity()["started"] == ident_before["started"]


def test_a_tick_returns_while_the_supervisor_stays_alive_and_holds_no_pipe(rig):
    (rig.workspace / ".env").write_text("SOLAR_SYSTEM_FEATURES=async-tasks\n")
    env = {**rig.env, "SOLAR_SYSTEM_LOCK_DIR": str(rig.tmp / "orchestrator.lock"), "SOLAR_ROOT": str(lib.HERE.parents[3])}
    start = time.monotonic()
    tick = subprocess.run(["bash", str(lib.HERE.parents[1] / "solar-system" / "scripts" / "run_orchestrator.sh"), "--once"],
                          env=env, capture_output=True, text=True, timeout=60, cwd=rig.workspace)
    took = time.monotonic() - start
    assert tick.returncode == 0, tick.stdout + tick.stderr
    assert took < 5 + 5 and rig.supervisor_pid() is not None, "the tick waited for the supervisor"
    stamp = json.loads((rig.runtime / "system" / "pass-stamp.json").read_text())
    assert stamp["features"] == {"async-tasks": "ok"}


# ---------------------------------------------------------------------------
# 0 ready / 10 starting / 20 blocked / 1 failed, within the handshake budget
# ---------------------------------------------------------------------------

def test_ensure_answers_within_five_seconds_while_slow_executions_run(rig):
    marker = rig.tmp / "slow.log"
    rel = _mark(rig, "sleep 8", marker)
    rig.local("Slow one", rel, timeout=60)
    rig.local("Slow two", rel, timeout=60)
    _ready(rig)
    wait_until(lambda: _lines(marker) == ["start Slow one"] or "start Slow one" in _lines(marker), 20)
    for _ in range(3):
        began = time.monotonic()
        out = rig.script("ensure_async_tasks.sh")
        assert out.returncode == 0 and time.monotonic() - began < 5
    assert rig.identity()["children"], "the supervisor lost sight of its running execution"


def test_starting_with_a_live_identity_is_10_then_ready_and_the_same_process_continues(rig):
    runtime_lock = rig.runtime / "state.lock"
    holder = open(runtime_lock, "a+")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)           # a cutover in progress: the candidate cannot open the state
    try:
        began = time.monotonic()
        first = rig.script("ensure_async_tasks.sh", extra_env=FAST)
        answer = rig.answer(first)
        assert first.returncode == 10 and answer["state"] == "starting" and answer["identity"]["pid"]
        assert time.monotonic() - began < 5, "ensure waited for more than the handshake budget"
        pid = answer["identity"]["pid"]
        again = rig.script("ensure_async_tasks.sh", extra_env=FAST)
        assert again.returncode == 10 and rig.answer(again)["identity"]["pid"] == pid, "the next tick made another candidate"
        assert rig.answer(again)["launched"] is False
    finally:
        holder.close()                                    # the cutover ends
    wait_until(lambda: rig.identity() and rig.identity()["reconciled"], 40, what="the handshake")
    ready = rig.script("ensure_async_tasks.sh")
    assert ready.returncode == 0 and rig.answer(ready)["identity"]["pid"] == pid


def test_starting_for_more_than_the_limit_is_blocked_not_replaced(rig):
    holder = open(rig.runtime / "state.lock", "a+")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        first = rig.script("ensure_async_tasks.sh", extra_env=FAST)
        pid = rig.answer(first)["identity"]["pid"]
        time.sleep(1.2)
        late = rig.script("ensure_async_tasks.sh", extra_env={**FAST, "SOLAR_SUPERVISOR_STARTING_LIMIT": "1"})
        answer = rig.answer(late)
        assert late.returncode == 20 and answer["reason"] == "starting_timeout" and answer["launched"] is False
        assert alive(pid), "the slow owner was replaced or killed"
    finally:
        holder.close()


def test_a_lock_held_by_something_that_shows_no_identity_is_blocked(rig):
    rig.ctx.locks.mkdir(parents=True, exist_ok=True)
    holder = open(rig.ctx.lock_file, "a+")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)           # an owner nobody can name
    try:
        began = time.monotonic()
        out = rig.script("ensure_async_tasks.sh")
        answer = rig.answer(out)
        assert out.returncode == 20 and answer["state"] == "blocked" and time.monotonic() - began < 5
        assert answer["reason"] in ("lock_held_without_identity", "startup_unverified")
        again = rig.script("ensure_async_tasks.sh")
        assert again.returncode == 20 and rig.answer(again)["launched"] is False, "it launched against an uncertain owner"
        assert rig.identity() is None or rig.supervisor_pid() is None
    finally:
        holder.close()


def test_a_start_that_fails_is_1_and_the_next_tick_tries_again(tmp_path, monkeypatch):
    runtime = tmp_path / "sun" / "runtime"
    runtime.mkdir(parents=True)
    claim_test_owner(runtime, tmp_path, monkeypatch=monkeypatch)       # an owner, but the state is not migrated
    env = {**os.environ, "SOLAR_RUNTIME_ROOT": str(runtime), "SOLAR_WORKSPACE": str(tmp_path)}
    script = str(lib.HERE / "ensure_async_tasks.sh")
    try:
        for _ in range(2):
            began = time.monotonic()
            out = subprocess.run(["bash", script], env=env, capture_output=True, text=True, timeout=30, cwd=tmp_path)
            answer = json.loads(out.stdout.strip().splitlines()[-1])
            assert out.returncode == 1 and answer["state"] == "failed" and answer["reason"] == "state_unavailable"
            assert time.monotonic() - began < 5 and answer["launched"] is True
    finally:
        ctx = lib.Context(runtime)
        for path in (ctx.identity_file, ctx.candidate_file):
            data = lib.read_json(path)
            if data and lib.matches(data.get("pid"), data.get("started"))[0] == "alive":
                os.kill(data["pid"], signal.SIGKILL)


def test_an_override_of_the_task_root_does_not_move_the_supervisor_lock(rig, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    out = rig.script("ensure_async_tasks.sh", extra_env={"SOLAR_TASK_ROOT": str(elsewhere),
                                                          "SOLAR_TASK_WORKER_LOCK": str(tmp_path / "w.lock")})
    assert out.returncode == 0, out.stdout
    assert rig.ctx.lock_file.exists() and not elsewhere.exists(), "the lock followed an override"
    again = rig.script("ensure_async_tasks.sh", extra_env={"SOLAR_TASK_ROOT": str(elsewhere)})
    assert again.returncode == 0 and rig.answer(again)["launched"] is False


def test_a_queue_signal_fills_a_free_place_without_waiting_for_the_poll(rig):
    # a supervisor that polls only every 30 s: only the signal can make it notice a new task quickly
    code = ("import sys; sys.path.insert(0, %r); import supervisor, supervisor_lib as lib; "
            "raise SystemExit(supervisor.Supervisor(lib.Context(), poll=30, sweep=30).run())" % str(lib.HERE))
    proc = subprocess.Popen([sys.executable, "-c", code], env=rig.env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        wait_until(lambda: rig.identity() and rig.identity()["reconciled"], 30, what="the supervisor")
        marker = rig.tmp / "signal.log"
        task = rig.local("Signalled", _mark(rig, "true", marker), timeout=60)
        time.sleep(1.0)
        assert rig.status(task) == "queued", "it noticed the task without a signal or a poll"
        poked = rig.script("check_async_tasks.sh")           # observing never signals
        assert poked.returncode == 0 and rig.status(task) == "queued"
        out = subprocess.run([sys.executable, str(lib.HERE / "supervisor_lib.py"), "poke"], env=rig.env,
                             capture_output=True, text=True, timeout=20)
        assert out.returncode == 0 and json.loads(out.stdout)["poked"] is True
        wait_until(lambda: rig.status(task) == "completed", 20, what="the signalled task to run")
        assert subprocess.run([sys.executable, str(lib.HERE / "supervisor_lib.py"), "poke"], env={**rig.env, "SOLAR_RUNTIME_ROOT": str(rig.tmp / "other")},
                              capture_output=True, text=True, timeout=20).returncode == 1
    finally:
        proc.kill()
        proc.wait()


def test_a_maintenance_barrier_blocks_ensure_and_check_without_launching(rig):
    (rig.runtime / "maintenance.json").write_text(json.dumps(dict(operation="update", phase="drain")))
    for name in ("ensure_async_tasks.sh", "check_async_tasks.sh"):
        out = rig.script(name)
        assert out.returncode == 20 and rig.answer(out)["reason"] == "maintenance", name
    assert not rig.ctx.candidate_file.exists() and not rig.ctx.identity_file.exists()


def test_a_stale_heartbeat_with_a_live_process_blocks_and_is_not_replaced(rig):
    pid = _ready(rig)["identity"]["pid"]
    os.kill(pid, signal.SIGSTOP)                          # alive, but it stopped beating
    try:
        time.sleep(1.5)
        out = rig.script("ensure_async_tasks.sh", extra_env={"SOLAR_SUPERVISOR_HEARTBEAT_STALE": "2"})
        time.sleep(1.0)
        out = rig.script("ensure_async_tasks.sh", extra_env={"SOLAR_SUPERVISOR_HEARTBEAT_STALE": "2"})
        answer = rig.answer(out)
        assert out.returncode == 20 and answer["reason"] == "stale_heartbeat" and answer["launched"] is False
        assert alive(pid)
    finally:
        os.kill(pid, signal.SIGCONT)
    wait_until(lambda: rig.script("check_async_tasks.sh").returncode == 0, 20, what="the beat to resume")


@pytest.mark.parametrize("field", ["workspace_id", "install_root", "runtime"])
def test_a_live_supervisor_of_another_workspace_install_or_runtime_is_never_taken_for_ours(rig, field):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        now = time.time()
        expected = rig.ctx.expected()
        document = dict(expected, schema=1, state="ready", reconciled=True, pid=other.pid,
                        started=lib.process_start(other.pid), started_epoch=now, heartbeat_epoch=now,
                        children=[], blocked=[])
        document[field] = "somebody-else"
        lib.write_json_atomic(rig.ctx.identity_file, document)
        out = rig.script("ensure_async_tasks.sh")
        answer = rig.answer(out)
        assert out.returncode == 20 and answer["reason"] == "identity_mismatch" and answer["launched"] is False
        assert alive(other.pid) and not rig.ctx.candidate_file.exists()
    finally:
        other.kill()
        other.wait()


# ---------------------------------------------------------------------------
# death, orphans and recovery
# ---------------------------------------------------------------------------

def test_a_supervisor_that_dies_is_replaced_by_the_next_tick_and_nothing_runs_twice(rig):
    marker = rig.tmp / "work.log"
    rel = _mark(rig, "sleep 3", marker)
    one = rig.local("Task one", rel, timeout=60)
    two = rig.local("Task two", rel, timeout=60)
    first = _ready(rig)["identity"]["pid"]
    wait_until(lambda: "start Task one" in _lines(marker), 30)
    os.kill(first, signal.SIGKILL)                        # the supervisor dies; its executor lives on
    wait_until(lambda: not alive(first), 10)
    out = rig.script("ensure_async_tasks.sh")
    assert out.returncode == 0 and rig.answer(out)["identity"]["pid"] != first
    wait_until(lambda: rig.status(one) == "completed" and rig.status(two) == "completed", 60, what="both tasks")
    assert _lines(marker).count("start Task one") == 1, "the running task was dispatched a second time"
    assert _lines(marker) == ["start Task one", "end Task one", "start Task two", "end Task two"]


def test_an_execution_lost_with_its_supervisor_is_failed_not_run_again(rig):
    marker = rig.tmp / "lost.log"
    rel = _mark(rig, "sleep 30", marker)
    lost = rig.local("Lost one", rel, timeout=60)
    after = rig.local("Zz after", rel, timeout=60)
    first = _ready(rig)["identity"]["pid"]
    wait_until(lambda: "start Lost one" in _lines(marker), 30)
    children = lib.read_json(rig.ctx.children_file)["executions"]
    group = children[0]["pgid"]
    os.kill(first, signal.SIGKILL)
    os.killpg(group, signal.SIGKILL)                      # the whole execution goes with it
    wait_until(lambda: not alive(first) and not alive(group), 10)
    out = rig.script("ensure_async_tasks.sh")
    assert out.returncode in (0, 10), out.stdout
    wait_until(lambda: rig.status(lost) == "error", 40, what="the lost execution to be reported")
    wait_until(lambda: rig.status(after) == "completed", 60, what="the next task to run")
    assert _lines(marker).count("start Lost one") == 1
    with solar_state.session() as store:
        assert "executor_lost" in store.task_get(lost)["body"]


# ---------------------------------------------------------------------------
# drain
# ---------------------------------------------------------------------------

def test_a_drain_waits_for_the_running_execution_and_leaves_the_lock_in_place(rig):
    marker = rig.tmp / "drain.log"
    rel = _mark(rig, "sleep 3", marker)
    running = rig.local("Running", rel, timeout=60)
    queued = rig.local("Zz queued", rel, timeout=60)
    pid = _ready(rig)["identity"]["pid"]
    wait_until(lambda: "start Running" in _lines(marker), 30)
    stop = rig.script("stop_supervisor.sh", "--drain", "--timeout", "60")
    assert stop.returncode == 0, stop.stdout + stop.stderr
    assert rig.status(running) == "completed", "the running execution was cut short"
    assert rig.status(queued) == "queued" and "start Zz queued" not in _lines(marker)
    assert not alive(pid) and rig.ctx.lock_file.exists(), "the lock must stay; only its owner leaves"
    after = rig.script("check_async_tasks.sh")
    assert after.returncode == 1 and rig.answer(after)["state"] == "absent"
    again = rig.script("stop_supervisor.sh", "--drain", "--timeout", "5")
    assert again.returncode == 0 and rig.answer(again)["reason"] == "not_running"
    nxt = rig.script("ensure_async_tasks.sh")                    # the next tick brings a new one, which finishes the queue
    assert nxt.returncode == 0
    wait_until(lambda: rig.status(queued) == "completed", 60)


def test_a_drain_that_times_out_reports_what_is_pending_and_kills_nothing(rig):
    marker = rig.tmp / "timeout.log"
    rel = _mark(rig, "sleep 5", marker)
    running = rig.local("Long", rel, timeout=60)
    pid = _ready(rig)["identity"]["pid"]
    wait_until(lambda: "start Long" in _lines(marker), 30)
    stop = rig.script("stop_supervisor.sh", "--drain", "--timeout", "1")
    answer = rig.answer(stop)
    assert stop.returncode == 1 and answer["state"] == "draining" and answer["children"]
    assert alive(pid) and rig.status(running) == "active"
    wait_until(lambda: rig.status(running) == "completed", 60)
    wait_until(lambda: not alive(pid), 30, what="the drained supervisor to leave")
    assert rig.ctx.lock_file.exists()


def test_a_drain_refuses_when_the_owner_cannot_be_identified(rig, tmp_path):
    pid = _ready(rig)["identity"]["pid"]
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "ps").write_text("#!/bin/sh\necho 'ps: denied' >&2\nexit 2\n")
    (shim / "ps").chmod(0o755)
    stop = rig.script("stop_supervisor.sh", "--drain", "--timeout", "3",
                      extra_env={"PATH": f"{shim}:{os.environ['PATH']}"})
    assert stop.returncode == 2 and rig.answer(stop)["reason"] == "owner_unverifiable"
    assert alive(pid) and rig.ctx.lock_file.exists()


def test_stop_without_the_drain_flag_is_refused(rig):
    assert rig.script("stop_supervisor.sh").returncode != 0


# ---------------------------------------------------------------------------
# the cut from the one-shot worker (machine lock) to the supervisor
# ---------------------------------------------------------------------------

def test_a_running_one_shot_worker_is_waited_for_and_its_guard_is_left_alone(rig):
    marker = rig.tmp / "cut.log"
    rel = _mark(rig, "true", marker)
    task = rig.local("Once only", rel, timeout=60)
    guard = rig.tmp / "worker.lock"
    # the previous design: a worker whose pid is in the machine guard (simulated by a process that
    # carries the worker's name on its command line)
    old = subprocess.Popen(["bash", "-c", "sleep 30; : run_worker.sh --once"], start_new_session=True)
    guard.write_text(str(old.pid))
    env = dict(SOLAR_TASK_WORKER_LOCK=str(guard), SOLAR_SUPERVISOR_LEGACY_LIMIT="60")
    try:
        for _ in range(2):
            out = rig.script("ensure_async_tasks.sh", extra_env=env)
            answer = rig.answer(out)
            assert out.returncode == 10 and answer["reason"] == "legacy_worker_draining", out.stdout
            assert answer["identity"]["kind"] == "legacy_worker" and answer["launched"] is False
        assert rig.identity() is None and _lines(marker) == [], "the new supervisor started beside the old worker"
        assert guard.read_text() == str(old.pid), "the old worker's guard was touched"
        limit = rig.script("ensure_async_tasks.sh", extra_env={**env, "SOLAR_SUPERVISOR_LEGACY_LIMIT": "1"})
        time.sleep(1.2)
        limit = rig.script("ensure_async_tasks.sh", extra_env={**env, "SOLAR_SUPERVISOR_LEGACY_LIMIT": "1"})
        assert limit.returncode == 20 and rig.answer(limit)["reason"] == "legacy_worker_running"
    finally:
        os.killpg(old.pid, signal.SIGKILL)
        old.wait()
    out = rig.script("ensure_async_tasks.sh", extra_env=env)           # the worker is gone: the supervisor takes over
    assert out.returncode == 0, out.stdout
    wait_until(lambda: rig.status(task) == "completed", 60)
    assert _lines(marker) == ["start Once only", "end Once only"], "dispatched more than once across the cut"
    assert guard.read_text() == str(old.pid), "a guard that belongs to another process was deleted"


def test_the_one_shot_worker_is_no_longer_an_entry_point(rig):
    out = rig.script("run_worker.sh", "--once")
    assert out.returncode == 64 and "no longer a production entry point" in out.stderr
    assert rig.script("run_worker.sh").returncode == 64


# ---------------------------------------------------------------------------
# the update's drain adapter against the real supervisor
# ---------------------------------------------------------------------------

def _drain_through_the_client(rig, timeout: int):
    """Run `solar_client_drain_async` exactly as an update does, on a process table the test keeps
    fresh from `ps` (the real services of the machine are never looked at)."""
    install = lib.HERE.parents[3]
    table = rig.tmp / "ps.txt"
    stop = threading.Event()

    def refresh():
        while not stop.is_set():
            listing = subprocess.run(["ps", "-ww", "-axo", "pid=,command="], capture_output=True, text=True).stdout
            tmp = table.with_suffix(".new")
            tmp.write_text(listing)
            os.replace(tmp, table)
            time.sleep(0.1)

    refresher = threading.Thread(target=refresh, daemon=True)
    refresher.start()
    wait_until(table.exists, 5)
    events = rig.tmp / "update-events.jsonl"
    env = {**rig.env, "SOLAR_CLIENT_PS_OUTPUT_FILE": str(table), "SOLAR_CLIENT_UPDATE_EVENTS_FILE": str(events),
           "SOLAR_CLIENT_DRAIN_POLL": "0.2"}
    env.pop("SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE")       # the simulated process table decides, not "none"
    try:
        done = subprocess.run(
            ["bash", "-c", f'source "{install}/core/skills/solar-client/scripts/client_lib.sh"; '
                           f'solar_client_drain_async "{install}" {timeout}'],
            env=env, capture_output=True, text=True, timeout=timeout + 60, cwd=rig.workspace)
    finally:
        stop.set()
        refresher.join()
    rows = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
    return done, [r["event"] for r in rows]


def test_the_update_drain_waits_for_the_real_supervisor_and_its_executions(rig):
    marker = rig.tmp / "update.log"
    rel = _mark(rig, "sleep 3", marker)
    task = rig.local("In flight", rel, timeout=60)
    pid = _ready(rig)["identity"]["pid"]
    wait_until(lambda: "start In flight" in _lines(marker), 30)
    done, names = _drain_through_the_client(rig, 90)
    assert done.returncode == 0, done.stdout + done.stderr
    assert names == ["drain-start", "drain-done"]
    assert rig.status(task) == "completed" and not alive(pid)


def test_the_update_drain_gives_up_without_killing_when_the_execution_is_too_long(rig):
    marker = rig.tmp / "update-long.log"
    rel = _mark(rig, "sleep 6", marker)
    task = rig.local("Too long", rel, timeout=60)
    pid = _ready(rig)["identity"]["pid"]
    wait_until(lambda: "start Too long" in _lines(marker), 30)
    done, names = _drain_through_the_client(rig, 1)
    assert done.returncode != 0 and "drain-timeout" in names and "did not drain" in done.stderr
    assert alive(pid) and rig.status(task) == "active", "a timed-out drain must not stop anything"
    wait_until(lambda: rig.status(task) == "completed", 60)
