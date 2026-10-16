"""The update sequence: maintenance -> drain -> stop -> apply/backup/cutover -> restart -> release.

Every test runs the real scripts (client_update.sh, client_update_staged.sh, the cutover
helper of solar-state) against a temporary install, workspace and runtime. Services, the
LaunchAgent and the async work are doubles that write their steps into the same event log as
the update, so the order is read from one file. Nothing here touches port 9000, a LaunchAgent,
a real workspace or runtime, or the machine's launchctl (the guard of test-isolation.md runs
first, with --services).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[3]
SCRIPTS = CORE / "skills" / "solar-client" / "scripts"
GUARD = CORE / "tests" / "support" / "shell_runtime_guard.sh"
sys.path.insert(0, str(CORE / "skills" / "solar-state" / "scripts"))
sys.path.insert(0, str(CORE / "tests" / "support"))

import solar_state  # noqa: E402
from dead_process import dead_pid  # noqa: E402
from runtime_owner import claim_test_owner  # noqa: E402

V6_TABLES = ("reservation_resources", "reservation_scopes", "execution_reservations",
             "task_authorizations", "claim_waits", "async_policy")
WS_ID = "ws-sequence"


def sh(path: Path, body: str) -> str:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


class Rig:
    """An install (git, tags v0.0.1 and v0.0.2), a workspace, a runtime and the doubles."""

    def __init__(self, tmp: Path, monkeypatch):
        self.tmp = tmp
        self.install = tmp / "install"
        self.ws = tmp / "ws"
        self.rt = tmp / "runtime"
        self.events = tmp / "events.jsonl"
        self.busy = tmp / "busy"
        self.monkeypatch = monkeypatch
        shutil.copytree(CORE, self.install / "core", ignore=shutil.ignore_patterns(
            ".venv", "__pycache__", "node_modules", "tests"))
        for number, marker in ((1, "OLD"), (2, "NEW")):
            (self.install / "core" / ".marker").write_text(marker + "\n")
            if number == 1:
                self.git("init", "-q")
                self.git("config", "user.email", "t@t")
                self.git("config", "user.name", "T")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", f"v{number}")
            self.git("tag", f"v0.0.{number}")
        self.git("checkout", "-q", "v0.0.1")
        (self.ws / "sun").mkdir(parents=True)
        (self.ws / ".solar").mkdir()
        (self.ws / ".solar" / "settings.json").write_text(json.dumps(dict(
            layout="solar-client-v1.2", core_version="v0.0.1", core_commit="unknown",
            core_source="global", workspace_id=WS_ID)))
        self.rt.mkdir()
        self.events.write_text("")
        self.busy.write_text("old executions\n")
        barrier = '"$([ -f %s ] && echo true || echo false)"' % (self.rt / "maintenance.json")

        def step(name):
            return (f'printf \'{{"event":"{name}","barrier":%s}}\\n\' {barrier} >>{self.events}\n')

        self.doubles = dict(
            SOLAR_CLIENT_LAUNCHCTL=sh(tmp / "launchctl", (
                f'case "$1" in print) exit 0 ;; bootout) {step("launchctl-bootout")};; '
                f'bootstrap) {step("launchctl-bootstrap")};; esac\nexit 0\n')),
            SOLAR_CLIENT_HOST_STOP_SCRIPT=sh(tmp / "host-stop.sh", step("host-stop")),
            SOLAR_CLIENT_HOST_START_SCRIPT=sh(tmp / "host-start.sh", step("host-start")),
            SOLAR_CLIENT_GATEWAY_STOP_SCRIPT=sh(tmp / "gateway-stop.sh", step("gateway-stop")),
            SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT=sh(tmp / "gateway-setup.sh", step("gateway-restart")),
            SOLAR_CLIENT_SUPERVISOR_STOP_SCRIPT=sh(tmp / "supervisor-stop.sh",
                                                   step("supervisor-drain") + f"rm -f {self.busy}\n"),
        )

    # -- helpers -------------------------------------------------------------

    def git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.install), *args], capture_output=True,
                              text=True, check=True).stdout.strip()

    def env(self, **extra) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("SOLAR_")}
        env.update(
            HOME=str(self.tmp / "home"), TMPDIR=str(self.tmp), SOLAR_ROOT=str(self.install), SOLAR_WORKSPACE=str(self.ws),
            SOLAR_RUNTIME_ROOT=str(self.rt), SOLAR_APP_DATA=str(self.tmp / "app"),
            SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE=str(self.install),
            SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host,async-supervisor",
            SOLAR_CLIENT_UPDATE_EVENTS_FILE=str(self.events),
            SOLAR_CLIENT_ASYNC_BUSY_COMMAND=f"test -f {self.busy}",
            SOLAR_CLIENT_DRAIN_POLL="0.1", SOLAR_CLIENT_DRAIN_TIMEOUT="20",
            SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE="ok", **self.doubles)
        env.update(extra)
        return env

    def guard(self, env: dict) -> None:
        done = subprocess.run(["bash", "-c", 'source "$1"; solar_test_guard --services; echo reached', "_", str(GUARD)],
                              env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0 and "reached" in done.stdout, done.stderr

    def update(self, *args, env_extra=None, script: Path | None = None) -> subprocess.CompletedProcess:
        env = self.env(**(env_extra or {}))
        self.guard(env)
        entry = script or (self.install / "core" / "skills" / "solar-client" / "scripts" / "client_update.sh")
        return subprocess.run(["bash", str(entry), "--workspace", str(self.ws), *args],
                              env=env, cwd=self.ws, capture_output=True, text=True, timeout=300)

    def names(self) -> list[str]:
        return [json.loads(line)["event"] for line in self.events.read_text().splitlines() if line.strip()]

    def rows(self) -> list[dict]:
        return [json.loads(line) for line in self.events.read_text().splitlines() if line.strip()]

    def runtime_state(self, version: int, tasks: int = 1) -> None:
        """A runtime already on solar-state at schema `version` (5 or 6), with some history."""
        claim_test_owner(self.rt, self.ws, WS_ID, monkeypatch=self.monkeypatch)
        with solar_state.cutover(self.rt) as cut:
            cut.upgrade_schema()
            cut.set_format(solar_state.FORMAT_SQLITE)
        with solar_state.session(self.rt, auto_backup=False) as store:
            for index in range(tasks):
                store.task_create([("title", json.dumps(f"T{index}"))], "\n# T\n", status="draft")
        if version == 5:
            conn = sqlite3.connect(solar_state.db_path(self.rt))
            for table in V6_TABLES:
                conn.execute(f"DROP TABLE {table}")
            conn.execute("PRAGMA user_version = 5")
            conn.commit()
            conn.close()
        (self.rt / "state-migration.json").write_text(json.dumps(dict(stamp=solar_state._stamp(), moved=True)))

    def schema(self) -> int:
        conn = sqlite3.connect(solar_state.db_path(self.rt))
        try:
            return solar_state._schema_version(conn)
        finally:
            conn.close()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def marker(self) -> str:
        return (self.install / "core" / ".marker").read_text().strip()

    def barrier(self) -> dict | None:
        path = self.rt / "maintenance.json"
        return json.loads(path.read_text()) if path.exists() else None


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.delenv("SOLAR_RUNTIME_ROOT", raising=False)
    return Rig(tmp_path, monkeypatch)


def subsequence(names: list[str], expected: list[str]) -> bool:
    it = iter(names)
    return all(any(name == wanted for name in it) for wanted in expected)


FULL = ["maintenance", "launchctl-bootout", "ticks-paused", "drain-start", "supervisor-drain", "drain-done", "host-stop", "gateway-stop",
        "services-stopped", "cutover-lock", "quiet-verified", "backup", "apply-start", "apply-done",
        "migrated-and-validated", "cutover-done", "restart-start", "gateway-restart", "host-start",
        "readiness-check", "readiness-ok", "launchctl-bootstrap", "release"]


# --------------------------------------------------------------------------
# the order
# --------------------------------------------------------------------------

def test_the_whole_sequence_runs_in_order_with_an_old_supervisor_and_schema(rig):
    rig.runtime_state(5, tasks=3)
    old_head = rig.head()
    done = rig.update("--ref", "v0.0.2", "--yes")
    assert done.returncode == 0, done.stdout + done.stderr
    names = rig.names()
    assert names[0] == "maintenance" and "ticks-paused" in names
    assert subsequence(names, FULL), names
    assert names.index("ticks-paused") < names.index("drain-start")
    # the barrier was held while every service stopped and started, and gone at the end
    held = {row["event"]: row["barrier"] for row in rig.rows() if "barrier" in row}
    assert all(held[name] for name in ("host-stop", "gateway-stop", "host-start", "gateway-restart",
                                       "launchctl-bootout", "launchctl-bootstrap"))
    assert rig.barrier() is None
    # the code moved only after the drain and the stops, together with the schema
    assert rig.head() != old_head and rig.head() == rig.git("rev-parse", "v0.0.2") and rig.marker() == "NEW"
    assert rig.schema() == solar_state.SCHEMA_VERSION == 6
    assert list((rig.rt / "state-backups" / "pre-update").glob("state-v5-pre-update-*.sqlite"))
    assert list((rig.rt / "state-backups" / "pre-migration").glob("state-v5-to-v6-*.sqlite"))
    with solar_state.session(rig.rt, auto_backup=False) as store:
        assert len(store.task_list()) == 3 and store.async_policy()["global_capacity"] == 1
    marker = json.loads((rig.rt / "state-cutover.json").read_text())
    assert marker["schema_version"] == 6 and marker["code_version"] == "v0.0.2"
    assert not list(rig.tmp.glob("solar-update-staging.*"))               # released: the staging copy is gone


def test_the_first_installation_runs_the_staged_entrypoint_with_explicit_paths(rig, tmp_path):
    rig.runtime_state(5)
    staging = tmp_path / "prepared"
    subprocess.run(["git", "clone", "-q", "--no-local", "--branch", "v0.0.2", str(rig.install), str(staging)], check=True)
    staged = staging / "core" / "skills" / "solar-client" / "scripts" / "client_update_staged.sh"
    env = rig.env()
    rig.guard(env)
    missing = subprocess.run(["bash", str(staged), "--workspace", str(rig.ws)], env=env, capture_output=True, text=True)
    assert missing.returncode == 2 and "--install-root is required" in missing.stderr      # never guesses paths
    assert rig.marker() == "OLD"
    done = subprocess.run(["bash", str(staged), "--install-root", str(rig.install), "--workspace", str(rig.ws),
                           "--runtime-root", str(rig.rt), "--stage-root", str(staging), "--mode", "git",
                           "--target", "v0.0.2"], env=env, cwd=rig.ws, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert subsequence(rig.names(), FULL)
    assert rig.marker() == "NEW" and rig.schema() == 6 and rig.barrier() is None
    assert staging.exists()            # a tree the person prepared is theirs


def test_a_bundle_install_follows_the_same_sequence(rig):
    shutil.rmtree(rig.install / ".git")
    rig.runtime_state(5)
    done = rig.update("--bundle", "--from-dev", env_extra=dict(SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE=str(rig.install)))
    assert done.returncode == 0, done.stdout + done.stderr
    assert subsequence(rig.names(), FULL)
    assert rig.schema() == 6 and rig.barrier() is None


def test_the_sync_path_takes_the_same_barrier(rig):
    """solar client sync runs the cutover with the code already in place: same barrier and order."""
    rig.runtime_state(5)
    env = rig.env()
    rig.guard(env)
    done = subprocess.run(
        ["bash", "-c", 'source "$1"; solar_client_state_cutover "$2" auto', "_",
         str(SCRIPTS / "client_lib.sh"), str(rig.install)], env=env, cwd=rig.ws, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    names = rig.names()
    assert subsequence(names, ["maintenance", "launchctl-bootout", "drain-start", "supervisor-drain", "drain-done",
                               "host-stop", "gateway-stop", "cutover-lock", "migrated-and-validated",
                               "cutover-done", "host-start", "readiness-ok", "launchctl-bootstrap", "release"])
    assert rig.schema() == 6 and rig.barrier() is None


# --------------------------------------------------------------------------
# failures keep everything stopped and the barrier held
# --------------------------------------------------------------------------

def test_a_drain_that_times_out_replaces_nothing_and_a_resume_finishes_it(rig):
    rig.runtime_state(5)
    no_supervisor = dict(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host", SOLAR_CLIENT_DRAIN_TIMEOUT="1")
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=no_supervisor)
    assert failed.returncode != 0 and "still running after 1s" in failed.stderr
    names = rig.names()
    assert "drain-timeout" in names and "host-stop" not in names and "apply-start" not in names
    assert rig.marker() == "OLD" and rig.schema() == 5                    # nothing replaced, nothing migrated
    assert rig.barrier()["phase"] == "ticks-paused" and "launchctl-bootstrap" not in names
    assert len(list(rig.tmp.glob("solar-update-staging.*"))) == 1          # kept: the resume needs it
    # while the barrier is held no claim starts, and a second update refuses to start
    again = rig.update("--ref", "v0.0.2", "--yes", env_extra=no_supervisor)
    assert again.returncode != 0 and "--resume" in again.stderr and rig.marker() == "OLD"
    rig.busy.unlink()                                                      # the old work finished
    resumed = rig.update("--resume", env_extra=no_supervisor)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert subsequence(rig.names(), ["resume", "drain-done", "host-stop", "apply-done", "cutover-done",
                                     "readiness-ok", "launchctl-bootstrap", "release"])
    assert rig.marker() == "NEW" and rig.schema() == 6 and rig.barrier() is None
    assert not list(rig.tmp.glob("solar-update-staging.*"))


def test_a_supervisor_that_cannot_be_drained_stops_the_update_before_it_changes_anything(rig):
    rig.runtime_state(5)
    missing = rig.tmp / "no-such-stop.sh"
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(SOLAR_CLIENT_SUPERVISOR_STOP_SCRIPT=str(missing)))
    assert failed.returncode != 0 and "no way to drain it" in failed.stderr
    assert "drain-refused" in rig.names() and "host-stop" not in rig.names()
    assert rig.marker() == "OLD" and rig.schema() == 5 and rig.barrier()["phase"] == "ticks-paused"


def test_a_supervisor_whose_drain_fails_is_not_killed_or_retried(rig):
    rig.runtime_state(5)
    broken = sh(rig.tmp / "broken-stop.sh", 'echo "pending: 1 execution" >&2\nexit 3\n')
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(SOLAR_CLIENT_SUPERVISOR_STOP_SCRIPT=broken))
    assert failed.returncode != 0 and "did not drain" in failed.stderr
    assert "drain-timeout" in rig.names() and "host-stop" not in rig.names() and rig.marker() == "OLD"


def test_a_migration_that_is_refused_keeps_the_services_stopped(rig):
    rig.runtime_state(5)
    conn = sqlite3.connect(solar_state.db_path(rig.rt))
    conn.execute(f"PRAGMA user_version = {solar_state.SCHEMA_VERSION + 1}")      # a base from the future
    conn.commit()
    conn.close()
    failed = rig.update("--ref", "v0.0.2", "--yes")
    assert failed.returncode != 0 and "newer than the target code" in failed.stderr
    names = rig.names()
    assert "cutover-failed" in names and "host-start" not in names and "launchctl-bootstrap" not in names
    assert "apply-start" not in names and rig.marker() == "OLD"               # the code was not even replaced
    assert rig.barrier()["phase"] == "cutover-started"
    assert not (rig.rt / "state-cutover.json").exists()


def test_a_crash_between_the_code_and_the_schema_is_resumed_not_repeated(rig, tmp_path):
    rig.runtime_state(5, tasks=2)
    wrapper = tmp_path / "cutover_wrapper.py"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        f"import os, sys\nsys.path.insert(0, {str(CORE / 'skills' / 'solar-state' / 'scripts')!r})\n"
        "import solar_state_cutover as c\nreal = c.migrate\n"
        "def migrate(*a, **k):\n    if os.environ.get('CUTOVER_FAIL_AT'):\n        k['_fail_at'] = os.environ['CUTOVER_FAIL_AT']\n"
        "    return real(*a, **k)\nc.migrate = migrate\nraise SystemExit(c._cli(sys.argv[1:]))\n", encoding="utf-8")
    wrapper.chmod(0o755)
    base = dict(SOLAR_CLIENT_CUTOVER_SCRIPT=str(wrapper))
    rig.busy.unlink()
    crashed = rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(base, CUTOVER_FAIL_AT="kill:after-apply"))
    assert crashed.returncode != 0
    # the code is new, the schema is still the old one, and nothing may claim or tick meanwhile
    assert rig.marker() == "NEW" and rig.schema() == 5
    assert rig.barrier()["phase"] == "cutover-started" and "host-start" not in rig.names()
    ensure = subprocess.run(["bash", str(rig.install / "core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh")],
                            env=rig.env(SOLAR_TASK_WORKER_LOCK=str(rig.tmp / "worker.lock")), cwd=rig.ws,
                            capture_output=True, text=True, timeout=120)
    assert ensure.returncode == 0 and "Maintenance in progress" in ensure.stdout
    with pytest.raises(solar_state.StateUnavailable, match="migration has not run"):
        with solar_state.session(rig.rt, auto_backup=False):
            pass                                                           # new code never meets the old schema
    before = len(list((rig.rt / "state-backups" / "pre-update").glob("*.sqlite")))
    resumed = rig.update("--resume", env_extra=base)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert rig.schema() == 6 and rig.barrier() is None and rig.names()[-1] == "release"
    with solar_state.session(rig.rt, auto_backup=False) as store:
        assert len(store.task_list()) == 2 and store.async_policy()["revision"] == 0
    assert before == 1                                                     # the first backup is the one that counts


def test_a_failed_restart_keeps_the_ticks_paused_and_the_barrier(rig):
    rig.runtime_state(5)
    rig.busy.unlink()
    broken_start = sh(rig.tmp / "host-start-broken.sh", "exit 1\n")
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(SOLAR_CLIENT_HOST_START_SCRIPT=broken_start))
    assert failed.returncode != 0 and "restart or readiness failed" in failed.stderr
    names = rig.names()
    assert "launchctl-bootstrap" not in names and "release" not in names
    assert rig.barrier()["phase"] == "restart-failed"
    assert not (rig.rt / "state-cutover.json").exists()


def test_readiness_must_confirm_the_code_and_the_schema_before_ticks_resume(rig):
    rig.runtime_state(5)
    rig.busy.unlink()
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(SOLAR_CLIENT_READINESS_COMMAND="exit 1"))
    assert failed.returncode != 0
    names = rig.names()
    assert "readiness-failed" in names and "launchctl-bootstrap" not in names and rig.barrier() is not None


# --------------------------------------------------------------------------
# --no-restart and --check
# --------------------------------------------------------------------------

def test_no_restart_leaves_dispatch_suspended_until_an_explicit_resume(rig):
    rig.runtime_state(5)
    rig.busy.unlink()
    done = rig.update("--ref", "v0.0.2", "--yes", "--no-restart")
    assert done.returncode == 0, done.stdout + done.stderr
    names = rig.names()
    assert "cutover-done" in names and "held-no-restart" in names
    assert not {"host-start", "gateway-restart", "launchctl-bootstrap", "release"} & set(names)
    assert rig.barrier()["phase"] == "held-no-restart" and rig.marker() == "NEW" and rig.schema() == 6
    assert "solar client update --resume" in done.stdout
    ensure = subprocess.run(["bash", str(rig.install / "core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh")],
                            env=rig.env(SOLAR_TASK_WORKER_LOCK=str(rig.tmp / "worker.lock")), cwd=rig.ws,
                            capture_output=True, text=True, timeout=120)
    assert "Maintenance in progress" in ensure.stdout
    resumed = rig.update("--resume")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert subsequence(rig.names(), ["held-no-restart", "resume", "host-start", "readiness-ok", "launchctl-bootstrap", "release"])
    assert rig.barrier() is None


def tree_digest(*roots: Path) -> str:
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git/" not in p.as_posix()):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.mark.parametrize("held", [False, True])
def test_check_reads_and_writes_nothing(rig, held):
    rig.runtime_state(5)
    if held:
        rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(SOLAR_CLIENT_DRAIN_TIMEOUT="1",
                                                              SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host"))
        assert rig.barrier() is not None
    before = (tree_digest(rig.install / "core", rig.rt, rig.ws), rig.events.read_text(), rig.head())
    checked = rig.update("--check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    after = (tree_digest(rig.install / "core", rig.rt, rig.ws), rig.events.read_text(), rig.head())
    assert before == after
    assert ("Update in progress: phase=ticks-paused" in checked.stdout) is held


def test_check_does_not_combine_with_resume(rig):
    done = rig.update("--check", "--resume")
    assert done.returncode == 2 and "do not combine" in done.stderr


def test_resume_with_nothing_in_progress_changes_nothing(rig):
    rig.runtime_state(6)
    done = rig.update("--resume")
    assert done.returncode == 0 and "nothing to resume" in done.stdout
    assert rig.barrier() is None and rig.marker() == "OLD"


def test_the_staging_failure_leaves_everything_as_it_was(rig):
    rig.runtime_state(5)
    failed = rig.update("--ref", "v9.9.9", "--yes")
    assert failed.returncode != 0 and "could not be prepared" in failed.stderr
    assert rig.names() == [] and rig.barrier() is None and rig.marker() == "OLD" and rig.schema() == 5


def test_a_tick_started_by_hand_does_nothing_while_the_barrier_is_held(rig):
    orchestrator = rig.install / "core" / "skills" / "solar-system" / "scripts" / "run_orchestrator.sh"
    env = rig.env(SOLAR_SYSTEM_FEATURES="async-tasks,transport-gateway,host", SOLAR_SYSTEM_LOCK_DIR=str(rig.tmp / "tick.lock"))
    (rig.rt / "maintenance.json").write_text(json.dumps(dict(operation="update-x", phase="stopped")))
    held = subprocess.run(["bash", str(orchestrator), "--once"], env=env, cwd=rig.ws, capture_output=True, text=True, timeout=120)
    assert held.returncode == 0, held.stdout + held.stderr
    assert "Skipping tick: an update holds the maintenance barrier" in held.stdout
    assert "Running feature" not in held.stdout and not (rig.rt / "system").exists()
    (rig.rt / "maintenance.json").unlink()
    free = subprocess.run(["bash", str(orchestrator), "--once"], env=dict(env, SOLAR_SYSTEM_FEATURES=""), cwd=rig.ws,
                          capture_output=True, text=True, timeout=120)
    assert "No Solar system features enabled" in free.stdout


def lib(rig, snippet: str, ps_lines: list[str], **extra) -> subprocess.CompletedProcess:
    ps = rig.tmp / "ps.txt"
    ps.write_text("\n".join(ps_lines) + "\n")
    env = rig.env(**extra)
    env.pop("SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE")
    env.pop("SOLAR_CLIENT_ASYNC_BUSY_COMMAND")
    env["SOLAR_CLIENT_PS_OUTPUT_FILE"] = str(ps)
    return subprocess.run(["bash", "-c", f'source "$1"; {snippet}', "_", str(SCRIPTS / "client_lib.sh")],
                          env=env, capture_output=True, text=True, timeout=60)


def test_the_supervisor_is_detected_by_install_not_by_name(rig):
    mine = f"python3 {rig.install}/core/skills/solar-async-tasks/scripts/supervisor.py --runtime {rig.rt}"
    other = "python3 /elsewhere/solar/core/skills/solar-async-tasks/scripts/supervisor.py"
    found = lib(rig, f'solar_client_running_services "{rig.install}"', [mine, other])
    assert found.stdout.split() == ["async-supervisor"]
    assert lib(rig, f'solar_client_running_services "{rig.install}"', [other, "python3 supervisor.py"]).stdout == ""


@pytest.mark.parametrize("line,busy", [
    ("{install}/core/skills/solar-async-tasks/scripts/run_worker.sh --once", True),
    ("python3 {install}/core/skills/solar-async-tasks/scripts/execute_active.py abc router.py", True),
    ("python3 {install}/core/skills/solar-async-tasks/scripts/supervisor.py", True),
    ("bash {install}/core/skills/solar-system/scripts/run_orchestrator.sh --once", True),
    ("bash /elsewhere/core/skills/solar-async-tasks/scripts/run_worker.sh --once", False),
    ("bash {install}/core/skills/solar-client/scripts/client_update.sh --check", False),
])
def test_the_drain_waits_for_this_installs_async_work_only(rig, line, busy):
    done = lib(rig, f'solar_client_async_busy "{rig.install}"', [line.format(install=rig.install)])
    assert (done.returncode == 0) is busy, done.stdout + done.stderr


# --------------------------------------------------------------------------
# one process drives the operation at a time
# --------------------------------------------------------------------------

def test_a_resume_cannot_run_next_to_the_update_that_is_still_driving(rig):
    rig.runtime_state(5)
    env_extra = dict(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host", SOLAR_CLIENT_DRAIN_TIMEOUT="60")
    env = rig.env(**env_extra)
    rig.guard(env)
    entry = rig.install / "core" / "skills" / "solar-client" / "scripts" / "client_update.sh"
    original = subprocess.Popen(["bash", str(entry), "--workspace", str(rig.ws), "--ref", "v0.0.2", "--yes"],
                                env=env, cwd=rig.ws, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 60
        while time.time() < deadline and "drain-start" not in rig.names():
            time.sleep(0.1)
        assert "drain-start" in rig.names(), "the original never reached the drain"
        resumed = rig.update("--resume", env_extra=env_extra)
        assert resumed.returncode != 0 and "another update process is driving" in resumed.stderr
        again = rig.update("--ref", "v0.0.2", "--yes", env_extra=env_extra)
        assert again.returncode != 0
        assert rig.barrier()["phase"] == "ticks-paused"                         # nothing ran twice, nothing was released
        assert not {"host-start", "release", "resume"} & set(rig.names())
        rig.busy.unlink()                                                       # the old work finishes
        out, err = original.communicate(timeout=300)
    finally:
        if original.poll() is None:
            original.kill()
    assert original.returncode == 0, out + err
    names = rig.names()
    assert names.count("host-start") == 1 and names.count("release") == 1 and "resume" not in names
    assert rig.barrier() is None and not (rig.rt / "maintenance.lock").exists()


def test_a_lock_left_by_a_dead_process_is_taken_over_but_an_unverifiable_one_is_respected(rig):
    rig.runtime_state(5)
    no_supervisor = dict(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host", SOLAR_CLIENT_DRAIN_TIMEOUT="1")
    assert rig.update("--ref", "v0.0.2", "--yes", env_extra=no_supervisor).returncode != 0
    rig.busy.unlink()
    lock = rig.rt / "maintenance.lock"
    lock.write_text("{ not json")
    refused = rig.update("--resume", env_extra=no_supervisor)
    assert refused.returncode != 0 and "another update process is driving" in refused.stderr
    assert rig.marker() == "OLD" and rig.barrier() is not None
    lock.write_text(json.dumps(dict(pid=dead_pid(), start="Thu Jan  1 00:00:00 1970")))
    resumed = rig.update("--resume", env_extra=no_supervisor)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert rig.marker() == "NEW" and rig.barrier() is None and not lock.exists()


def _stale_lock_and_guard(rig, guard_owner):
    rig.runtime_state(5)
    no_supervisor = dict(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host", SOLAR_CLIENT_DRAIN_TIMEOUT="1")
    assert rig.update("--ref", "v0.0.2", "--yes", env_extra=no_supervisor).returncode != 0
    rig.busy.unlink()
    lock = rig.rt / "maintenance.lock"
    lock.write_text(json.dumps(dict(pid=dead_pid(), start="Thu Jan  1 00:00:00 1970")))
    (rig.rt / "maintenance.lock.takeover").write_text(json.dumps(guard_owner))
    return no_supervisor


def test_a_takeover_guard_left_by_a_killed_taker_does_not_close_the_lock_for_good(rig):
    env = _stale_lock_and_guard(rig, dict(pid=dead_pid(), start="Thu Jan  1 00:00:00 1970"))
    resumed = rig.update("--resume", env_extra=env)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert rig.marker() == "NEW" and not (rig.rt / "maintenance.lock.takeover").exists()


def test_a_takeover_guard_of_a_live_taker_is_respected(rig):
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        env = _stale_lock_and_guard(rig, dict(pid=holder.pid, start="?"))
        refused = rig.update("--resume", env_extra=env)
        assert refused.returncode != 0 and "another update process is driving" in refused.stderr
        assert (rig.rt / "maintenance.lock.takeover").exists() and rig.marker() == "OLD"
    finally:
        holder.kill()
        holder.wait()


def test_a_lock_written_without_a_verifiable_start_is_not_stolen_from_a_live_owner(rig):
    """The owner's start time could not be read when the lock was written ("?"). A start time
    that reads fine now proves nothing, so a live pid keeps the lock."""
    rig.runtime_state(5)
    no_supervisor = dict(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host", SOLAR_CLIENT_DRAIN_TIMEOUT="1")
    assert rig.update("--ref", "v0.0.2", "--yes", env_extra=no_supervisor).returncode != 0
    rig.busy.unlink()
    lock = rig.rt / "maintenance.lock"
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lock.write_text(json.dumps(dict(pid=holder.pid, start="?")))
        refused = rig.update("--resume", env_extra=no_supervisor)
        assert refused.returncode != 0 and "another update process is driving" in refused.stderr
        assert json.loads(lock.read_text())["pid"] == holder.pid
        assert rig.marker() == "OLD" and rig.barrier() is not None
    finally:
        holder.kill()
        holder.wait()
