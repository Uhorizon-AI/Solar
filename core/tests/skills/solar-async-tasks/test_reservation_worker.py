"""The sequential worker as the only executor: every start goes through a reservation.

start_next.sh takes the reservation and hands the executor the task and its token;
execute_active.sh runs exactly that claim, or takes over an execution nobody runs. A stale
token, a held execution and a maintenance barrier stop a run before it starts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dead_process import dead_pid
from reservation_tokens import token_of

CORE_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = CORE_ROOT / "skills" / "solar-async-tasks" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(CORE_ROOT / "skills" / "solar-state" / "scripts"))

import solar_state  # noqa: E402
from queue_mirror import env_for  # noqa: E402


def _setup(tmp_path: Path, marker_name: str = "ran"):
    script = tmp_path / "planets" / "louis" / "skills" / "sync" / "scripts" / "run.sh"
    script.parent.mkdir(parents=True)
    script.write_text(f'#!/bin/bash\necho "$$ $1" >> "{tmp_path / marker_name}"\nexit 0\n', encoding="utf-8")
    script.chmod(0o755)
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    task_root.mkdir(parents=True)
    env = env_for(task_root, {**os.environ, "SOLAR_WORKSPACE": str(tmp_path)})
    return script.relative_to(tmp_path).as_posix(), env, tmp_path / marker_name


def _local(store, title: str, rel: str, **extra) -> str:
    fields = [("title", json.dumps(title)), ("executor", "local"), ("local_command", json.dumps(f"bash {rel} {title}")),
              ("local_timeout", "30")] + list(extra.items())
    return store.task_create(fields, f"\n# {title}\n\nx\n", status="queued", task_id=title.lower())


def _sh(env, script, *args, extra_env=None):
    return subprocess.run(["bash", str(SCRIPTS / script), *args], env={**env, **(extra_env or {})},
                          capture_output=True, text=True, timeout=120)


def _runs(marker: Path) -> list[str]:
    return marker.read_text().split("\n")[:-1] if marker.is_file() else []


def test_start_next_hands_over_the_task_and_its_token(tmp_path):
    rel, env, _ = _setup(tmp_path)
    with solar_state.session() as store:
        task_id = _local(store, "One", rel)
    claim_file = tmp_path / "claim.json"
    started = _sh(env, "start_next.sh", extra_env={"SOLAR_CLAIM_FILE": str(claim_file)})
    assert started.returncode == 0 and "Started task" in started.stdout, started.stderr
    handed = json.loads(claim_file.read_text())
    with solar_state.session() as store:
        assert handed == dict(task_id=task_id, token=token_of(store, task_id))


def test_a_second_start_waits_while_the_only_place_is_taken(tmp_path):
    rel, env, _ = _setup(tmp_path)
    with solar_state.session() as store:
        _local(store, "One", rel)
        two = _local(store, "Two", rel)
    assert "Started task" in _sh(env, "start_next.sh").stdout
    waiting = _sh(env, "start_next.sh")
    assert "No tasks ready to start" in waiting.stdout and "two (exclusive_needs_idle)" in waiting.stdout
    with solar_state.session() as store:
        assert store.task_status(two) == "queued"


def test_the_worker_runs_exactly_the_claimed_task_and_frees_its_place(tmp_path):
    rel, env, marker = _setup(tmp_path)
    with solar_state.session() as store:
        one = _local(store, "One", rel)
        _local(store, "Two", rel)
    cycle = _sh(env, "run_worker.sh", "--once")
    assert cycle.returncode == 0, cycle.stdout + cycle.stderr
    assert [line.split()[1] for line in _runs(marker)] == ["One"]
    with solar_state.session() as store:
        assert store.task_status(one) == "completed" and store.reservations() == []
    assert _sh(env, "run_worker.sh", "--once").returncode == 0
    assert [line.split()[1] for line in _runs(marker)] == ["One", "Two"]


def test_a_stale_token_runs_nothing_and_changes_nothing(tmp_path):
    rel, env, marker = _setup(tmp_path)
    with solar_state.session() as store:
        task_id = _local(store, "One", rel)
    _sh(env, "start_next.sh")
    run = _sh(env, "execute_active.sh", "--task", task_id, "--token", "0" * 32)
    assert run.returncode != 0 and _runs(marker) == []
    with solar_state.session() as store:
        assert store.task_status(task_id) == "active" and store.reservation_for(task_id)["token"]


def test_a_manual_activation_is_run_by_the_worker_through_the_reservation(tmp_path):
    rel, env, marker = _setup(tmp_path)
    with solar_state.session() as store:
        task_id = _local(store, "Manual", rel)
    assert _sh(env, "activate.sh", task_id).returncode == 0
    with solar_state.session() as store:
        first = store.reservation_for(task_id)["token"]
    cycle = _sh(env, "run_worker.sh", "--once")
    assert cycle.returncode == 0, cycle.stdout + cycle.stderr
    assert [line.split()[1] for line in _runs(marker)] == ["Manual"]
    with solar_state.session() as store:
        assert store.task_status(task_id) == "completed" and first not in {r["token"] for r in store.reservations()}


def test_manual_activation_cannot_exceed_the_capacity(tmp_path):
    rel, env, _ = _setup(tmp_path)
    with solar_state.session() as store:
        _local(store, "One", rel)
        two = _local(store, "Two", rel)
    assert "Started task" in _sh(env, "start_next.sh").stdout
    refused = _sh(env, "activate.sh", two)
    assert refused.returncode != 0 and "reason=exclusive_needs_idle" in refused.stderr
    with solar_state.session() as store:
        assert store.task_status(two) == "queued"


def test_an_execution_held_by_a_live_executor_is_left_alone(tmp_path):
    rel, env, marker = _setup(tmp_path)
    with solar_state.session() as store:
        task_id = _local(store, "Busy", rel)
        claimed = store.task_claim_next("worker")
        store.reservation_attach(task_id, claimed["token"], pid=os.getpid())     # an executor owns it
    taken = _sh(env, "execute_active.sh", "--once")
    assert taken.returncode == 0 and "Not taking over" in taken.stderr and "lease_valid" in taken.stderr
    assert _runs(marker) == []
    with solar_state.session() as store:
        assert store.reservation_for(task_id)["token"] == claimed["token"]


def test_an_execution_whose_owner_is_gone_is_taken_over_once_its_lease_ended(tmp_path):
    rel, env, marker = _setup(tmp_path)
    with solar_state.session() as store:
        task_id = _local(store, "Orphan", rel)
        claimed = store.task_claim_next("worker")
        # The owner was a process that no longer exists, and its lease ran out.
        store.reservation_attach(task_id, claimed["token"], pid=dead_pid())
        store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z'")
    taken = _sh(env, "execute_active.sh", "--once")
    assert taken.returncode == 0, taken.stdout + taken.stderr
    assert [line.split()[1] for line in _runs(marker)] == ["Orphan"]
    with solar_state.session() as store:
        assert store.task_status(task_id) == "completed"


def test_a_maintenance_barrier_stops_the_worker_before_it_starts_anything(tmp_path):
    rel, env, marker = _setup(tmp_path)
    with solar_state.session() as store:
        task_id = _local(store, "One", rel)
        runtime = store.root
    (runtime / "maintenance.json").write_text(json.dumps(dict(operation="update")))
    cycle = _sh(env, "run_worker.sh", "--once")
    assert cycle.returncode == 0 and _runs(marker) == []
    with solar_state.session() as store:
        assert store.task_status(task_id) == "queued" and store.reservations() == []
    (runtime / "maintenance.json").unlink()
    assert _sh(env, "run_worker.sh", "--once").returncode == 0
    assert len(_runs(marker)) == 1


def test_the_executor_records_its_process_and_keeps_the_lease(tmp_path):
    rel, env, _ = _setup(tmp_path)
    slow = tmp_path / "planets" / "louis" / "skills" / "sync" / "scripts" / "slow.sh"
    slow.write_text("#!/bin/bash\nsleep 2\n", encoding="utf-8")
    slow.chmod(0o755)
    with solar_state.session() as store:
        task_id = store.task_create(
            [("title", '"Slow"'), ("executor", "local"), ("local_command", '"bash planets/louis/skills/sync/scripts/slow.sh"')],
            "\n# Slow\n\nx\n", status="queued", task_id="slow")
    proc = subprocess.Popen(["bash", str(SCRIPTS / "run_worker.sh"), "--once"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 30
    seen = None
    while time.time() < deadline and seen is None:
        with solar_state.session() as store:
            row = store.reservation_for(task_id)
            if row and row.get("owner_pid"):
                seen = row
        time.sleep(0.1)
    proc.communicate(timeout=60)
    assert seen and seen["owner_pid"] and seen["handoff"] == 0 and seen["owner_started"]
    with solar_state.session() as store:
        assert store.task_status(task_id) == "completed"


def test_ensure_does_not_start_a_worker_during_maintenance(tmp_path):
    rel, env, marker = _setup(tmp_path)
    with solar_state.session() as store:
        _local(store, "One", rel)
        runtime = store.root
    env = {**env, "SOLAR_TASK_WORKER_LOCK": str(tmp_path / "worker.lock")}
    (runtime / "maintenance.json").write_text(json.dumps(dict(operation="update")))
    held = _sh(env, "ensure_async_tasks.sh")
    assert held.returncode == 0 and "Maintenance in progress" in held.stdout and _runs(marker) == []
    (runtime / "maintenance.json").unlink()
    free = _sh(env, "ensure_async_tasks.sh")
    assert free.returncode == 0 and len(_runs(marker)) == 1


def test_a_refused_activation_gives_back_the_resources_its_hooks_took(tmp_path):
    rel, env, _ = _setup(tmp_path)
    installed = _sh(env, "install_hooks.sh", "demo")
    assert installed.returncode == 0, installed.stderr
    with solar_state.session() as store:
        _local(store, "Holder", rel)
        wanted = _local(store, "Wanted", rel, cleanup_required="true", resources=json.dumps("demo"))
    assert "Started task" in _sh(env, "start_next.sh").stdout          # Holder takes the only place
    lock = Path(env["SOLAR_TASK_ROOT"]) / ".locks" / "demo.lock"
    refused = _sh(env, "activate.sh", wanted)
    assert refused.returncode != 0 and "reason=exclusive_needs_idle" in refused.stderr
    assert not lock.exists(), "the pre_start lock must not outlive a refused activation"
    with solar_state.session() as store:
        assert store.task_status(wanted) == "queued"


def _hooks(env, name="demo", pre_start="exit 0\n"):
    """Hooks written by the test: pre_start runs the given body; on_error leaves a mark."""
    folder = Path(env["SOLAR_TASK_ROOT"]) / "hooks" / name
    folder.mkdir(parents=True)
    mark = folder / "on_error_ran"
    for hook, body in (("pre_start.sh", pre_start), ("on_error.sh", f'echo "$1" >> "{mark}"\n')):
        (folder / hook).write_text("#!/bin/bash\n" + body, encoding="utf-8")
        (folder / hook).chmod(0o755)
    return mark


def test_a_refusal_for_capacity_releases_what_this_attempt_took(tmp_path):
    rel, env, _ = _setup(tmp_path)
    mark = _hooks(env)
    with solar_state.session() as store:
        _local(store, "Holder", rel)
        wanted = _local(store, "Wanted", rel, cleanup_required="true", resources=json.dumps("demo"))
    assert "Started task" in _sh(env, "start_next.sh").stdout
    refused = _sh(env, "activate.sh", wanted)
    assert refused.returncode != 0 and "reason=exclusive_needs_idle" in refused.stderr
    assert mark.is_file(), "the on_error hook must release what the pre_start hook took"


def test_a_task_another_executor_claimed_keeps_its_resources(tmp_path):
    """Between the hooks and the claim somebody else claimed the same task: its resources are theirs."""
    rel, env, _ = _setup(tmp_path)
    state_py = CORE_ROOT / "skills" / "solar-state" / "scripts" / "solar_state.py"
    mark = _hooks(env, pre_start=(
        'id="$(grep -m1 "^id:" "$1" | cut -d: -f2 | tr -d \' "\')"\n'
        f'python3 "{state_py}" task claim "$id" --worker someone-else >/dev/null\n'))
    with solar_state.session() as store:
        wanted = _local(store, "Wanted", rel, cleanup_required="true", resources=json.dumps("demo"))
    refused = _sh(env, "activate.sh", wanted)
    assert refused.returncode != 0 and "no longer queued" in refused.stderr
    assert not mark.exists(), "another executor owns the resources now: nothing may be released"
    with solar_state.session() as store:
        assert store.task_status(wanted) == "active" and store.reservation_for(wanted)["worker"] == "someone-else"


def _alive(pid: int) -> bool:
    done = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    state = done.stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_losing_the_execution_stops_the_provider_it_started(tmp_path):
    """The heartbeat finds the token replaced: the provider's process group goes down with the executor."""
    script = tmp_path / "planets" / "louis" / "skills" / "sync" / "scripts" / "linger.sh"
    script.parent.mkdir(parents=True)
    pids = tmp_path / "pids"
    script.write_text(f'#!/bin/bash\nsleep 120 &\necho "$$ $!" > "{pids}"\nwait\n', encoding="utf-8")
    script.chmod(0o755)
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    task_root.mkdir(parents=True)
    env = env_for(task_root, {**os.environ, "SOLAR_WORKSPACE": str(tmp_path)})
    with solar_state.session() as store:
        task_id = store.task_create(
            [("title", '"Linger"'), ("executor", "local"),
             ("local_command", json.dumps("bash planets/louis/skills/sync/scripts/linger.sh")),
             ("local_timeout", "100")], "\n# Linger\n\nx\n", status="queued", task_id="linger")
        token = store.task_claim_next("worker")["token"]
    proc = subprocess.Popen([sys.executable, str(SCRIPTS / "execute_active.py"), task_id, "/nonexistent/router.py"],
                            env={**env, "SOLAR_TASK_TOKEN": token, "SOLAR_TASK_HEARTBEAT_SECONDS": "0.3"},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and not pids.exists():
            time.sleep(0.1)
        assert pids.exists(), "the provider never started"
        time.sleep(0.2)
        leader, child = (int(x) for x in pids.read_text().split())
        assert _alive(leader) and _alive(child)
        with solar_state.session() as store:                                   # somebody took the execution over
            store.conn.execute("UPDATE execution_reservations SET token = ? WHERE task_id = ?", ("f" * 32, task_id))
        code = proc.wait(timeout=30)
        assert code == 75, proc.stdout.read() + proc.stderr.read()
        time.sleep(0.5)
        assert not _alive(leader) and not _alive(child), "the provider outlived its executor"
    finally:
        proc.kill()
        for pid in (locals().get("leader"), locals().get("child")):
            if pid:
                subprocess.run(["kill", "-9", str(pid)], capture_output=True)
    with solar_state.session() as store:
        assert store.task_status(task_id) == "active"                          # the new owner decides, not the loser
