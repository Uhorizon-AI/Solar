#!/usr/bin/env python3
"""Resident async-tasks supervisor: where it lives, who it is, how it is observed, launched and drained.

Everything that is not the supervisor loop itself. `ensure_async_tasks.sh`, `check_async_tasks.sh`,
`launch_supervisor.sh` and `stop_supervisor.sh` are thin wrappers over the commands below, so they
all resolve the same files from solar-paths and judge the same identity.

Only the supervisor (`supervisor.py run`) acquires `<runtime root>/async-tasks/.locks/supervisor.lock`
and writes `supervisor.json` next to it. Observers read that identity and prove the process behind it
(pid and start time); they never take the lock, never write a pid for the owner and never remove
anything of the owner. No environment variable moves these files or names another owner.

Commands (JSON on stdout, one object on the last line):
  observe  state of the supervisor; exit 0 ready, 10 starting, 20 blocked, 1 failed or not running
  ensure   observe, start a candidate when none is alive, wait at most the handshake budget
  launch   start a candidate (what ensure does); never a second one while one is alive
  poke     queue signal: ask the identified supervisor to fill free places now (SIGUSR1)
  stop     --drain [--timeout N]: ask the identified supervisor to finish its executions and exit
"""
from __future__ import annotations

import argparse
import calendar
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).resolve().parent
_SCRIPTS = HERE.parents[1]
for _dir in (_SCRIPTS / "solar-paths" / "scripts", _SCRIPTS / "solar-state" / "scripts"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import solar_runtime  # noqa: E402

SCHEMA = 1
READY, STARTING, BLOCKED, FAILED, ABSENT = "ready", "starting", "blocked", "failed", "absent"
EXIT_CODES = {READY: 0, STARTING: 10, BLOCKED: 20, FAILED: 1, ABSENT: 1}


def _env_seconds(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return min(max(value, low), high)


# Timings of the contract. The environment can only move how long an observer waits or how stale
# a heartbeat may be judged; nothing here names another owner or another lock.
HANDSHAKE_BUDGET = _env_seconds("SOLAR_SUPERVISOR_HANDSHAKE_SECONDS", 5.0, 0.2, 5.0)
STARTING_LIMIT = _env_seconds("SOLAR_SUPERVISOR_STARTING_LIMIT", 120.0, 1.0, 600.0)
HEARTBEAT_STALE = _env_seconds("SOLAR_SUPERVISOR_HEARTBEAT_STALE", 30.0, 2.0, 600.0)
LEGACY_WORKER_LIMIT = _env_seconds("SOLAR_SUPERVISOR_LEGACY_LIMIT", 120.0, 1.0, 3600.0)
UNCERTAIN_HOLD = _env_seconds("SOLAR_SUPERVISOR_UNCERTAIN_HOLD", 300.0, 1.0, 3600.0)

LEGACY_GUARD_DEFAULT = "/tmp/solar-async-tasks-worker.lock"
_LSTART = re.compile(r"^(\S+)\s+([A-Za-z]{3} [A-Za-z]{3}\s+\d{1,2} \d{2}:\d{2}:\d{2} \d{4})\s*(.*)$")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def epoch(stamp: str) -> float:
    """Seconds since the epoch of an UTC stamp as the state writes it."""
    return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))


def write_json_atomic(path: Path, data: Any, mode: int = 0o644, durable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Process identity: pid plus start time. A pid alone is never an identity.
# ---------------------------------------------------------------------------

def probe(pid: Any) -> tuple[str, dict]:
    """('alive', {start, epoch, command}) | ('gone', {}) | ('unknown', {reason}).

    A zombie is gone. `unknown` means the process table could not be asked: nobody is replaced,
    stopped or declared dead on a guess."""
    try:
        number = int(pid)
        if number <= 0:
            return "gone", {}
    except (TypeError, ValueError):
        return "gone", {}
    try:
        done = subprocess.run(["ps", "-ww", "-o", "stat=,lstart=,command=", "-p", str(number)],
                              capture_output=True, text=True, check=False, timeout=10,
                              env={**os.environ, "LC_ALL": "C", "LANG": "C"})
    except (OSError, subprocess.SubprocessError) as exc:
        return "unknown", {"reason": f"cannot ask the process table: {exc}"}
    out = done.stdout.strip()
    if not out:
        if done.returncode == 1 and not done.stderr.strip():
            return "gone", {}
        return "unknown", {"reason": f"the process table answered {done.returncode}: "
                                     f"{done.stderr.strip()[:120]}"}
    match = _LSTART.match(out)
    if not match:
        return "unknown", {"reason": f"unreadable process table line: {out[:80]}"}
    stat, start, command = match.groups()
    if stat.startswith("Z"):
        return "gone", {}
    try:
        epoch = time.mktime(time.strptime(re.sub(r"\s+", " ", start), "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        epoch = None
    return "alive", {"start": re.sub(r"\s+", " ", start), "epoch": epoch, "command": command}


def process_start(pid: Any) -> Optional[str]:
    kind, info = probe(pid)
    return info.get("start") if kind == "alive" else None


def matches(pid: Any, started: Optional[str]) -> tuple[str, dict]:
    """Is `pid` still the process that started at `started`? ('alive'|'gone'|'unknown', info)."""
    kind, info = probe(pid)
    if kind == "alive":
        if not started or info.get("start") != started:
            return "gone", {}                      # the pid was reused
    return kind, info


# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------

class Context:
    """The runtime this process serves. Always from solar-paths; there is no override of the lock."""

    def __init__(self, runtime: Optional[Path] = None):
        self.runtime = Path(runtime) if runtime is not None else solar_runtime.runtime_root()
        self.tasks = self.runtime / "async-tasks"
        self.locks = self.tasks / ".locks"
        self.support = self.tasks / "supervisor"
        self.lock_file = self.locks / "supervisor.lock"
        self.identity_file = self.locks / "supervisor.json"
        self.candidate_file = self.locks / "supervisor-candidate.json"
        self.launch_guard = self.locks / "supervisor-launch.lock"
        self.control_file = self.locks / "supervisor-control.json"
        self.exit_file = self.locks / "supervisor-exit.json"
        self.children_file = self.support / "children.json"
        self.blocked_file = self.support / "blocked.json"
        self.log_file = self.support / "supervisor.log"
        self.install_root = str(HERE.parents[3])

    def owner(self) -> Optional[dict]:
        data = read_json(self.runtime / "workspace-owner.json")
        if isinstance(data, dict) and str(data.get("workspace_id") or "").strip():
            return data
        return None

    def expected(self) -> Optional[dict]:
        """What a supervisor of this runtime must say it is."""
        owner = self.owner()
        if owner is None:
            return None
        return {"runtime": str(self.runtime), "workspace_id": str(owner["workspace_id"]),
                "workspace": str(owner.get("path") or ""), "install_root": self.install_root}

    def maintenance(self) -> Optional[dict]:
        import solar_state
        return solar_state.maintenance_state(self.runtime)

    def legacy_guard(self) -> Path:
        return Path(os.environ.get("SOLAR_TASK_WORKER_LOCK") or LEGACY_GUARD_DEFAULT)


def identity_mismatch(recorded: dict, expected: dict) -> Optional[str]:
    for key in ("runtime", "workspace_id", "install_root"):
        if str(recorded.get(key) or "") != str(expected.get(key) or ""):
            return key
    return None


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def _result(state: str, reason: Optional[str], *, identity: Optional[dict] = None,
            age: Optional[float] = None, heartbeat_age: Optional[float] = None,
            **extra: Any) -> dict:
    out = {"state": state, "code": EXIT_CODES[state], "reason": reason, "identity": identity,
           "age_seconds": None if age is None else round(max(age, 0.0), 1),
           "heartbeat_age_seconds": None if heartbeat_age is None else round(max(heartbeat_age, 0.0), 1)}
    out.update(extra)
    return out


def _identity_view(kind: str, pid: Any, started: Optional[str], record: Optional[dict] = None) -> dict:
    view = {"kind": kind, "pid": pid, "started": started}
    for key in ("runtime", "workspace_id", "workspace", "install_root"):
        if record and record.get(key) is not None:
            view[key] = record[key]
    return view


def legacy_worker(ctx: Context) -> Optional[dict]:
    """The one-shot worker of the previous design, if its machine guard names one that still runs.
    Read only: the guard is never written or removed here."""
    try:
        pid = int(ctx.legacy_guard().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    kind, info = probe(pid)
    if kind == "unknown":
        return {"pid": pid, "unknown": True, "reason": info.get("reason")}
    if kind != "alive":
        return None
    command = info.get("command") or ""
    if "run_worker.sh" not in command and "ensure_async_tasks.sh" not in command:
        return None                                # the pid belongs to something else now
    return {"pid": pid, "started": info.get("start"), "epoch": info.get("epoch")}


def observe(ctx: Context, *, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    expected = ctx.expected()
    if expected is None:
        return _result(BLOCKED, "no_workspace_owner",
                       detail="the runtime has no workspace owner: nothing can be supervised")
    recorded = read_json(ctx.identity_file)
    exit_record = read_json(ctx.exit_file)
    dead_pid = None
    if isinstance(recorded, dict) and recorded.get("pid") is not None:
        kind, info = matches(recorded.get("pid"), recorded.get("started"))
        if kind == "unknown":
            return _result(BLOCKED, "owner_unverifiable",
                           identity=_identity_view("supervisor", recorded.get("pid"), recorded.get("started"), recorded),
                           detail=info.get("reason"))
        if kind == "alive":
            view = _identity_view("supervisor", recorded["pid"], recorded.get("started"), recorded)
            wrong = identity_mismatch(recorded, expected)
            if wrong:
                return _result(BLOCKED, "identity_mismatch", identity=view,
                               detail=f"a supervisor with another {wrong} holds this runtime")
            started_at = float(recorded.get("started_epoch") or now)
            beat = float(recorded.get("heartbeat_epoch") or started_at)
            age, beat_age = now - started_at, now - beat
            common = dict(identity=view, age=age, heartbeat_age=beat_age,
                          capacity=recorded.get("capacity"), blocked_executions=recorded.get("blocked") or [])
            state = recorded.get("state")
            if state == "draining":
                return _result(BLOCKED, "draining", **common,
                               detail="a drain was requested: it leaves when its executions end")
            if beat_age > HEARTBEAT_STALE:
                return _result(BLOCKED, "stale_heartbeat", **common,
                               detail="the process is alive but its heartbeat stopped; it is not replaced")
            if state != "ready" or not recorded.get("reconciled"):
                if age > STARTING_LIMIT:
                    return _result(BLOCKED, "starting_timeout", **common,
                                   detail=f"starting for more than {int(STARTING_LIMIT)}s")
                return _result(STARTING, "reconciling", **common)
            if recorded.get("blocked"):
                return _result(BLOCKED, "recovery_required", **common,
                               detail="executions with an uncertain owner or failed cleanup are blocked")
            return _result(READY, None, **common)
        dead_pid = recorded.get("pid")
    candidate = read_json(ctx.candidate_file)
    if isinstance(candidate, dict) and candidate.get("pid") is not None:
        kind, info = matches(candidate.get("pid"), candidate.get("started"))
        if kind == "unknown":
            return _result(BLOCKED, "owner_unverifiable",
                           identity=_identity_view("candidate", candidate.get("pid"), candidate.get("started")),
                           detail=info.get("reason"))
        if kind == "alive":
            age = now - float(candidate.get("launched_epoch") or now)
            view = _identity_view("candidate", candidate["pid"], candidate.get("started"))
            if age > STARTING_LIMIT:
                return _result(BLOCKED, "starting_timeout", identity=view, age=age,
                               detail=f"starting for more than {int(STARTING_LIMIT)}s")
            return _result(STARTING, "handshake_pending", identity=view, age=age)
        dead_pid = dead_pid if dead_pid is not None else candidate.get("pid")
    if isinstance(exit_record, dict) and exit_record.get("pid") is not None \
            and exit_record.get("reason") not in (None, "drained"):
        mine = exit_record.get("pid") in (dead_pid, (candidate or {}).get("pid"))
        if exit_record.get("reason") == "lock_held_without_identity":
            # A lock held by something that shows no identity is an owner nobody can name. It is
            # reported blocked, and no candidate is launched against it for a while.
            try:
                recent = now - epoch(str(exit_record.get("at"))) < UNCERTAIN_HOLD
            except ValueError:
                recent = False
            if recent:
                return _result(BLOCKED, "lock_held_without_identity", detail=exit_record.get("detail"),
                               at=exit_record.get("at"))
        elif mine:
            return _result(FAILED, exit_record.get("reason"), identity=_identity_view(
                "supervisor", exit_record.get("pid"), exit_record.get("started")),
                detail=exit_record.get("detail"), at=exit_record.get("at"))
    legacy = legacy_worker(ctx)
    if legacy:
        if legacy.get("unknown"):
            return _result(BLOCKED, "owner_unverifiable", identity=_identity_view("legacy_worker", legacy["pid"], None),
                           detail=legacy.get("reason"))
        age = now - float(legacy.get("epoch") or now)
        view = _identity_view("legacy_worker", legacy["pid"], legacy.get("started"))
        if age > LEGACY_WORKER_LIMIT:
            return _result(BLOCKED, "legacy_worker_running", identity=view, age=age,
                           detail="the one-shot worker of the previous design is still running; "
                                  "the supervisor starts when it ends")
        return _result(STARTING, "legacy_worker_draining", identity=view, age=age)
    return _result(ABSENT, "not_running", detail="stale identity of a dead supervisor" if dead_pid else None)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

_LAUNCHED: list[subprocess.Popen] = []


class _Guard:
    """Short exclusion between two launchers, so two ticks do not start two candidates. It is not
    the supervisor lock: the supervisor never takes it and holding it proves nothing about ownership."""

    def __init__(self, path: Path, timeout: float = 3.0):
        self.path, self.timeout, self.handle = path, timeout, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    raise TimeoutError("another launcher holds the launch guard")
                time.sleep(0.02)

    def __exit__(self, *exc):
        self.handle.close()


def launch(ctx: Context, *, env: Optional[dict] = None) -> dict:
    """Start one supervisor candidate in its own session, unless one is already alive.

    stdin is null and stdout/stderr go to the supervisor's own log: nothing of the caller's pipes
    is inherited, so a tick (or a test) that waits for its output is never held by the supervisor."""
    ctx.support.mkdir(parents=True, exist_ok=True)
    try:
        guard = _Guard(ctx.launch_guard)
        guard.__enter__()
    except TimeoutError as exc:
        return {"launched": False, "reason": "launch_guard_busy", "detail": str(exc)}
    try:
        seen = observe(ctx)
        if seen["state"] not in (ABSENT, FAILED):
            return {"launched": False, "reason": seen["state"], "observed": seen}
        log = open(ctx.log_file, "ab")
        try:
            proc = subprocess.Popen(
                [sys.executable, str(HERE / "supervisor.py"), "run"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                close_fds=True, env=env if env is not None else os.environ.copy())
        finally:
            log.close()
        _LAUNCHED.append(proc)
        launched_epoch = time.time()
        write_json_atomic(ctx.candidate_file, {
            "pid": proc.pid, "started": process_start(proc.pid), "launched_epoch": launched_epoch,
            "launched_at": iso(launched_epoch), "launcher_pid": os.getpid(),
            "runtime": str(ctx.runtime)})
        return {"launched": True, "pid": proc.pid}
    finally:
        guard.__exit__(None, None, None)


def _reap_launched() -> None:
    for proc in list(_LAUNCHED):
        if proc.poll() is not None:
            _LAUNCHED.remove(proc)


def _wait_handshake(ctx: Context, started: float, budget: float,
                    sleep: Callable[[float], None] = time.sleep) -> dict:
    while True:
        _reap_launched()
        seen = observe(ctx)
        if seen["state"] in (READY, BLOCKED, FAILED):
            return seen
        if time.monotonic() - started >= budget:
            return seen
        sleep(0.05)


def ensure(ctx: Context, *, budget: float = HANDSHAKE_BUDGET) -> dict:
    """What a tick does: observe, start a candidate when none is alive, wait for the handshake.

    The wait is bounded by the handshake budget and never by the executions the supervisor runs.
    A held maintenance barrier is not worked around: no candidate is started and the answer is
    `blocked`. Past the budget the answer is `starting` only while a live process with a verifiable
    identity stands behind it; without one it is `blocked`, never success and never a licence to
    start another."""
    started = time.monotonic()
    held = ctx.maintenance()
    if held is not None:
        seen = observe(ctx)
        return _result(BLOCKED, "maintenance", detail="an update holds the maintenance barrier: "
                       "no supervisor is started", supervisor=seen["state"],
                       identity=seen.get("identity"), age=seen.get("age_seconds"))
    seen = observe(ctx)
    launched = None
    if seen["state"] in (ABSENT, FAILED):
        try:
            launched = launch(ctx)
        except OSError as exc:
            return _result(FAILED, "launch_failed", detail=str(exc))
        seen = _wait_handshake(ctx, started, budget)
    elif seen["state"] == STARTING:
        seen = _wait_handshake(ctx, started, budget)
    if seen["state"] == ABSENT:
        # We started one (or another launcher did) and nothing alive stands behind it any more.
        seen = _result(BLOCKED, "startup_unverified", detail="no live supervisor identity after the "
                       "handshake budget; not treated as running and not started again this tick")
    seen["launched"] = bool(launched and launched.get("launched"))
    return seen


# ---------------------------------------------------------------------------
# Drain
# ---------------------------------------------------------------------------

def stop(ctx: Context, *, timeout: float, poll: float = 0.2, requested_by: str = "stop_supervisor") -> tuple[int, dict]:
    """Ask the identified supervisor to stop dispatching, collect its executions and exit.

    Exit codes: 0 gone with nothing pending; 1 still draining when the time ran out (nothing is
    killed); 2 refused, the owner cannot be identified; 3 gone but executions with an uncertain
    owner or failed cleanup remain blocked."""
    deadline = time.monotonic() + timeout
    asked_for: Optional[tuple] = None
    last_seen: dict = {}
    while True:
        recorded = read_json(ctx.identity_file)
        owner_alive = False
        if isinstance(recorded, dict) and recorded.get("pid") is not None:
            kind, info = matches(recorded["pid"], recorded.get("started"))
            if kind == "unknown":
                return 2, {"state": "refused", "reason": "owner_unverifiable", "detail": info.get("reason")}
            if kind == "alive":
                owner_alive = True
                last_seen = recorded
                target = (recorded["pid"], recorded.get("started"))
                if asked_for != target:
                    write_json_atomic(ctx.control_file, {
                        "request": "drain", "target_pid": recorded["pid"],
                        "target_started": recorded.get("started"),
                        "requested_at": iso(time.time()), "requested_by": requested_by})
                    asked_for = target
        candidate = read_json(ctx.candidate_file)
        candidate_alive = False
        if not owner_alive and isinstance(candidate, dict) and candidate.get("pid") is not None:
            kind, _ = matches(candidate["pid"], candidate.get("started"))
            candidate_alive = kind == "alive"      # it may still win the lock: wait for it
        if not owner_alive and not candidate_alive:
            pending = (read_json(ctx.identity_file) or last_seen or {}).get("blocked") or []
            state = {"state": "stopped", "reason": "not_running" if asked_for is None else "drained",
                     "pending": pending}
            return (3, dict(state, reason="blocked_executions")) if pending else (0, state)
        if time.monotonic() >= deadline:
            current = read_json(ctx.identity_file) or last_seen or {}
            return 1, {"state": "draining", "reason": "timeout",
                       "children": current.get("children") or [], "blocked": current.get("blocked") or [],
                       "detail": "the supervisor was asked to drain and is still collecting its executions; "
                                 "nothing was killed"}
        time.sleep(poll)


# ---------------------------------------------------------------------------
# Queue signal
# ---------------------------------------------------------------------------

def poke(ctx: Context) -> dict:
    """Tell the identified supervisor the queue changed (SIGUSR1): it fills free places now instead
    of at its next poll (at most one second away). Only a process whose pid and start time match
    the published identity is signalled; anything else is left alone."""
    recorded = read_json(ctx.identity_file)
    if not isinstance(recorded, dict) or recorded.get("pid") is None:
        return {"poked": False, "reason": "not_running"}
    kind, info = matches(recorded["pid"], recorded.get("started"))
    if kind != "alive":
        return {"poked": False, "reason": "not_running" if kind == "gone" else "owner_unverifiable"}
    os.kill(int(recorded["pid"]), signal.SIGUSR1)
    return {"poked": True, "pid": recorded["pid"]}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _emit(result: dict, *, summary: bool = True) -> None:
    """The JSON object is the last line of stdout. A one-line summary for people goes to stderr."""
    if summary and "state" in result:
        bits = [f"async-tasks supervisor: {result['state']}"]
        if result.get("reason"):
            bits.append(f"({result['reason']})")
        who = result.get("identity") or {}
        if who.get("pid"):
            bits.append(f"pid {who['pid']}")
        print(" ".join(bits), file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="supervisor_lib.py")
    parser.add_argument("--runtime", default=None, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("observe")
    sub.add_parser("ensure")
    sub.add_parser("launch")
    sub.add_parser("poke")
    stopper = sub.add_parser("stop")
    stopper.add_argument("--drain", action="store_true")
    stopper.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    ctx = Context(Path(args.runtime) if args.runtime else None)
    if args.cmd == "observe":
        result = observe(ctx)
        held = ctx.maintenance()
        if held is not None and result["state"] != READY:
            result = dict(result, state=BLOCKED, code=EXIT_CODES[BLOCKED], supervisor=result["state"],
                          reason="maintenance")
        _emit(result)
        return result["code"]
    if args.cmd == "ensure":
        result = ensure(ctx)
        _emit(result)
        return result["code"]
    if args.cmd == "launch":
        try:
            result = launch(ctx)
        except OSError as exc:
            _emit({"launched": False, "reason": "launch_failed", "detail": str(exc)})
            return 1
        _emit(result)
        return 0 if result.get("launched") or result.get("reason") in (READY, STARTING) else 1
    if args.cmd == "poke":
        result = poke(ctx)
        _emit(result, summary=False)
        return 0 if result["poked"] else 1
    if args.cmd == "stop":
        if not args.drain:
            print("stop_supervisor.sh only drains: pass --drain", file=sys.stderr)
            return 64
        code, result = stop(ctx, timeout=args.timeout)
        _emit(result)
        return code
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
