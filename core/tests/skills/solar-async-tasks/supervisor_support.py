"""Shared pieces of the supervisor tests: a temporary runtime, executor doubles, the event log, cleanup.

Nothing here touches the machine runtime, a LaunchAgent, port 9000 or a provider. Every runtime is
a temporary directory with its own workspace owner; every process the tests start is recorded and
ended by `Rig.cleanup`, which only signals processes it can name from that runtime's own files.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

CORE_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = CORE_ROOT / "skills" / "solar-async-tasks" / "scripts"
DOUBLE = Path(__file__).with_name("executor_double.py")
for _dir in (SCRIPTS, CORE_ROOT / "skills" / "solar-state" / "scripts", CORE_ROOT / "tests" / "support"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import solar_state  # noqa: E402
import supervisor as supervisor_mod  # noqa: E402
import supervisor_lib as lib  # noqa: E402
from queue_mirror import env_for  # noqa: E402

PROFILE = "text_only_review_v1"


class _EveryProvider:
    def __contains__(self, _):
        return True


def pretend_profile_is_verified(monkeypatch) -> None:
    """No profile has a verified implementation until the delivery that confines one. Tests of
    concurrency stand in for it: declared readers may then run next to each other."""
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {PROFILE: _EveryProvider()})


def wait_until(predicate: Callable[[], object], timeout: float = 30.0, interval: float = 0.05, what: str = "") -> object:
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what or predicate}")
        time.sleep(interval)


def alive(pid: int) -> bool:
    kind, _ = lib.probe(pid)
    return kind == "alive"


class Rig:
    def __init__(self, tmp_path: Path, monkeypatch, name: str = "sun"):
        self.tmp = tmp_path
        self.workspace = tmp_path
        self.task_root = tmp_path / name / "runtime" / "async-tasks"
        self.task_root.mkdir(parents=True)
        self.env = env_for(self.task_root, {**os.environ, "SOLAR_WORKSPACE": str(tmp_path)})
        self.runtime = self.task_root.parent
        self.ctx = lib.Context(self.runtime)
        # Nothing here may reach the real LaunchAgent or a real service: the launchctl is a double
        # and service detection is switched off (core/docs/test-isolation.md).
        launchctl = tmp_path / f"launchctl-{name}"
        launchctl.write_text("#!/bin/sh\nexit 0\n")
        launchctl.chmod(0o755)
        self.env["SOLAR_CLIENT_LAUNCHCTL"] = str(launchctl)
        self.env["SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE"] = "none"
        self.guard()
        self.double_dir = tmp_path / f"double-{name}"
        for sub in ("spec", "gates", "barriers"):
            (self.double_dir / sub).mkdir(parents=True)
        self.env["DOUBLE_DIR"] = str(self.double_dir)
        monkeypatch.setenv("DOUBLE_DIR", str(self.double_dir))   # in-process supervisors pass os.environ on
        self.threads: list[threading.Thread] = []
        self.supervisors: list[supervisor_mod.Supervisor] = []

    def guard(self) -> None:
        """The shell guard of the suite, with this rig's environment: it aborts (exit 97) when the
        runtime is the machine runtime or launchctl is the system binary, and with --services when
        service detection would reach the real ones."""
        guard = CORE_ROOT / "tests" / "support" / "shell_runtime_guard.sh"
        done = subprocess.run(["bash", "-c", f'source "{guard}"; solar_test_guard --services'],
                              env={**self.env, "SOLAR_ROOT": str(CORE_ROOT.parent)}, capture_output=True, text=True)
        assert done.returncode == 0, f"test isolation guard refused: {done.stdout}{done.stderr}"

    # -- tasks ------------------------------------------------------------------------

    def _create(self, title: str, extra: list, status: str = "queued") -> str:
        fields = [("title", json.dumps(title))] + extra
        with solar_state.session() as store:
            task_id = store.task_create(fields, f"\n# {title}\n\nDo {title}.\n", status=status,
                                        task_id=title.lower().replace(" ", "-"))
        return task_id

    def reader(self, title: str, provider: str = "codex", spec: Optional[dict] = None,
               scopes=(), resources=(), mode: str = "read", **extra) -> str:
        """A declared task that may run next to others once the profile is verified and enabled."""
        policy = json.dumps(dict(version=1, mode=mode, scopes=list(scopes), resources=list(resources)),
                            sort_keys=True, separators=(",", ":"))
        fields = [("provider", provider), ("access_policy", policy), ("execution_profile", PROFILE)]
        fields += [(k, v) for k, v in extra.items()]
        task_id = self._create(title, fields)
        if spec is not None:
            self.spec(task_id, **spec)
        return task_id

    def legacy(self, title: str, spec: Optional[dict] = None, **extra) -> str:
        """A task with no access declaration: it runs alone."""
        task_id = self._create(title, [(k, v) for k, v in extra.items()])
        if spec is not None:
            self.spec(task_id, **spec)
        return task_id

    def local(self, title: str, script_rel: str, *, timeout: int = 60, **extra) -> str:
        """A deterministic local task (what the real executor runs without a provider)."""
        fields = [("executor", "local"), ("local_command", json.dumps(f"bash {script_rel} {title}")),
                  ("local_timeout", str(timeout))] + [(k, v) for k, v in extra.items()]
        return self._create(title, fields)

    def local_script(self, body: str, name: str = "run.sh") -> str:
        script = self.workspace / "planets" / "louis" / "skills" / "sync" / "scripts" / name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("#!/bin/bash\n" + body, encoding="utf-8")
        script.chmod(0o755)
        return script.relative_to(self.workspace).as_posix()

    def spec(self, task_id: str, **spec) -> None:
        (self.double_dir / "spec" / f"{task_id}.json").write_text(json.dumps(spec), encoding="utf-8")

    def gate(self, name: str) -> None:
        (self.double_dir / "gates" / name).write_text("open")

    def status(self, task_id: str) -> Optional[str]:
        with solar_state.session() as store:
            return store.task_status(task_id)

    def apply_policy(self, **changes) -> dict:
        with solar_state.session() as store:
            current = store.async_policy()
            document = dict(schema_version=1, revision=current["revision"] + 1,
                            global_capacity=current["global_capacity"],
                            provider_capacity=current["provider_capacity"],
                            exclusive_wait_seconds=current["exclusive_wait_seconds"],
                            enabled_reader_profiles=[PROFILE])
            document.update(changes)
            return store.async_policy_apply(document, actor="test")

    def reservations_of(self, task_id: str):
        return next((r for r in self.reservations() if r["task_id"] == task_id), None)

    def reservations(self) -> list[dict]:
        with solar_state.session() as store:
            return store.reservations()

    # -- events -----------------------------------------------------------------------

    def events(self, name: Optional[str] = None, task: Optional[str] = None) -> list[dict]:
        path = self.double_dir / "events.jsonl"
        if not path.is_file():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        return [r for r in rows if (name is None or r["event"] == name) and (task is None or r["task"] == task)]

    def first(self, event: str, task: str) -> float:
        return self.events(event, task)[0]["t"]

    def max_overlap(self) -> int:
        """The most executions that were between `start` and `end` at the same instant."""
        points = []
        for row in self.events():
            if row["event"] == "start":
                points.append((row["t"], 1))
            elif row["event"] in ("end", "crash", "hang"):
                points.append((row["t"], -1))
        points.sort()
        best = running = 0
        for _, delta in points:
            running += delta
            best = max(best, running)
        return best

    # -- an in-process supervisor over the doubles -------------------------------------

    def executor(self, task_id: str, token: str) -> list[str]:
        return [sys.executable, str(DOUBLE), "--task", task_id, "--token", token]

    def build(self, **kw) -> supervisor_mod.Supervisor:
        kw.setdefault("poll", 0.2)
        kw.setdefault("sweep", 0.5)
        kw.setdefault("term_grace", 1.0)
        kw.setdefault("kill_wait", 2.0)
        kw.setdefault("cancel_grace", 1.0)
        kw.setdefault("cooldown", 0.2)
        sup = supervisor_mod.Supervisor(self.ctx, executor=kw.pop("executor", self.executor),
                                        install_signals=False, **kw)
        self.supervisors.append(sup)
        return sup

    @contextmanager
    def running(self, **kw):
        """Run a Supervisor in a thread of this process until the block ends, then drain it."""
        sup = self.build(**kw)
        box: dict = {}
        thread = threading.Thread(target=lambda: box.setdefault("code", sup.run()), daemon=True,
                                  name="supervisor-under-test")
        thread.start()
        self.threads.append(thread)
        wait_until(lambda: sup.reconciled or not thread.is_alive(), 30, what="the supervisor to be ready")
        assert sup.reconciled, f"the supervisor did not start: {box}"
        try:
            yield sup
        finally:
            sup._request_drain("test")
            thread.join(60)
            assert not thread.is_alive(), "the supervisor did not drain"

    def stop_abruptly(self, sup: supervisor_mod.Supervisor, thread_box: threading.Thread) -> None:
        sup.stop_event.set()
        sup.wake.set()
        thread_box.join(30)

    # -- real processes through the scripts -----------------------------------------------

    def script(self, name: str, *args: str, timeout: float = 60, extra_env: Optional[dict] = None,
               cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPTS / name), *args], env={**self.env, **(extra_env or {})},
                              capture_output=True, text=True, timeout=timeout, cwd=cwd or self.workspace)

    def answer(self, proc: subprocess.CompletedProcess) -> dict:
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def identity(self) -> Optional[dict]:
        return lib.read_json(self.ctx.identity_file)

    def supervisor_pid(self) -> Optional[int]:
        ident = self.identity()
        if ident and lib.matches(ident.get("pid"), ident.get("started"))[0] == "alive":
            return ident["pid"]
        return None

    # -- cleanup --------------------------------------------------------------------------

    def cleanup(self) -> None:
        """End what this rig started, and only that: every process is named by its recorded pid AND
        start time (a reused pid is never signalled), and a group is signalled only when its
        recorded leader is still the process that started it."""
        for sup in self.supervisors:
            sup.stop_event.set()
            sup.wake.set()
        for thread in self.threads:
            thread.join(10)

        def kill(pid, started=None, group=False, command_has=None):
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                return
            if pid <= 1 or pid in (os.getpid(), os.getppid()):
                return
            kind, info = lib.probe(pid)
            if kind != "alive":
                return
            if started is not None and info.get("start") != started:
                return
            if command_has and command_has not in (info.get("command") or ""):
                return
            try:
                if group and pid != os.getpgrp():
                    os.killpg(pid, signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

        for path in (self.ctx.identity_file, self.ctx.candidate_file):
            data = lib.read_json(path)
            if isinstance(data, dict):
                kill(data.get("pid"), data.get("started"))
        for name in (self.ctx.children_file, self.ctx.blocked_file):
            data = lib.read_json(name) or {}
            for item in data.get("executions", []) + data.get("blocked", []):
                kill(item.get("pid"), item.get("started"), group=True)
        for path in self.double_dir.glob("straggler-*.pid"):
            kill(path.read_text() or 0, command_has="time.sleep(300)")
        for path in self.double_dir.glob("pids/*"):
            try:
                record = json.loads(path.read_text())
            except ValueError:
                continue
            kill(record.get("pid"), record.get("started"), group=True)
