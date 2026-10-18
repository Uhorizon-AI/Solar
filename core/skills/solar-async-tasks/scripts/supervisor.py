#!/usr/bin/env python3
"""Resident async-tasks supervisor: fills the places the applied policy allows, one executor per task.

One supervisor per runtime. It is the only process that takes `supervisor.lock` and keeps it for its
whole life. Each claim goes through the reservation of solar-state (the same one `activate.sh` and
the diagnostic worker use), so the supervisor never decides capacity itself: it asks for the next
task, and the reservation answers or refuses. A claimed task is dispatched by id and token to its own
executor (`execute_active.sh --task <id> --token <token>`) in its own session and process group;
children are collected with wait/poll, and a free place is filled as soon as one ends or a queue
signal arrives (SIGUSR1), with a poll of at most one second as the floor.

The executor marks its reservation ending when it finishes the task. The supervisor verifies that
all recorded groups are gone (and stops only verified stragglers), releases the reservation, and takes
over only what an executor left unfinished: it never re-runs a task whose outcome is uncertain, and
an owner it cannot identify stays blocked and visible.

Usage:  supervisor.py run        (what the launcher starts; not meant to be run by hand)
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import supervisor_lib as lib  # noqa: E402
import solar_state  # noqa: E402

LOCK_IDENTITY_WAIT = 2.0        # how long a candidate that lost the lock waits for the winner to show itself
HOOK_TIMEOUT = 60.0             # a pre-start hook's deadline unless the task sets cleanup_timeout
MAX_START_FAILURES = 3          # an executor that never took its execution, this many times in a row
MAX_PER_PASS = 16               # claims in one pass: the policy decides how many fit, this only bounds a pass
WAITING_SHOWN = 20


def log(message: str) -> None:
    print(f"[{lib.iso(time.time())}] supervisor[{os.getpid()}] {message}", flush=True)


def _seconds(name: str, default: float, low: float, high: float) -> float:
    return lib._env_seconds(name, default, low, high)


def group_members(pgid: int) -> Optional[list[int]]:
    """Use the same fail-closed process-table proof as reservation recovery."""
    return solar_state._group_members(pgid)


def stop_group(pgid: int, term_grace: float, kill_wait: float) -> bool:
    """End one execution's process group and prove it. True only when no live member remains.

    Only the group it is given is signalled, and never the supervisor's own or a system group."""
    if pgid is None or pgid <= 1 or pgid == os.getpgrp():
        return False
    for sig, wait in ((signal.SIGTERM, term_grace), (signal.SIGKILL, kill_wait)):
        members = group_members(pgid)
        if members is None:
            return False
        if not members:
            return True
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            return False
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            members = group_members(pgid)
            if members is None:
                return False
            if not members:
                return True
            time.sleep(0.05)
    members = group_members(pgid)
    return members == []


class Execution:
    """One dispatched (or adopted) executor and what it holds."""

    def __init__(self, task_id: str, token: str, worker: str, *, pid: Optional[int] = None,
                 started: Optional[str] = None, proc: Optional[subprocess.Popen] = None,
                 adopted: bool = False, access: Optional[dict] = None):
        self.task_id, self.token, self.worker = task_id, token, worker
        self.pid, self.started, self.proc, self.adopted = pid, started, proc, adopted
        self.pgid = pid
        self.provider_pid: Optional[int] = None    # leader of the command's own group, once the executor recorded it
        self.access = access or {}
        self.dispatched_epoch = time.time()
        self.cancel_seen: Optional[float] = None
        self.reason: Optional[str] = None          # why the supervisor itself stopped it
        self.forced = False
        self.foreign = False                       # a reservation some other process took: judged, never run here

    def record(self) -> dict:
        return {"task_id": self.task_id, "token": self.token, "worker": self.worker, "pid": self.pid,
                "pgid": self.pgid, "provider_pid": self.provider_pid, "started": self.started,
                "dispatched_epoch": self.dispatched_epoch, "access": self.access}

    def groups(self) -> list[int]:
        """Every process group of this execution that must be gone before it counts as over."""
        return [g for g in (self.pgid, self.provider_pid) if g]

    def view(self) -> dict:
        return {"task_id": self.task_id, "pid": self.pid, "pgid": self.pgid, "adopted": self.adopted,
                "since": lib.iso(self.dispatched_epoch), "provider": self.access.get("provider")}


def default_executor(task_id: str, token: str) -> list[str]:
    return ["bash", str(HERE / "execute_active.sh"), "--task", task_id, "--token", token]


class Supervisor:
    def __init__(self, ctx: lib.Context, *, executor: Callable[[str, str], list[str]] = default_executor,
                 poll: Optional[float] = None, tick: float = 0.1, sweep: Optional[float] = None,
                 heartbeat: float = 1.0, term_grace: Optional[float] = None,
                 kill_wait: Optional[float] = None, cancel_grace: Optional[float] = None,
                 cooldown: Optional[float] = None, install_signals: bool = True):
        self.ctx = ctx
        self.executor = executor
        self.poll = poll if poll is not None else _seconds("SOLAR_SUPERVISOR_POLL", 1.0, 0.05, 1.0)
        self.tick = tick
        self.sweep_every = sweep if sweep is not None else _seconds("SOLAR_SUPERVISOR_SWEEP", 5.0, 0.2, 60.0)
        self.heartbeat_every = heartbeat
        self.term_grace = term_grace if term_grace is not None else _seconds("SOLAR_SUPERVISOR_TERM_GRACE", 5.0, 0.1, 60.0)
        self.kill_wait = kill_wait if kill_wait is not None else _seconds("SOLAR_SUPERVISOR_KILL_WAIT", 5.0, 0.1, 60.0)
        self.cancel_grace = cancel_grace if cancel_grace is not None else _seconds("SOLAR_SUPERVISOR_CANCEL_GRACE", 15.0, 0.1, 600.0)
        self.cooldown_seconds = cooldown if cooldown is not None else _seconds("SOLAR_SUPERVISOR_COOLDOWN", 30.0, 0.1, 600.0)
        self.install_signals = install_signals
        self.worker = f"supervisor-{os.getpid()}"
        self.children: dict[str, Execution] = {}
        self.blocked: dict[str, dict] = {}
        self.start_failures: dict[str, int] = {}
        self.cooldown: dict[str, float] = {}
        self.waiting: list[dict] = []
        self.dispatch_log: list[tuple[str, float]] = []   # (task id, epoch): when each executor was started
        self.capacity_view: dict = {}
        self.wake = threading.Event()
        self.stop_event = threading.Event()        # lets an in-process owner end the loop
        self.draining = False
        self.drain_request: Optional[dict] = None
        self.state = "starting"
        self.reconciled = False
        self.reconciled_at: Optional[float] = None
        self.started_epoch = time.time()
        self.started: Optional[str] = None
        self._lock_handle = None
        self._control_mtime: Optional[float] = None
        self.state_errors = 0
        self._next_enforce = 0.0
        self._next_adopted_check = 0.0
        # The holds the previous supervisor left, kept in every write until the start-up reconciliation
        # has decided about them: a write in between must never publish a state without them.
        self._carried_holds: Optional[list[dict]] = None

    # -- lock and identity ----------------------------------------------------------

    def acquire(self) -> bool:
        self.ctx.locks.mkdir(parents=True, exist_ok=True)
        self.ctx.support.mkdir(parents=True, exist_ok=True)
        handle = open(self.ctx.lock_file, "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                return False
            raise
        self._lock_handle = handle
        self.started = lib.process_start(os.getpid())
        self.started_epoch = time.time()
        expected = self.ctx.expected() or {}
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "started": self.started, "runtime": str(self.ctx.runtime),
                                 "workspace_id": expected.get("workspace_id")}) + "\n")
        handle.flush()
        return True

    def _lost_the_lock(self) -> int:
        """Another process holds the lock. Normally that is a supervisor that just won it: its
        identity appears within moments and this candidate leaves quietly. A lock held with no
        identity ever showing is an owner that cannot be identified: it is recorded, so the ticks
        report it as blocked (and do not keep launching candidates against it)."""
        expected = self.ctx.expected() or {}
        deadline = time.monotonic() + LOCK_IDENTITY_WAIT
        while time.monotonic() < deadline:
            recorded = lib.read_json(self.ctx.identity_file)
            if isinstance(recorded, dict) and recorded.get("pid") not in (None, os.getpid()):
                kind, _ = lib.matches(recorded["pid"], recorded.get("started"))
                if kind == "alive" and not lib.identity_mismatch(recorded, expected):
                    log("another supervisor owns this runtime: exiting without dispatching")
                    return 2
            time.sleep(0.05)
        log("the supervisor lock is held by a process that shows no identity: not replacing it")
        self.started = lib.process_start(os.getpid())
        self._exit_record("lock_held_without_identity",
                          "the lock is held but no live supervisor identity is published")
        return 2

    def release(self) -> None:
        if self._lock_handle is not None:
            self._lock_handle.close()          # closing releases the flock; the file stays
            self._lock_handle = None

    def _document(self) -> dict:
        expected = self.ctx.expected() or {}
        now = time.time()
        return {
            "schema": lib.SCHEMA, "state": self.state, "pid": os.getpid(), "started": self.started,
            "started_epoch": self.started_epoch, "started_at": lib.iso(self.started_epoch),
            "runtime": str(self.ctx.runtime), "workspace_id": expected.get("workspace_id"),
            "workspace": expected.get("workspace"), "install_root": self.ctx.install_root,
            "heartbeat_epoch": now, "heartbeat_at": lib.iso(now), "reconciled": self.reconciled,
            "reconciled_at": lib.iso(self.reconciled_at) if self.reconciled_at else None,
            "draining": self.drain_request, "capacity": dict(self.capacity_view, running=len(self.children)),
            "children": [c.view() for c in self.children.values()],
            "blocked": list(self.blocked.values()), "waiting": self.waiting[:WAITING_SHOWN],
        }

    def publish(self, durable: bool = False) -> None:
        try:
            lib.write_json_atomic(self.ctx.identity_file, self._document(), durable=durable)
        except OSError as exc:
            log(f"cannot publish the identity: {exc}")

    def _exit_record(self, reason: str, detail: str = "") -> None:
        try:
            lib.write_json_atomic(self.ctx.exit_file, {
                "pid": os.getpid(), "started": self.started, "reason": reason, "detail": detail,
                "at": lib.iso(time.time())})
        except OSError:
            pass

    # -- records of what was dispatched (for a later incarnation) --------------------

    def _save_records(self) -> None:
        try:
            lib.write_json_atomic(self.ctx.children_file, {
                "version": 1, "executions": [c.record() for c in self.children.values()]}, mode=0o600)
            lib.write_json_atomic(self.ctx.blocked_file, {"version": 1, "blocked": list(self.blocked.values())},
                                  mode=0o600)
            # Claims read these exclusions in the same database as reservations. A running or ending
            # reservation counts once; a hold without a reservation counts independently until all
            # groups are proved gone. A failed or unverified cleanup retains its exclusion.
            holds = [{"task_id": c.task_id, "while_reserved": True, "pgids": c.groups(),
                      **(c.access or {})} for c in self.children.values()]
            holds += [{"task_id": e["task_id"], "reason": e.get("reason"), "since": e.get("since"),
                       "pgids": e.get("pgids") or ([e["pgid"]] if e.get("pgid") else []),
                       **(e.get("access") or {})}
                      for e in self.blocked.values() if e.get("released")]
            if self._carried_holds:
                covered = {h.get("task_id") for h in holds}
                holds += [h for h in self._carried_holds if h.get("task_id") not in covered]
            solar_state.cleanup_holds_write(self.ctx.runtime, holds)
        except OSError as exc:
            log(f"cannot record the executions: {exc}")

    def _load_records(self) -> dict[str, dict]:
        data = lib.read_json(self.ctx.children_file)
        recs = {}
        if isinstance(data, dict):
            for item in data.get("executions") or []:
                if isinstance(item, dict) and item.get("task_id") and item.get("token"):
                    recs[item["task_id"]] = item
        return recs

    def _load_blocked(self) -> None:
        data = lib.read_json(self.ctx.blocked_file)
        if isinstance(data, dict):
            for item in data.get("blocked") or []:
                if isinstance(item, dict) and item.get("task_id"):
                    self.blocked[item["task_id"]] = item

    # -- state access ----------------------------------------------------------------

    def _session(self):
        return solar_state.session(self.ctx.runtime)

    def _maintenance(self) -> bool:
        return solar_state.maintenance_state(self.ctx.runtime) is not None

    # -- start -------------------------------------------------------------------------

    def start(self) -> int:
        """Lock, identity, schema check, reconciliation. 0 ready; 1 the candidate must exit."""
        if not self.acquire():
            return self._lost_the_lock()
        self.publish(durable=True)
        try:
            with self._session() as store:
                policy = store.async_policy()
            self.capacity_view = self._capacity_from(policy)
        except (solar_state.StateError, OSError) as exc:
            log(f"the state is not ready: {exc}")
            self._exit_record("state_unavailable", str(exc))
            return 1
        self._load_blocked()
        previous = solar_state.cleanup_holds(self.ctx.runtime)
        self._carried_holds = previous
        try:
            try:
                self._sweep(startup=True)
            except solar_state.StateError as exc:
                log(f"reconciliation could not finish: {exc}")
                self._exit_record("reconciliation_failed", str(exc))
                return 1
            self._recover_holds(previous)
        finally:
            # Only now, with the sweep done and the holds judged, are they replaced together.
            self._carried_holds = None
        self.reconciled, self.reconciled_at, self.state = True, time.time(), "ready"
        self._save_records()
        self.publish(durable=True)
        log(f"ready: workspace {(self.ctx.expected() or {}).get('workspace_id')}, runtime {self.ctx.runtime}, "
            f"{len(self.children)} execution(s) adopted, {len(self.blocked)} blocked")
        return 0

    def _recover_holds(self, previous: list[dict]) -> None:
        """An execution that was running when the previous supervisor went away and is neither adopted
        nor blocked now has finished (or is finishing) with nobody to prove its groups gone. Its
        groups are the executor's and the command's: the command's leader is read again from the task
        when the hold did not carry it. A hold whose groups are all empty is dropped; one with any
        member left, or that cannot be checked, stays as an unverified cleanup (the claim exclusion
        is kept) until every group is empty."""
        for hold in previous:
            task_id = hold.get("task_id")
            if hold.get("unreadable"):
                self.blocked[task_id] = dict(task_id=task_id, reason="cleanup_unverified",
                    detail="legacy cleanup exclusions were unreadable; operator recovery required",
                    since=lib.iso(time.time()), pgids=[], released=True, ours=False,
                    access=dict(access_class="exclusive"))
                continue
            if not task_id or task_id in self.children or task_id in self.blocked:
                continue
            groups = [g for g in hold.get("pgids") or [] if g]
            try:
                with self._session() as store:
                    pid = (store.task_get(task_id) or {}).get("pid")
                if self._recorded_provider_pid(pid, hold.get("prior_pid")) and int(pid) not in groups:
                    groups.append(int(pid))
            except (solar_state.StateError, OSError) as exc:
                log(f"{task_id}: could not re-read the command's group from the task ({exc}); "
                    "keeping the groups the hold recorded")
            if groups and all(group_members(g) == [] for g in groups):
                log(f"{task_id}: its groups were already gone when the previous supervisor's hold was read")
                continue
            self.blocked[task_id] = {
                "task_id": task_id, "reason": "cleanup_unverified", "since": lib.iso(time.time()),
                "detail": "the supervisor that ran it went away before its process groups were proved gone",
                "pgids": groups, "pid": None, "pgid": None, "token": None, "worker": None,
                "released": True, "ours": True,
                "access": {k: hold.get(k) for k in ("provider", "access_class", "resources", "scopes")}}
            log(f"BLOCKED {task_id}: cleanup_unverified: groups {groups} are not proved gone")

    @staticmethod
    def _recorded_provider_pid(pid, prior) -> Optional[int]:
        """The pid the executor recorded for the command of THIS execution (not one an earlier run left)."""
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return None
        if pid <= 1 or pid == prior or pid == os.getpgrp():
            return None
        return pid

    # -- main loop ---------------------------------------------------------------------

    def run(self) -> int:
        code = self.start()
        if code != 0:
            self.release()
            return 0 if code == 2 else code
        if self.install_signals and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, lambda *_: self._request_drain("signal"))
            signal.signal(signal.SIGINT, lambda *_: self._request_drain("signal"))
            signal.signal(signal.SIGUSR1, lambda *_: self.wake.set())
        next_fill = next_sweep = next_beat = 0.0
        try:
            while not self.stop_event.is_set():
                self._check_control()
                self._guarded(self._reap)
                now = time.monotonic()
                if now >= self._next_enforce:
                    self._guarded(self._enforce)
                    self._next_enforce = now + 1.0
                if self.draining and not self.children:
                    break
                if not self.draining:
                    if (self.wake.is_set() or now >= next_fill) and not self._maintenance():
                        self.wake.clear()
                        self._guarded(self._fill)
                        next_fill = time.monotonic() + self.poll
                    if now >= next_sweep:
                        self._guarded(self._sweep)
                        next_sweep = time.monotonic() + self.sweep_every
                if now >= next_beat:
                    self.publish()
                    next_beat = time.monotonic() + self.heartbeat_every
                self.wake.wait(self.tick)
                if self.wake.is_set() and not self.draining:
                    next_fill = 0.0
        finally:
            self.state = "stopped" if (self.draining or self.stop_event.is_set()) else "crashed"
            self._save_records()
            self.publish(durable=True)
        pending = len(self.blocked)
        self._exit_record("drained", f"{pending} blocked execution(s) remain" if pending else "")
        log(f"drained: nothing running, {pending} blocked execution(s) left for attention")
        self.release()
        return 0

    def _guarded(self, action: Callable[[], Any]) -> None:
        try:
            action()
            self.state_errors = 0
        except (solar_state.StateError, OSError) as exc:
            self.state_errors += 1
            if self.state_errors in (1, 10, 100) or self.state_errors % 600 == 0:
                log(f"state not available ({self.state_errors}): {exc}")

    def _request_drain(self, by: str) -> None:
        if not self.draining:
            self.draining = True
            self.state = "draining"
            self.drain_request = {"by": by, "at": lib.iso(time.time())}
            log(f"drain requested by {by}: no new dispatch, {len(self.children)} execution(s) to collect")
            self.publish(durable=True)
        self.wake.set()

    def _check_control(self) -> None:
        try:
            mtime = self.ctx.control_file.stat().st_mtime
        except OSError:
            return
        if mtime == self._control_mtime:
            return
        self._control_mtime = mtime
        data = lib.read_json(self.ctx.control_file)
        if (isinstance(data, dict) and data.get("request") == "drain"
                and data.get("target_pid") == os.getpid() and data.get("target_started") == self.started):
            self._request_drain(str(data.get("requested_by") or "control"))

    # -- claiming and dispatching ------------------------------------------------------

    @staticmethod
    def _capacity_from(policy: dict) -> dict:
        return {"revision": policy["revision"], "global": policy["global_capacity"],
                "provider": policy["provider_capacity"]}

    def _exclude(self) -> list[str]:
        now = time.monotonic()
        # An execution still being collected is not claimed again (a recurring task is queued again
        # the moment its executor finishes it, a few milliseconds before the process is gone).
        excluded = [tid for tid, until in list(self.cooldown.items()) if until > now] + list(self.children)
        for tid in [t for t, until in self.cooldown.items() if until <= now]:
            del self.cooldown[tid]
        return excluded

    def _fill(self) -> None:
        for _ in range(MAX_PER_PASS):
            if self.draining or self.stop_event.is_set():
                return
            with self._session() as store:
                policy = store.async_policy()
                self.capacity_view = self._capacity_from(policy)
                detail = store.task_claim_next_detail(self.worker, exclude=self._exclude())
                task, token = detail["task"], detail["token"]
                self.waiting = [w for w in detail["waiting"] if w.get("id")][:WAITING_SHOWN]
                if task is None:
                    return
                access = self._access_of(store, task["id"])
            if not self._post_claim(task, token):
                continue
            self._dispatch(task["id"], token, self.worker, access)

    @staticmethod
    def _access_of(store, task_id: str) -> dict:
        row = store.reservation_for(task_id) or {}
        task = store.task_get(task_id) or {}
        return {"provider": row.get("provider") or "", "access_class": row.get("access_class") or "exclusive",
                "resources": row.get("resources") or [], "scopes": row.get("scopes") or [],
                # the pid recorded by an earlier run: only a different one belongs to this execution
                "prior_pid": task.get("pid")}

    def _post_claim(self, task: dict, token: str) -> bool:
        """What `start_next.sh` does after a claim: the pre-start hooks of the task's resources (a
        hook that blocks gives the claim back), the interval stamp of a recurring task, and the
        dependency marker. False means the task went back to the queue."""
        task_id = task["id"]
        with self._session() as store:
            cleanup = (store.task_field(task_id, "cleanup_required") or "") == "true"
            resources = store.task_field(task_id, "resources") or ""
            exported = store.task_export(task_id) if cleanup else ""
            try:
                hook_timeout = float(store.task_field(task_id, "cleanup_timeout") or HOOK_TIMEOUT)
            except ValueError:
                hook_timeout = HOOK_TIMEOUT
            hook_timeout = min(max(hook_timeout, 1.0), 3600.0)      # 0 or a negative value is not "no time"
        if cleanup:
            tasks_root = Path(os.environ.get("SOLAR_TASK_ROOT") or self.ctx.tasks)
            env = {**os.environ, "HOOKS_DIR": str(tasks_root / "hooks"), "DIR_LOCKS": str(tasks_root / ".locks"),
                   "SOLAR_TASK_ROOT": str(tasks_root)}
            for resource in [r.strip() for r in resources.split(",") if r.strip()]:
                hook = tasks_root / "hooks" / resource / "pre_start.sh"
                if not (hook.is_file() and os.access(hook, os.X_OK)):
                    continue
                export_file = self.ctx.support / f".export-{task_id}"
                export_file.write_text(exported, encoding="utf-8")
                try:
                    blocked = self._run_hook(hook, export_file, env, hook_timeout)
                finally:
                    export_file.unlink(missing_ok=True)
                if blocked:
                    log(f"pre-start hook blocked {task_id} (resource busy or no answer: {resource}); given back")
                    self._give_back(task_id, token, self.worker)
                    self.cooldown[task_id] = time.monotonic() + self.cooldown_seconds
                    return False
        with self._session() as store:
            if (store.task_field(task_id, "recurring") or "") == "true":
                store.task_set(task_id, "recurring_last_run", lib.iso(time.time()))
            store.task_unset(task_id, "blocked_by_task_ids")
        return True

    def _run_hook(self, hook: Path, export_file: Path, env: dict, timeout: float) -> bool:
        """Run a pre-start hook with a deadline; True when it blocks the start. A hook that does
        not answer in time is a blocked hook (its whole group is ended), never a frozen supervisor:
        while it runs the heartbeat keeps beating and finished executions are still collected."""
        proc = subprocess.Popen([str(hook), str(export_file)], env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + timeout
        next_beat = 0.0
        while proc.poll() is None:
            now = time.monotonic()
            if now >= deadline:
                log(f"pre-start hook {hook} gave no answer in {timeout:g}s; ending it")
                stop_group(proc.pid, self.term_grace, self.kill_wait)
                proc.wait()
                return True
            if now >= next_beat:
                self.publish()
                self._guarded(self._reap)
                next_beat = now + 1.0
            time.sleep(0.05)
        return proc.returncode != 0

    def _give_back(self, task_id: str, token: str, worker: str) -> None:
        try:
            with self._session() as store:
                store.task_release(task_id, worker, token=token)
        except solar_state.StateError as exc:
            log(f"could not give {task_id} back: {exc}")

    def _dispatch(self, task_id: str, token: str, worker: str, access: dict) -> None:
        """Start the executor of exactly this claim. The record is written before the process
        starts, so a supervisor that dies in between leaves a claim its successor can account for."""
        ex = Execution(task_id, token, worker, access=access)
        self.children[task_id] = ex
        self._save_records()
        try:
            log_dir = self.ctx.runtime / "task-logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / f"{task_id}.dispatch.log", "ab") as out:
                proc = subprocess.Popen(self.executor(task_id, token), stdin=subprocess.DEVNULL, stdout=out,
                                        stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
                                        env={**os.environ, "SOLAR_SUPERVISOR_DISPATCH": "1"})
        except OSError as exc:
            log(f"could not start the executor of {task_id}: {exc}")
            del self.children[task_id]
            self._save_records()
            self._start_failure(task_id, token, worker, f"the executor could not start: {exc}")
            return
        ex.proc, ex.pid, ex.pgid = proc, proc.pid, proc.pid
        ex.started = lib.process_start(proc.pid)
        self.dispatch_log = (self.dispatch_log + [(task_id, time.time())])[-500:]
        self._save_records()
        log(f"dispatched {task_id} (pid {proc.pid})")

    # -- collecting ----------------------------------------------------------------------

    def _reap(self) -> None:
        """Collect what ended. A child of this process is polled every tick (cheap); an adopted one
        has no handle, so it is asked about in the process table at most once a second."""
        now = time.monotonic()
        ask_table = now >= self._next_adopted_check
        if ask_table:
            self._next_adopted_check = now + 1.0
        for ex in list(self.children.values()):
            if ex.proc is not None:
                if ex.proc.poll() is None:
                    continue
                code: Optional[int] = ex.proc.returncode
            else:
                if not ask_table:
                    continue
                kind, _ = lib.matches(ex.pid, ex.started)
                if kind != "gone":
                    continue
                code = None
            self._collect(ex, code)

    def _provider_group(self, ex: Execution, immediate: bool = True) -> tuple[str, Optional[int]]:
        """The process group of the command or provider this execution started (the router runs it
        in a group of its own, apart from the executor's): ('none'|'alive'|'uncertain', pid).

        The pid is the one the executor recorded for this task after it was dispatched. `alive`
        means that process still leads its own group and started after the dispatch (so it is
        this execution's). A group whose leader is gone but still has members is this execution's
        too when we look right after its executor ended (`immediate`: a group id cannot be reused
        while it has members, and the window for it to have emptied and been reused is the
        milliseconds since); otherwise, and when the process table would not answer, it is
        `uncertain`."""
        with self._session() as store:
            pid = (store.task_get(ex.task_id) or {}).get("pid")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return "none", None
        if pid <= 1 or pid == (ex.access or {}).get("prior_pid") or pid == os.getpgrp():
            return "none", None
        kind, info = lib.probe(pid)
        members = group_members(pid)
        ex.provider_pid = pid                      # remembered: it is one of the groups that must be proved gone
        if kind == "unknown" or members is None:
            return "uncertain", pid
        if kind == "alive" and pid in members and (info.get("epoch") or 0) >= ex.dispatched_epoch - 2:
            return "alive", pid
        if not members:
            return "none", None
        return ("alive", pid) if immediate else ("uncertain", pid)

    def _settle_provider_group(self, ex: Execution, immediate: bool = True) -> bool:
        """End the provider group of this execution and prove it gone. False when that cannot be
        proved (the reservation then stays and nothing unproven is signalled)."""
        state, pid = self._provider_group(ex, immediate)
        if state == "none":
            return True
        if state == "alive":
            return stop_group(pid, self.term_grace, self.kill_wait)
        return False

    def _collect(self, ex: Execution, code: Optional[int]) -> None:
        """The executor is over. Prove its group is gone, then finish what it left unfinished.
        Only after that is the place forgotten; when the proof fails the execution stays counted
        and visible as blocked."""
        if not (stop_group(ex.pgid, self.term_grace, self.kill_wait) and self._settle_provider_group(ex)):
            self._block(ex, "cleanup_failed", f"the process group of {ex.task_id} could not be proven gone",
                        released=True)
            self.children.pop(ex.task_id, None)
            self._save_records()
            return
        try:
            outcome = self._finalize(ex, code)
        except solar_state.StaleToken:
            outcome = "token_replaced"
        except solar_state.TransitionRefused:
            outcome = "already_settled"
        # Any other state error (busy, unavailable) propagates: the child stays counted and the
        # next pass settles it; nothing is forgotten while its outcome is not recorded.
        with self._session() as store:
            remaining = store.reservation_for(ex.task_id)
            if remaining and remaining.get("token") == ex.token and remaining.get("phase") == "ending":
                released = store.reservation_finish(ex.task_id, ex.token, groups=group_members)
                if not released["released"]:
                    self._block(ex, "cleanup_unverified", released["reason"], released=False)
                    self.children.pop(ex.task_id, None)
                    self._save_records()
                    return
        log(f"collected {ex.task_id}: executor exit {code}, {outcome}")
        self.children.pop(ex.task_id, None)
        if outcome != "never_started":
            self.start_failures.pop(ex.task_id, None)
        self._save_records()
        self.wake.set()

    def _finalize(self, ex: Execution, code: Optional[int]) -> str:
        """Settle unfinished task state under this execution's token. The reservation remains
        ending until collection also verifies the owner and every persisted group is gone."""
        with self._session() as store:
            status = store.task_status(ex.task_id)
            row = store.reservation_for(ex.task_id)
            if status != "active" or not row or row.get("token") != ex.token:
                return "finished_by_its_executor"
            unattached = row.get("owner_pid") is None
            if store.cancellation_requested(ex.task_id):
                store.task_complete(ex.task_id, cancelled=True, token=ex.token)
                return "cancelled"
        if unattached:
            # it never took its execution (it exited, or hung, before attaching): nothing ran
            self._start_failure(ex.task_id, ex.token, ex.worker,
                                f"the executor exited ({code}) before taking its execution")
            return "never_started"
        why = {"lease_expired": "its lease expired without a heartbeat and the supervisor stopped it",
               "cancel_forced": "the supervisor stopped it after a cancellation request"}.get(
            ex.reason or "", f"the executor exited (code {code}) without finishing the task")
        self._fail(ex.task_id, ex.token, ex.reason or "executor_exited", why)
        return ex.reason or "failed_uncertain"

    def _fail(self, task_id: str, token: str, code: str, why: str) -> None:
        suffix = ("## Execution Error\n"
                  f"- time: {lib.iso(time.time())}\n- provider_attempted: unknown\n- error_code: {code}\n"
                  f"- error: {why}; whether it had effects is uncertain, so it was not retried\n")
        with self._session() as store:
            store.task_fail(task_id, suffix, token=token)

    def _start_failure(self, task_id: str, token: str, worker: str, why: str) -> None:
        """An execution that never started: nothing ran, so the place is given back unambiguously.
        A task that keeps failing to start is failed instead of being retried for ever."""
        count = self.start_failures.get(task_id, 0) + 1
        self.start_failures[task_id] = count
        try:
            if count >= MAX_START_FAILURES:
                self._fail(task_id, token, "executor_start_failed", f"{why} ({count} times)")
                self.start_failures.pop(task_id, None)
            else:
                self._give_back(task_id, token, worker)
                self.cooldown[task_id] = time.monotonic() + self.cooldown_seconds
        except solar_state.StateError as exc:
            log(f"could not settle the failed start of {task_id}: {exc}")

    def _block(self, ex: Execution, reason: str, detail: str, *, released: bool) -> None:
        self.blocked[ex.task_id] = {
            "task_id": ex.task_id, "reason": reason, "detail": detail, "since": lib.iso(time.time()),
            "pid": ex.pid, "pgid": ex.pgid, "pgids": ex.groups(), "started": ex.started,
            "token": ex.token, "worker": ex.worker,
            "access": ex.access, "released": released, "ours": not ex.foreign}
        log(f"BLOCKED {ex.task_id}: {reason}: {detail}")

    # -- cancellation and lease timeouts -----------------------------------------------

    def _enforce(self) -> None:
        live = [c for c in self.children.values()]
        if not live:
            return
        try:
            with self._session() as store:
                cancels = set(store.cancellation_ids())
                held = {r["task_id"]: r for r in store.reservations() if r.get("token")}
                recorded = {ex.task_id: (store.task_get(ex.task_id) or {}).get("pid") for ex in live}
        except (solar_state.StateError, OSError):
            return
        # The command's own group, as soon as the executor records it, so the hold carries it from then on.
        changed = False
        for ex in live:
            pid = self._recorded_provider_pid(recorded.get(ex.task_id), (ex.access or {}).get("prior_pid"))
            if pid and pid != ex.provider_pid:
                ex.provider_pid, changed = pid, True
        if changed:
            self._save_records()
        now = time.monotonic()
        for ex in live:
            if ex.forced:
                continue
            if ex.task_id in cancels:
                ex.cancel_seen = ex.cancel_seen or now
                if now - ex.cancel_seen >= self.cancel_grace:
                    self._stop(ex, "cancel_forced")
                continue
            ex.cancel_seen = None
            row = held.get(ex.task_id)
            # attached or not: a lease that ran out while its process is alive is a timeout
            if row and row.get("token") == ex.token and self._lease_expired(row):
                self._stop(ex, "lease_expired")

    def _stop(self, ex: Execution, reason: str) -> None:
        """Stop this execution's group, and nothing else. The loop notices the exit and finishes it."""
        ex.forced, ex.reason = True, reason
        log(f"stopping the group of {ex.task_id} ({reason})")
        self._settle_provider_group(ex)                  # the command's own group first
        kind, _ = lib.matches(ex.pid, ex.started)
        if kind == "alive":
            stop_group(ex.pgid, self.term_grace, self.kill_wait)

    # -- reconciliation ----------------------------------------------------------------

    def _sweep(self, startup: bool = False) -> None:
        """Reservations nobody here accounts for, and blocked entries that may have cleared. At
        start this is the reconciliation: an owner that cannot be identified stays blocked, and a
        task whose executor is gone is failed rather than run again."""
        with self._session() as store:
            rows = [r for r in store.reservations() if r.get("token")]
            policy = store.async_policy()
        self.capacity_view = self._capacity_from(policy)
        recs = self._load_records() if startup else {}
        live_tasks = set()
        for row in rows:
            task_id = row["task_id"]
            live_tasks.add(task_id)
            if task_id in self.children:
                continue
            rec = recs.get(task_id) or self.blocked.get(task_id)      # a blocked entry keeps what it knew
            if rec and rec.get("token") != row["token"]:
                rec = None
            try:
                self._examine(row, rec, startup)
            except solar_state.StateError as exc:
                log(f"could not reconcile {task_id}: {exc}")
        for task_id, entry in list(self.blocked.items()):
            if entry.get("released") or task_id in live_tasks:
                if self._cleared(entry, task_id in live_tasks):
                    log(f"{task_id} is no longer blocked")
                    del self.blocked[task_id]
            elif task_id not in live_tasks:
                del self.blocked[task_id]
        # records of executions whose reservation is gone (the executor finished) are not needed
        self._save_records()

    def _cleared(self, entry: dict, still_reserved: bool) -> bool:
        if entry.get("reason") in ("cleanup_failed", "cleanup_unverified"):
            # every group the execution had (the executor's and the command's), not only the wrapper's
            groups = entry.get("pgids") or ([entry["pgid"]] if entry.get("pgid") else [])
            return bool(groups) and all(group_members(g) == [] for g in groups)
        if entry.get("reason") == "owner_unverifiable":
            return False
        return not still_reserved

    @staticmethod
    def _lease_expired(row: dict) -> bool:
        try:
            return lib.epoch(row["lease_expires_at"]) <= time.time()
        except (KeyError, ValueError):
            return False

    def _examine(self, row: dict, rec: Optional[dict], startup: bool) -> None:
        task_id = row["task_id"]
        if row.get("phase") == "ending":
            with self._session() as store:
                result = store.reservation_finish(task_id, row["token"], groups=group_members)
            if result["released"]:
                self.blocked.pop(task_id, None)
                log(f"{task_id}: ending execution released after its groups were proved gone")
            else:
                if task_id not in self.blocked:
                    self.blocked[task_id] = dict(task_id=task_id, token=row["token"],
                        reason="cleanup_unverified", detail=result["reason"], since=lib.iso(time.time()),
                        pgids=row.get("pgids") or [], released=False, ours=False)
            return
        if (self.blocked.get(task_id) or {}).get("reason") in (
                "owner_unverifiable", "owner_alive_lease_expired", "group_uncertain"):
            del self.blocked[task_id]               # judged again below; it comes back if still true
        ours = bool(rec) and rec.get("ours", True)  # dispatched or claimed by a supervisor, not by anyone else
        pids = []
        if row.get("owner_pid") is not None:
            pids.append((row["owner_pid"], row.get("owner_started")))
        if rec and rec.get("pid"):
            pids.append((rec["pid"], rec.get("started")))
        states = [lib.matches(pid, started)[0] for pid, started in pids]
        expired = self._lease_expired(row)
        pseudo = Execution(task_id, row["token"], (rec or {}).get("worker") or row.get("worker") or self.worker,
                           pid=(rec or {}).get("pid"), started=(rec or {}).get("started"), adopted=True,
                           access=(rec or {}).get("access") or {
                               "provider": row.get("provider"), "access_class": row.get("access_class"),
                               "resources": row.get("resources") or [], "scopes": row.get("scopes") or []})
        pseudo.foreign = not ours
        if rec and rec.get("pgid"):
            pseudo.pgid = rec["pgid"]
        if rec and rec.get("provider_pid"):
            pseudo.provider_pid = rec["provider_pid"]
        if "unknown" in states:
            self._block(pseudo, "owner_unverifiable", "the process table could not be asked about its owner",
                        released=False)
            return
        if "alive" in states:
            if ours and startup:
                pseudo.pid = rec.get("pid") or row.get("owner_pid")
                pseudo.started = rec.get("started") if rec.get("pid") else row.get("owner_started")
                self.children[task_id] = pseudo           # watched until it ends; never killed for being an orphan
                self.blocked.pop(task_id, None)
                log(f"adopted the running execution of {task_id} (pid {pseudo.pid})")
            elif expired:
                self._block(pseudo, "owner_alive_lease_expired",
                            "its process is alive but its lease stopped being renewed; it is not replaced",
                            released=False)
            return
        # Every process that could own it is gone (or none was ever recorded).
        unattached = row.get("owner_pid") is None and not (rec and rec.get("pid"))
        if unattached:
            if ours:
                # claimed here, never dispatched: nothing ran
                self._start_failure(task_id, row["token"], pseudo.worker, "the supervisor stopped before dispatching it")
            elif row.get("handoff"):
                if not self.draining and not self._maintenance():
                    self._take_over(task_id)           # a manual activation nobody runs yet
            elif expired:
                self._give_back_foreign(task_id)
            return
        if not expired and not ours:
            return                                     # a foreign owner that just died: the lease decides
        if pseudo.pgid and pseudo.pgid != os.getpgrp():
            members = group_members(pseudo.pgid)
            if members is None or members:
                # members it cannot prove are its own, or a process table that would not answer:
                # neither is "the group is empty", so the reservation stays and nothing is killed
                why = ("the process table could not be asked about its group" if members is None else
                       f"its executor is gone but process group {pseudo.pgid} still has members "
                       "that cannot be proven to be its own")
                self._block(pseudo, "group_uncertain", why, released=False)
                return
        if self._provider_group(pseudo, immediate=False)[0] != "none":
            if not self._settle_provider_group(pseudo, immediate=False):
                self._block(pseudo, "group_uncertain",
                            "its executor is gone but the command it started still has processes "
                            "that cannot be proven gone", released=False)
                return
        token = row["token"] if ours else self._adopt_token(task_id)
        if token is None:
            return
        self._fail(task_id, token, "executor_lost",
                   "its executor is gone without finishing the task")
        self.blocked.pop(task_id, None)
        log(f"{task_id}: executor gone without finishing; failed (outcome uncertain, not retried)")

    def _adopt_token(self, task_id: str) -> Optional[str]:
        with self._session() as store:
            taken = store.task_adopt(task_id, self.worker)
        return taken["token"] if taken.get("adopted") else None

    def _take_over(self, task_id: str) -> None:
        """A manual activation: the reservation exists and no executor was attached. Take it over
        with a new token (the previous one stops working) and run exactly that claim."""
        with self._session() as store:
            taken = store.task_adopt(task_id, self.worker)
            if not taken.get("adopted"):
                return
            access = self._access_of(store, task_id)
        log(f"taking over the manual activation of {task_id}")
        self._dispatch(task_id, taken["token"], self.worker, access)

    def _give_back_foreign(self, task_id: str) -> None:
        token = self._adopt_token(task_id)
        if token is not None:
            self._give_back(task_id, token, self.worker)


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "run"
    if command != "run":
        print("usage: supervisor.py run", file=sys.stderr)
        return 64
    ctx = lib.Context()
    supervisor = Supervisor(ctx)
    try:
        return supervisor.run()
    except BaseException as exc:                    # noqa: BLE001 - recorded, then re-raised
        supervisor._exit_record("crashed", f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
