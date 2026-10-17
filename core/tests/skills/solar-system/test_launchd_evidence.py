"""Opt-in REAL launchd evidence harness (the contract of async-rollout.md §Prerequisites).

This is NOT part of the automatic suite. It runs only when both hold:

  1. the environment variable SOLAR_TEST_LAUNCHD=1 is set, and
  2. the host is macOS (launchctl exists).

Without SOLAR_TEST_LAUNCHD=1 (or on Linux) the test skips: the CI "Install E2E"
job and the pytest suites never reach launchd, a LaunchAgent or port 9000.

What it proves, with timestamps, process identity (pid + start time) and events
collected in a temporary runtime, using deterministic local tasks (no provider):

  (a) the ensure tick ends while the resident supervisor stays alive;
  (b) killing ONLY that supervisor: the next tick recovers it within 75 s
      (60 s tick + 5 s handshake + margin), with reconciliation and no double
      dispatch of any execution;
  (c) already-running executions are not duplicated;
  (d) final cleanup: `launchctl bootout` of THIS label only, and proof that no
      job, no processes and no temporary-runtime files remain. A failure in any
      step performs the same cleanup in a finally block.

Hard refusals (the harness must not even start) — core/docs/test-isolation.md
and the encargo rules:

  - label            != com.solar.system (the production LaunchAgent is never
                       rendered, bootstrapped or bootout'ed by this harness)
  - no port is bound at all (the feature set is async-tasks only: no gateway,
    no host, nothing listens on 9000)
  - runtime root     under /private/tmp, never the live runtime
  - SOLAR_ROOT       the agent's install is a COPY under /private/tmp; the
    repository this test lives in is never bootstrap'd as the install

Processes are signalled only by recorded pid AND start time (supervisor_lib
.matches), never by name. Every kill is of a process this harness recorded.

How isolation reaches the launchd process: production injects only
SOLAR_WORKSPACE and SOLAR_ROOT into the plist; everything else comes from the
workspace `.env` that run_orchestrator.sh sources (`solar_system_load_env`).
This harness writes that same `.env` in the temporary workspace, so the tick,
the supervisor and the seeded local tasks all resolve the temporary runtime.

Run:
  SOLAR_TEST_LAUNCHD=1 uv run --project core/tests pytest \
      core/tests/skills/solar-system/test_launchd_evidence.py -q -s
"""
from __future__ import annotations

import json
import os
import plistlib
import platform
import signal
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[3]
STATE = CORE / "skills" / "solar-state" / "scripts"
ASYNC = CORE / "skills" / "solar-async-tasks" / "scripts"
SYSTEM = CORE / "skills" / "solar-system" / "scripts"
for p in (str(STATE), str(ASYNC), str(CORE / "tests" / "support")):
    if p not in sys.path:
        sys.path.insert(0, p)

TICK_SECONDS = 60
RECOVERY_BUDGET = 75          # 60 tick + 5 handshake + margin
LABEL_PREFIX = "com.solar.test.async."
FORBIDDEN_LABEL = "com.solar.system"
LIVE_RUNTIME = Path.home() / "Library" / "Application Support" / "Solar"


def _launchctl() -> str:
    return shutil.which("launchctl") or "/bin/launchctl"


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def _plist_label_listed(label: str) -> bool:
    """True when `launchctl print` shows the label in the user's gui domain."""
    done = subprocess.run([_launchctl(), "print", f"{_launchctl_domain()}/{label}"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0


def _process_start(pid: int) -> str | None:
    import supervisor_lib as lib
    kind, info = lib.probe(pid)
    return info.get("start") if kind == "alive" else None


def _kill_by_identity(pid: int | None, started: str | None, sig=15) -> bool:
    """Signal ONLY a recorded pid whose start time still matches. Never by name."""
    import supervisor_lib as lib
    if not started or not pid or int(pid) <= 1 or int(pid) in (os.getpid(), os.getppid()):
        return False
    kind, _ = lib.matches(pid, started)
    if kind != "alive":
        return False
    try:
        os.kill(int(pid), sig)
        return True
    except OSError:
        return False


class _EnvKeeper:
    """Stands in for pytest's monkeypatch outside a fixture: setenv records the
    previous value and restore() puts every touched variable back."""

    def __init__(self) -> None:
        self._saved: dict[str, str | None] = {}

    def setenv(self, key: str, value: str) -> None:
        self._saved.setdefault(key, os.environ.get(key))
        os.environ[key] = str(value)

    def restore(self) -> None:
        for key, previous in self._saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


class LaunchdRig:
    """A temporary install, workspace and runtime under /private/tmp, driven by a REAL
    user LaunchAgent with a private label. Everything is cleaned in cleanup()."""

    def __init__(self) -> None:
        self.base = Path("/private/tmp") / f"solar-launchd-{uuid.uuid4().hex[:8]}"
        # The PLIST lives in ~/Library/LaunchAgents (a real plist the gui domain can
        # bootstrap; a plist under /private/tmp fails bootstrap with "5: Input/output
        # error" — the same lesson install_launchagent_macos.sh records for logs).
        # The per-run folder name embeds nothing shared; cleanup removes it whole.
        # The entrypoint lives in the TEMP runtime (production layout:
        # <runtime>/system/Solar). Everything else — install, workspace, runtime,
        # logs — stays under /private/tmp.
        self.agent_dir = (Path.home() / "Library" / "LaunchAgents" /
                          f".solar-launchd-evidence-{uuid.uuid4().hex[:8]}")
        self.install = self.base / "install"
        self.workspace = self.base / "ws"
        self.runtime = self.base / "runtime"
        self.logs = self.base / "logs"
        self.label = LABEL_PREFIX + uuid.uuid4().hex[:12]
        self.plist = self.agent_dir / f"{self.label}.plist"
        self.entrypoint = self.runtime / "system" / "Solar"
        self.tick_log = self.logs / "tick.jsonl"        # what this harness observed per tick
        self.events: list[dict] = []                     # the evidence record (also dumped)
        self.started_pids: list[tuple[int, str | None]] = []
        self.booted = False
        self._env = _EnvKeeper()

    # -- guards ---------------------------------------------------------------

    def assert_safe(self) -> None:
        if self.label == FORBIDDEN_LABEL or not self.label.startswith(LABEL_PREFIX):
            raise ValueError("refused: production or non-test label")
        base = self.base.resolve()
        live = Path.home() / ".local/share/solar"
        inherited = Path(os.environ.get("SOLAR_ROOT") or CORE.parent).resolve()
        if inherited == live.resolve():
            raise ValueError("refused: inherited SOLAR_ROOT is the live installation")
        for path in (base, self.install.resolve(), self.workspace.resolve(), self.runtime.resolve()):
            if not path.is_relative_to(Path("/private/tmp")) or path == Path("/private/tmp"):
                raise ValueError(f"refused: non-temporary path {path}")
        if self.runtime.resolve().is_relative_to(LIVE_RUNTIME.resolve()):
            raise ValueError("refused: operational runtime")
        if self.install.resolve() == live.resolve():
            raise ValueError("refused: live installation")
        if os.environ.get("SOLAR_APP_TEST_PORT") == "9000":
            raise ValueError("refused: port 9000")

    # -- setup ----------------------------------------------------------------

    def setup(self) -> None:
        self.assert_safe()
        for d in (self.install, self.workspace / "sun", self.workspace / ".solar",
                  self.runtime / "system", self.logs, self.agent_dir,
                  self.base / "home" / ".cache"):
            d.mkdir(parents=True, exist_ok=True)
        shutil.copytree(CORE, self.install / "core",
                        ignore=shutil.ignore_patterns(".venv", "__pycache__",
                                                      "node_modules", "tests", ".git"))
        (self.workspace / ".solar" / "settings.json").write_text(json.dumps(dict(
            layout="solar-client-v1.2", core_source="global")), encoding="utf-8")
        # The tick's whole environment: production injects only SOLAR_WORKSPACE and
        # SOLAR_ROOT into the plist; the rest comes from this workspace `.env`
        # (sourced by run_orchestrator.sh with set -a). No port-bound feature: the
        # feature set is async-tasks only, so nothing can ever reach port 9000.
        env_lines = [
            f'SOLAR_ROOT="{self.install}"',
            f'SOLAR_WORKSPACE="{self.workspace}"',
            f'SOLAR_RUNTIME_ROOT="{self.runtime}"',
            f'SOLAR_APP_DATA="{self.base / "app"}"',
            f'SOLAR_SYSTEM_RUNTIME_DIR="{self.runtime / "system"}"',
            'SOLAR_SYSTEM_FEATURES="async-tasks"',
            f'SOLAR_SYSTEM_LAUNCHD_LABEL="{self.label}"',
            f'SOLAR_SYSTEM_LAUNCHD_START_INTERVAL="{TICK_SECONDS}"',
            f'SOLAR_SYSTEM_STDOUT_PATH="{self.logs / "agent-stdout.log"}"',
            f'SOLAR_SYSTEM_STDERR_PATH="{self.logs / "agent-stderr.log"}"',
            f'SOLAR_SYSTEM_LOCK_DIR="{self.base / "tick-lock"}"',
            f'HOME="{self.base / "home"}"',
            f'TMPDIR="{self.base}"',
            f'XDG_CACHE_HOME="{self.base / "home" / ".cache"}"',
        ]
        (self.workspace / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        # a workspace owner for the temporary runtime (the same claim production uses)
        from runtime_owner import claim_test_owner
        claim_test_owner(self.runtime, self.workspace, "ws-launchd-evidence",
                         monkeypatch=self._env)
        # the same base the state conftest builds: schema upgraded, format sqlite
        import solar_state
        with solar_state.cutover(self.runtime) as cut:
            cut.upgrade_schema()
            cut.set_format(solar_state.FORMAT_SQLITE)
        # The standard guard still protects any client/cutover path. Only this
        # harness's explicit bootstrap/bootout calls use real launchctl.
        double = self.base / "launchctl-double"
        double.write_text("#!/bin/sh\nexit 1\n")
        double.chmod(0o755)
        guarded = dict(self.env(), SOLAR_CLIENT_LAUNCHCTL=str(double),
                       SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="none")
        subprocess.run(["bash", "-c", 'source "$1"; solar_test_guard --services',
                        "_", str(CORE / "tests/support/shell_runtime_guard.sh")],
                       env=guarded, check=True, capture_output=True, text=True, timeout=30)
        self.record("environment", host=platform.platform(), uid=os.getuid(),
                    account=os.environ.get("USER"), domain=_launchctl_domain(),
                    install=str(self.install), workspace=str(self.workspace), runtime=str(self.runtime))
        # deterministic local executor task runner: a planet script the local
        # executor allowlist accepts (planets/<p>/skills/<s>/scripts/**)
        script = self.workspace / "planets" / "louis" / "skills" / "sync" / "scripts" / "run.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        # exec avoids an unrecorded shell/sleep descendant. The task waits on a
        # gate, so it is provably still running when the replacement reconciles.
        worker = self.base / "local_work.py"
        worker.write_text(
            "import json, os, pathlib, subprocess, sys, time\n"
            "task, folder = sys.argv[1], pathlib.Path(sys.argv[2])\n"
            "started = subprocess.check_output(['ps', '-p', str(os.getpid()), '-o', 'lstart='], text=True).strip()\n"
            "started = ' '.join(started.split())\n"
            "def emit(event):\n"
            "    row = dict(event=event, task=task, t=time.time(), pid=os.getpid(), started=started)\n"
            "    fd = os.open(folder/'exec.jsonl', os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)\n"
            "    try: os.write(fd, (json.dumps(row)+'\\n').encode())\n"
            "    finally: os.close(fd)\n"
            "emit('start')\n"
            "deadline = time.monotonic() + 180\n"
            "while not (folder / ('release-' + task)).exists():\n"
            "    if time.monotonic() > deadline: raise SystemExit(2)\n"
            "    time.sleep(0.05)\n"
            "emit('end')\n", encoding="utf-8")
        import shlex
        script.write_text("#!/bin/bash\nexec " + shlex.join(
            [sys.executable, str(worker)]) + ' "$1" ' + shlex.quote(str(self.logs)) + "\n")
        script.chmod(0o755)
        self.script = script

    def env(self) -> dict:
        """Subprocess env for ticks driven by hand (the launchd agent gets its own
        from the plist + this workspace .env)."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("SOLAR_")}
        env.update(
            HOME=str(self.base / "home"), TMPDIR=str(self.base),
            XDG_CACHE_HOME=str(self.base / "home" / ".cache"),
            SOLAR_ROOT=str(self.install), SOLAR_WORKSPACE=str(self.workspace),
            SOLAR_RUNTIME_ROOT=str(self.runtime), SOLAR_APP_DATA=str(self.base / "app"),
            SOLAR_SYSTEM_RUNTIME_DIR=str(self.runtime / "system"),
            SOLAR_SYSTEM_LAUNCHD_LABEL=self.label,
            SOLAR_SYSTEM_LAUNCHD_START_INTERVAL=str(TICK_SECONDS),
            SOLAR_SYSTEM_FEATURES="async-tasks",
            SOLAR_SYSTEM_STDOUT_PATH=str(self.logs / "agent-stdout.log"),
            SOLAR_SYSTEM_STDERR_PATH=str(self.logs / "agent-stderr.log"),
            SOLAR_SYSTEM_LOCK_DIR=str(self.base / "tick-lock"),
        )
        return env

    def install_agent(self) -> None:
        """Compile the C wrapper into the TEMP entrypoint and bootstrap the agent."""
        env = self.env()
        subprocess.run(["gcc", "-o", str(self.entrypoint),
                        str(SYSTEM / "Solar.c")], check=True, timeout=120)
        self.entrypoint.chmod(0o755)
        rendered = subprocess.run(
            ["bash", str(SYSTEM / "render_launchagent_plist.sh"), str(self.plist)],
            env=env, cwd=str(self.workspace), capture_output=True, text=True,
            check=True, timeout=60)
        assert rendered.returncode == 0, rendered.stderr
        text = self.plist.read_text(encoding="utf-8")
        assert "StartInterval" in text and f"<integer>{TICK_SECONDS}</integer>" in text
        assert "RunAtLoad" in text and "AbandonProcessGroup" in text
        assert self.label in text and FORBIDDEN_LABEL not in text
        assert str(self.install) in text and str(self.workspace) in text
        assert str(self.entrypoint) in text
        document = plistlib.loads(self.plist.read_bytes())
        assert document["StartInterval"] == 60
        assert document["RunAtLoad"] is True and document["AbandonProcessGroup"] is True
        self.record("plist", document=document)
        lc = _launchctl()
        subprocess.run([lc, "bootout", f"{_launchctl_domain()}/{self.label}"],
                       capture_output=True, timeout=30)
        done = subprocess.run([lc, "bootstrap", _launchctl_domain(), str(self.plist)],
                              capture_output=True, text=True, timeout=30)
        self.booted = done.returncode == 0
        assert self.booted, f"bootstrap failed: {done.stderr}"
        self.record("bootstrap", label=self.label, plist=str(self.plist))

    def record(self, event: str, **kw) -> None:
        row = {"event": event, "t": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ",
               time.gmtime()), **kw}
        self.events.append(row)

    # -- task seeding ---------------------------------------------------------

    def seed_task(self, task_id: str) -> None:
        """Queue a deterministic local task in the TEMP runtime. The pytest process
        itself is bound to the temp workspace/runtime for the duration (restored in
        cleanup): session() refuses a runtime it does not own."""
        import solar_state
        self._env.setenv("SOLAR_WORKSPACE", str(self.workspace))
        self._env.setenv("SOLAR_RUNTIME_ROOT", str(self.runtime))
        with solar_state.session(root=self.runtime) as store:
            store.task_create([
                ("title", json.dumps(task_id)),
                ("executor", "local"),
                ("local_command", json.dumps(f"bash planets/louis/skills/sync/scripts/run.sh {task_id}")),
                ("local_timeout", "240"),
            ], "\n# local launchd evidence task\n", status="draft", task_id=task_id)
            store.task_approve(task_id, actor="launchd-evidence")

    def ctx(self):
        """A supervisor_lib context aligned with the COPY the launchd agent serves:
        observe()/stop() verify install_root against where supervisor_lib lives, and
        the agent imports it from the temp install, not from this repository."""
        import supervisor_lib as lib
        context = lib.Context(self.runtime)
        context.install_root = str(self.install)
        return context

    def supervisor_identity(self) -> dict | None:
        import supervisor_lib as lib
        return lib.read_json(self.ctx().identity_file)

    def wait_supervisor_ready(self, timeout: float = 40) -> dict:
        import supervisor_lib as lib
        deadline = time.monotonic() + timeout
        seen: dict = {}
        while time.monotonic() < deadline:
            seen = lib.observe(self.ctx())
            if seen["state"] == "ready":
                ident = self.supervisor_identity() or {}
                self.record("supervisor_ready", pid=ident.get("pid"),
                            started=ident.get("started"))
                if ident.get("pid"):
                    self.started_pids.append((ident["pid"], ident.get("started")))
                return seen
            time.sleep(0.5)
        raise AssertionError(f"supervisor never became ready: {seen}")

    def wait_condition(self, what: str, cond, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return
            time.sleep(0.5)
        raise AssertionError(f"timed out after {timeout}s waiting for {what}")

    # -- teardown -------------------------------------------------------------

    def cleanup(self) -> None:
        # Refusal must also protect teardown after a failed setup.
        try:
            self.assert_safe()
        except ValueError:
            self._env.restore()
            raise
        import supervisor_lib as lib
        problems: list[str] = []
        registered = set(self.started_pids)
        try:
            # Bootstrap can succeed even if its caller loses the response.
            if _plist_label_listed(self.label):
                done = subprocess.run([_launchctl(), "bootout", f"{_launchctl_domain()}/{self.label}"],
                                      capture_output=True, text=True, timeout=30)
                if done.returncode != 0:
                    problems.append(f"bootout: {done.stderr.strip()}")
            if _plist_label_listed(self.label):
                problems.append("the label is still listed after bootout")
            self.record("bootout", label=self.label, absent=not _plist_label_listed(self.label))
            for path in (self.ctx().identity_file, self.ctx().candidate_file):
                item = lib.read_json(path) or {}
                if item.get("pid") and item.get("started"):
                    registered.add((item["pid"], item["started"]))
            children = lib.read_json(self.ctx().children_file) or {}
            for item in children.get("executions", []):
                if item.get("pid") and item.get("started"):
                    registered.add((item["pid"], item["started"]))
            for item in _exec_events(self):
                registered.add((item["pid"], item["started"]))
                (self.logs / ("release-" + item["task"])).touch()
            code, state = lib.stop(self.ctx(), timeout=20, requested_by="launchd-evidence-cleanup")
            self.record("drain", code=code, state=state.get("state"))
        except Exception as exc:
            problems.append(f"cleanup observation/drain: {exc}")
        finally:
            # Even failure during setup is covered. Never signal an unverified pid.
            for pid, started in registered:
                _kill_by_identity(pid, started, sig=signal.SIGKILL)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and any(
                    lib.matches(pid, started)[0] == "alive" for pid, started in registered):
                time.sleep(0.1)
            survivors = [(pid, started) for pid, started in registered
                         if lib.matches(pid, started)[0] not in ("gone", "reused")]
            table = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                                   text=True, timeout=10)
            leftovers = [line for line in table.stdout.splitlines()
                         if str(self.base) in line]
            if table.returncode != 0 or leftovers:
                problems.append(f"temporary runtime process check failed: {table.returncode}, {leftovers}")
            # Preserve runtime evidence before deleting it, including real tick output.
            for path in (self.logs / "exec.jsonl", self.logs / "agent-stdout.log",
                         self.logs / "agent-stderr.log", self.ctx().support / "supervisor.log"):
                if path.exists():
                    self.record("log", name=path.name, content=path.read_text(errors="replace"))
            if survivors:
                problems.append(f"unverified or surviving processes: {survivors}")
            if not survivors and not leftovers and table.returncode == 0:
                for path in (self.base, self.agent_dir):
                    try:
                        if path.exists():
                            shutil.rmtree(path)
                    except OSError as exc:
                        problems.append(f"remove {path}: {exc}")
                if self.base.exists() or self.agent_dir.exists():
                    problems.append("temporary runtime or plist files remain")
            self.record("cleanup", problems=problems, registered=sorted(registered),
                        runtime_absent=not self.base.exists(), plist_absent=not self.agent_dir.exists())
            self._dump_evidence()
            self._env.restore()
        assert not problems, "; ".join(problems)

    def _dump_evidence(self) -> None:
        out_dir = Path("/private/tmp") / "solar-pr4-results"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"launchd-evidence-{self.label}.json").write_text(
                json.dumps(self.events, indent=1), encoding="utf-8")
        except OSError:
            pass


RIG: LaunchdRig | None = None


@pytest.fixture(scope="module")
def rig():
    global RIG
    if not sys.platform.startswith("darwin"):
        pytest.skip("launchd evidence is macOS only")
    if os.environ.get("SOLAR_TEST_LAUNCHD") != "1":
        pytest.skip("opt-in only: set SOLAR_TEST_LAUNCHD=1")
    if not Path(_launchctl()).exists():
        pytest.skip("launchctl not available")
    # the production label is never touched: we only assert OUR label is private
    RIG = LaunchdRig()
    try:
        RIG.setup()
        RIG.install_agent()
        yield RIG
    finally:
        try:
            RIG.cleanup()
        finally:
            RIG = None


def _exec_events(rig: LaunchdRig) -> list[dict]:
    path = rig.logs / "exec.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _tick_returns_while_supervisor_stays_alive(rig: LaunchdRig):
    """(a) RunAtLoad fires the tick; ensure answers within its handshake budget and the
    supervisor process keeps running with the same identity."""
    seen = rig.wait_supervisor_ready()
    assert seen["state"] == "ready"
    ident = rig.supervisor_identity() or {}
    assert ident.get("pid") and ident.get("started")
    # Observe the actual launchd tick ending, rather than substitute a manual
    # subprocess for the lifecycle being validated.
    def tick_ended():
        output = rig.logs / "agent-stdout.log"
        job = subprocess.run([_launchctl(), "print", f"{_launchctl_domain()}/{rig.label}"],
                             capture_output=True, text=True, timeout=10)
        return (job.returncode == 0 and "state = running" not in job.stdout
                and output.exists() and "Solar system tick completed" in output.read_text())
    rig.wait_condition("the real launchd tick to end", tick_ended, 15)
    import supervisor_lib as lib
    assert lib.matches(ident["pid"], ident["started"])[0] == "alive"
    rig.record("tick_returned", pid=ident["pid"], started=ident["started"])


def _only_supervisor_killed_recovers_within_75s(rig: LaunchdRig):
    """(b) Terminate ONLY the resident supervisor (pid+start verified). The next launchd
    tick (StartInterval 60) recovers it: a new identity appears, reconciliation runs and
    the queued local task is dispatched exactly once."""
    ident = rig.supervisor_identity() or {}
    assert ident.get("pid") and ident.get("started")
    t0 = time.monotonic()
    rig.record("kill_supervisor", pid=ident.get("pid"), started=ident.get("started"))
    assert _kill_by_identity(ident["pid"], ident["started"], sig=9)
    time.sleep(1.0)
    import supervisor_lib as lib
    assert lib.matches(ident["pid"], ident["started"])[0] != "alive"
    # seed while the supervisor is dead: nobody else can dispatch this task
    rig.seed_task("launchd-recovery-1")

    def recovered() -> bool:
        now = rig.supervisor_identity() or {}
        return bool(now.get("pid") and now["pid"] != ident["pid"]
                    and lib.matches(now["pid"], now.get("started"))[0] == "alive"
                    and lib.observe(rig.ctx())["state"] == "ready")
    rig.wait_condition("a new ready supervisor within 75s", recovered, RECOVERY_BUDGET)
    elapsed = time.monotonic() - t0
    rig.record("recovered", seconds=round(elapsed, 1),
               budget=RECOVERY_BUDGET, within_budget=elapsed <= RECOVERY_BUDGET)
    assert elapsed <= RECOVERY_BUDGET
    new_ident = rig.supervisor_identity() or {}
    rig.started_pids.append((new_ident["pid"], new_ident.get("started")))

    def dispatched() -> bool:
        return any(e["event"] == "start" and e["task"] == "launchd-recovery-1"
                   for e in _exec_events(rig))
    rig.wait_condition("the recovered supervisor dispatches the task", dispatched, 90)

    def ended() -> bool:
        return any(e["event"] == "end" and e["task"] == "launchd-recovery-1"
                   for e in _exec_events(rig))
    (rig.logs / "release-launchd-recovery-1").touch()
    rig.wait_condition("the task ends", ended, 30)
    starts = [e for e in _exec_events(rig)
              if e["event"] == "start" and e["task"] == "launchd-recovery-1"]
    assert len(starts) == 1, f"double dispatch: {starts}"
    rig.record("single_dispatch", starts=len(starts), ends=1)


def _running_executions_are_not_duplicated(rig: LaunchdRig):
    """(c) An execution that is already running when the supervisor is replaced is not
    started a second time: the replacement adopts or leaves it, never re-dispatches."""
    rig.seed_task("launchd-longrun-1")
    ident = rig.supervisor_identity() or {}

    def running() -> bool:
        return any(e["event"] == "start" and e["task"] == "launchd-longrun-1"
                   for e in _exec_events(rig))
    rig.wait_condition("the long task started", running, 90)
    starts_before = [e for e in _exec_events(rig)
                     if e["event"] == "start" and e["task"] == "launchd-longrun-1"]
    assert len(starts_before) == 1
    assert not any(e["event"] == "end" and e["task"] == "launchd-longrun-1" for e in _exec_events(rig))
    rig.record("kill_supervisor_midrun", pid=ident.get("pid"), started=ident.get("started"))
    t0 = time.monotonic()
    assert _kill_by_identity(ident["pid"], ident.get("started"), sig=9)
    import supervisor_lib as lib
    def adopted():
        now = rig.supervisor_identity() or {}
        return (now.get("pid") != ident["pid"] and now.get("reconciled")
                and lib.observe(rig.ctx())["state"] == "ready"
                and any(e.get("task_id") == "launchd-longrun-1" and e.get("adopted")
                        for e in now.get("children", [])))
    rig.wait_condition("replacement to reconcile and adopt the still-running execution", adopted, RECOVERY_BUDGET)
    elapsed = time.monotonic() - t0
    assert elapsed <= RECOVERY_BUDGET
    rig.record("adopted_live_execution", seconds=elapsed, identity=rig.supervisor_identity())
    assert not any(e["event"] == "end" and e["task"] == "launchd-longrun-1" for e in _exec_events(rig))
    (rig.logs / "release-launchd-longrun-1").touch()
    rig.wait_condition("the task ended", lambda: any(
        e["event"] == "end" and e["task"] == "launchd-longrun-1" for e in _exec_events(rig)), 30)
    def persisted():
        with __import__("solar_state").session(rig.runtime) as store:
            return all(store.task_status(task) == "completed" for task in
                       ("launchd-recovery-1", "launchd-longrun-1"))
    rig.wait_condition("both results persisted", persisted, 30)
    assert all(len([e for e in _exec_events(rig) if e["event"] == "start" and e["task"] == task]) == 1
               for task in ("launchd-recovery-1", "launchd-longrun-1"))
    rig.record("no_duplicate", execution_events=_exec_events(rig))


def test_real_launchd_lifecycle(rig: LaunchdRig):
    _tick_returns_while_supervisor_stays_alive(rig)
    _only_supervisor_killed_recovers_within_75s(rig)
    _running_executions_are_not_duplicated(rig)
