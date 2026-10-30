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
import re
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
        """A runtime already on solar-state at schema `version` (5 or 6), with some history.

        The base is built at the current schema and then taken back by undoing what each later
        migration added, newest first: v8 (token evidence and the execution id), v7 (lifecycle
        tables), then v6 (reservations) for a v5 base."""
        claim_test_owner(self.rt, self.ws, WS_ID, monkeypatch=self.monkeypatch)
        with solar_state.cutover(self.rt) as cut:
            cut.upgrade_schema()
            cut.set_format(solar_state.FORMAT_SQLITE)
        with solar_state.session(self.rt, auto_backup=False) as store:
            for index in range(tasks):
                store.task_create([("title", json.dumps(f"T{index}"))], "\n# T\n", status="draft")
        if version < solar_state.SCHEMA_VERSION:
            # The undo below knows schema v8 and nothing newer: a later migration must be undone
            # here too, or the base keeps its objects under an older user_version and collides.
            assert solar_state.SCHEMA_VERSION == 8, "teach runtime_state to undo the newer migrations"
            assert version in (5, 6), f"runtime_state can rebuild schema v5 or v6, not v{version}"
            conn = sqlite3.connect(solar_state.db_path(self.rt))
            for table in ("token_observations", "token_attempts"):
                conn.execute(f"DROP TABLE {table}")
            conn.execute("ALTER TABLE execution_reservations DROP COLUMN execution_id")
            for table in ("execution_groups", "execution_lifecycle", "execution_cleanup_holds"):
                conn.execute(f"DROP TABLE {table}")
            if version == 5:
                for table in V6_TABLES:
                    conn.execute(f"DROP TABLE {table}")
            conn.execute(f"PRAGMA user_version = {version}")
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
    assert rig.schema() == solar_state.SCHEMA_VERSION
    assert list((rig.rt / "state-backups" / "pre-update").glob("state-v5-pre-update-*.sqlite"))
    assert list((rig.rt / "state-backups" / "pre-migration").glob(f"state-v5-to-v{solar_state.SCHEMA_VERSION}-*.sqlite"))
    with solar_state.session(rig.rt, auto_backup=False) as store:
        assert len(store.task_list()) == 3 and store.async_policy()["global_capacity"] == 1
    marker = json.loads((rig.rt / "state-cutover.json").read_text())
    assert marker["schema_version"] == solar_state.SCHEMA_VERSION and marker["code_version"] == "v0.0.2"
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
    assert rig.marker() == "NEW" and rig.schema() == solar_state.SCHEMA_VERSION and rig.barrier() is None
    assert staging.exists()            # a tree the person prepared is theirs


def test_a_bundle_install_follows_the_same_sequence(rig):
    shutil.rmtree(rig.install / ".git")
    rig.runtime_state(5)
    done = rig.update("--bundle", "--from-dev", env_extra=dict(SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE=str(rig.install)))
    assert done.returncode == 0, done.stdout + done.stderr
    assert subsequence(rig.names(), FULL)
    assert rig.schema() == solar_state.SCHEMA_VERSION and rig.barrier() is None


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
    assert rig.schema() == solar_state.SCHEMA_VERSION and rig.barrier() is None


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
    assert rig.marker() == "NEW" and rig.schema() == solar_state.SCHEMA_VERSION and rig.barrier() is None
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
    broken = sh(rig.tmp / "broken-stop.sh", 'echo "pending: 1 execution" >&2\nexit 1\n')
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(SOLAR_CLIENT_SUPERVISOR_STOP_SCRIPT=broken))
    assert failed.returncode != 0 and "did not drain" in failed.stderr
    assert "drain-timeout" in rig.names() and "host-stop" not in rig.names() and rig.marker() == "OLD"


def test_a_supervisor_that_leaves_blocked_executions_stops_the_update_with_its_own_message(rig):
    rig.runtime_state(5)
    broken = sh(rig.tmp / "blocked-stop.sh", 'echo "pending: 1 execution" >&2\nexit 3\n')
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=dict(SOLAR_CLIENT_SUPERVISOR_STOP_SCRIPT=broken))
    assert failed.returncode != 0 and "remain blocked" in failed.stderr and "supervisor did not drain" not in failed.stderr
    assert "drain-blocked" in rig.names() and "host-stop" not in rig.names() and rig.marker() == "OLD"


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
    assert ensure.returncode == 20 and "\"reason\": \"maintenance\"" in ensure.stdout
    with pytest.raises(solar_state.StateUnavailable, match="migration has not run"):
        with solar_state.session(rig.rt, auto_backup=False):
            pass                                                           # new code never meets the old schema
    before = len(list((rig.rt / "state-backups" / "pre-update").glob("*.sqlite")))
    resumed = rig.update("--resume", env_extra=base)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert rig.schema() == solar_state.SCHEMA_VERSION and rig.barrier() is None and rig.names()[-1] == "release"
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
    assert rig.barrier()["phase"] == "held-no-restart" and rig.marker() == "NEW" and rig.schema() == solar_state.SCHEMA_VERSION
    assert "solar client update --resume" in done.stdout
    ensure = subprocess.run(["bash", str(rig.install / "core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh")],
                            env=rig.env(SOLAR_TASK_WORKER_LOCK=str(rig.tmp / "worker.lock")), cwd=rig.ws,
                            capture_output=True, text=True, timeout=120)
    assert ensure.returncode == 20 and "\"reason\": \"maintenance\"" in ensure.stdout
    assert "services left stopped" in done.stdout and "Next: solar client update --resume" in done.stdout
    assert "published to the IDEs" not in done.stdout          # nothing is synced while the barrier is held
    resumed = rig.update("--resume")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert subsequence(rig.names(), ["held-no-restart", "resume", "host-start", "readiness-ok", "launchctl-bootstrap", "release"])
    assert rig.barrier() is None
    assert "Resuming the interrupted update" in resumed.stdout
    # The resume finishes the update the way a plain one does: the workspace is synced to the new version.
    assert "✓ Skills, agents and commands published to the IDEs" in resumed.stdout, resumed.stdout + resumed.stderr
    assert json.loads((rig.ws / ".solar" / "settings.json").read_text())["core_version"] == "v0.0.2"


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


def _stale_lock_and_guard(rig, guard_text=None):
    rig.runtime_state(5)
    no_supervisor = dict(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host", SOLAR_CLIENT_DRAIN_TIMEOUT="1")
    assert rig.update("--ref", "v0.0.2", "--yes", env_extra=no_supervisor).returncode != 0
    rig.busy.unlink()
    lock = rig.rt / "maintenance.lock"
    lock.write_text(json.dumps(dict(pid=dead_pid(), start="Thu Jan  1 00:00:00 1970")))
    if guard_text is not None:
        (rig.rt / "maintenance.lock.takeover").write_text(guard_text)
    return no_supervisor


def test_a_guard_file_left_by_a_killed_taker_does_not_close_the_lock_for_good(rig):
    """The guard is an operating-system file lock: a taker that died holds nothing, whatever
    the file it left behind says."""
    env = _stale_lock_and_guard(rig, json.dumps(dict(pid=dead_pid(), start="?")))
    resumed = rig.update("--resume", env_extra=env)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert rig.marker() == "NEW"


def test_a_takeover_guard_held_by_a_live_taker_is_respected(rig):
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, os, sys, time\n"
         "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX)\n"
         "print('held', flush=True)\n"
         "time.sleep(60)\n", str(rig.rt / "maintenance.lock.takeover")],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        env = _stale_lock_and_guard(rig)
        refused = rig.update("--resume", env_extra=env)
        assert refused.returncode != 0 and "another update process is driving" in refused.stderr
        assert rig.marker() == "OLD"
    finally:
        holder.kill()
        holder.wait()


def test_two_simultaneous_recoverers_of_a_stale_lock_have_one_winner(tmp_path):
    """Both judge the same lock stale at the same moment: one takes it, the other is refused,
    and nobody removes a lock that belongs to the winner."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    lock = runtime / "maintenance.lock"
    script = (
        'source "$LIB"; while [ ! -f "$GO" ]; do :; done; '
        'if solar_client_operation_lock_acquire 2>/dev/null; then echo "won $$"; sleep 4; else echo lost; fi')
    env = dict(os.environ, LIB=str(SCRIPTS / "client_lib.sh"), GO=str(tmp_path / "go"),
               SOLAR_RUNTIME_ROOT=str(runtime))
    for _ in range(5):
        (tmp_path / "go").unlink(missing_ok=True)
        lock.write_text(json.dumps(dict(pid=dead_pid(), start="Thu Jan  1 00:00:00 1970")))
        procs = [subprocess.Popen(["bash", "-c", script], env=env, stdout=subprocess.PIPE, text=True)
                 for _ in range(2)]
        time.sleep(1)
        (tmp_path / "go").write_text("")
        time.sleep(2)
        owner = json.loads(lock.read_text())["pid"]            # still the winner's, mid-sleep
        results = [p.communicate(timeout=30)[0].split() for p in procs]
        winners = [r for r in results if r and r[0] == "won"]
        assert len(winners) == 1 and sorted(r[0] for r in results) == ["lost", "won"], results
        assert str(owner) == winners[0][1]


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


def test_live_capacity_three_supervisor_drains_cutover_and_relaunches_without_duplicates(rig, monkeypatch):
    """Real resident supervisor + deterministic executors; update services stay doubled."""
    import signal
    import threading
    sys.path.insert(0, str(CORE / "tests/skills/solar-async-tasks"))
    sys.path.insert(0, str(CORE / "skills/solar-async-tasks/scripts"))
    from supervisor_support import wait_until
    import supervisor_lib
    from rollout_policy import apply_policy

    rig.runtime_state(solar_state.SCHEMA_VERSION, tasks=0)
    monkeypatch.chdir(rig.ws)
    for key, value in rig.env().items():
        if key.startswith("SOLAR_"):
            monkeypatch.setenv(key, value)
    apply_policy(3)
    double = rig.tmp / "executor-double"
    for sub in ("spec", "gates", "barriers"):
        (double / sub).mkdir(parents=True, exist_ok=True)
    tasks = []
    with solar_state.session(rig.rt) as store:
        for i in range(3):
            task = store.task_create([
                ("title", json.dumps(f"Review {i}")), ("provider", "claude"),
                ("execution_profile", "text_only_review_v1"),
                ("access_policy", json.dumps(dict(version=1, mode="read", scopes=[], resources=[])))],
                "Deterministic update review.", status="queued")
            tasks.append(task)
            (double / "spec" / f"{task}.json").write_text(json.dumps(dict(
                gate="release", hold=0.1 + i * 0.1, barrier=dict(name="three", parties=3))))
    wrapper = rig.tmp / "supervisor-double-provider.py"
    wrapper.write_text(
        "import sys\n" + f"sys.path.insert(0, {str(rig.install / 'core/skills/solar-async-tasks/scripts')!r})\n" +
        "import supervisor, supervisor_lib\n" +
        f"executor = lambda task, token: [sys.executable, {str(CORE / 'tests/skills/solar-async-tasks/executor_double.py')!r}, '--task', task, '--token', token]\n" +
        "raise SystemExit(supervisor.Supervisor(supervisor_lib.Context(), executor=executor, poll=0.1, sweep=0.2).run())\n")
    env = rig.env(DOUBLE_DIR=str(double), SOLAR_CUTOVER_PS_OUTPUT_FILE=str(rig.tmp / "cutover-ps"))
    (rig.tmp / "cutover-ps").write_text("")
    original = subprocess.Popen([sys.executable, str(wrapper)], env=env, cwd=rig.ws,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    original_start = supervisor_lib.process_start(original.pid)
    update_box = {}

    def events():
        path = double / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    try:
        wait_until(lambda: len([e for e in events() if e["event"] == "start"]) == 3, 45)
        extra = dict(SOLAR_CLIENT_SUPERVISOR_STOP_SCRIPT=str(rig.install / "core/skills/solar-async-tasks/scripts/stop_supervisor.sh"),
                     SOLAR_CLIENT_ASYNC_BUSY_COMMAND="exit 1", SOLAR_CLIENT_DRAIN_TIMEOUT="60",
                     SOLAR_CUTOVER_PS_OUTPUT_FILE=str(rig.tmp / "cutover-ps"))
        update = threading.Thread(target=lambda: update_box.setdefault("result", rig.update(
            "--ref", "v0.0.2", "--yes", env_extra=extra)), daemon=True)
        update.start()
        wait_until(lambda: "drain-start" in rig.names(), 60)
        assert original.poll() is None and rig.marker() == "OLD"
        (double / "gates/release").touch()
        update.join(180)
        assert not update.is_alive()
        done = update_box["result"]
        assert done.returncode == 0, done.stdout + done.stderr
        original.wait(timeout=10)
        assert original.returncode == 0 and rig.marker() == "NEW" and rig.barrier() is None
        with solar_state.session(rig.rt) as store:
            assert store.async_policy()["global_capacity"] == 3
            assert all(store.task_status(task) == "completed" for task in tasks)
        # The actual ensure path starts the new code only after cutover released maintenance.
        ensure = rig.install / "core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh"
        started = subprocess.run(["bash", str(ensure)], env=env, cwd=rig.ws,
                                 capture_output=True, text=True, timeout=60)
        assert started.returncode == 0, started.stdout + started.stderr
        identity = supervisor_lib.read_json(supervisor_lib.Context(rig.rt).identity_file)
        assert identity and identity["pid"] != original.pid
        stopped = subprocess.run(["bash", str(rig.install / "core/skills/solar-async-tasks/scripts/stop_supervisor.sh"),
                                  "--drain", "--timeout", "30"], env=env, cwd=rig.ws,
                                 capture_output=True, text=True, timeout=45)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        assert all(len([e for e in events() if e["event"] == "start" and e["task"] == task]) == 1 for task in tasks)
        assert len([e for e in events() if e["event"] == "completed"]) == 3
        names = rig.names()
        assert subsequence(names, ["drain-start", "drain-done", "cutover-lock", "cutover-done", "release"])
    finally:
        # Signals are restricted to recorded pid + process start; never by process name.
        for identity in (dict(pid=original.pid, started=original_start),
                         supervisor_lib.read_json(supervisor_lib.Context(rig.rt).identity_file) or {}):
            if identity.get("started") and supervisor_lib.matches(identity.get("pid"), identity["started"])[0] == "alive":
                os.kill(identity["pid"], signal.SIGTERM)
        (double / "gates/release").touch()
        if original.poll() is None:
            original.wait(timeout=30)


# --------------------------------------------------------------------------
# the short output
# --------------------------------------------------------------------------

def test_the_update_prints_a_short_summary_and_keeps_the_detail_in_a_log(rig):
    rig.runtime_state(5, tasks=3)
    done = rig.update("--ref", "v0.0.2", "--yes", "--no-sync")
    assert done.returncode == 0, done.stdout + done.stderr
    shown = done.stdout.splitlines()
    assert len(shown) <= 14, done.stdout
    for wanted in ("→", "✓ Target version prepared and checked", "✓ Services stopped (console, gateway)",
                   "✓ Runtime migrated", "✓ Services started and verified", "✓ Update complete - v0.0.2"):
        assert any(wanted in line for line in shown), (wanted, done.stdout)
    for noise in ("pid=", "action=kill", "State:", "legacy_children", "SOLAR_ROOT=", "staging", "{", "}"):
        assert noise not in done.stdout, (noise, done.stdout)
    log = Path(next(line for line in shown if line.strip().startswith("Log: ")).split("Log: ")[1])
    assert log.parent == rig.rt / "update-logs" and log.exists()
    text = log.read_text()
    assert "State: migrating the runtime" in text and "State: update verified" in text


def test_verbose_prints_everything_and_writes_no_log(rig):
    rig.runtime_state(5)
    done = rig.update("--ref", "v0.0.2", "--yes", "--no-sync", "--verbose")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "State: migrating the runtime" in done.stdout and "State: update verified" in done.stdout
    assert not (rig.rt / "update-logs").exists()


def test_a_failed_update_shows_the_error_with_its_cause_and_how_to_resume(rig):
    rig.runtime_state(5)
    no_supervisor = dict(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host", SOLAR_CLIENT_DRAIN_TIMEOUT="1")
    failed = rig.update("--ref", "v0.0.2", "--yes", env_extra=no_supervisor)
    assert failed.returncode != 0
    assert "ERROR:" in failed.stderr and "still running after 1s" in failed.stderr
    assert "solar client update --resume" in failed.stdout + failed.stderr
    assert "State: pausing LaunchAgent" in failed.stderr          # the lines before the error come with it


def test_the_log_directory_keeps_the_last_ten_logs_including_the_new_one(rig):
    logs = rig.rt / "update-logs"
    logs.mkdir(parents=True)
    for index in range(14):
        path = logs / f"update-2026010{index % 10}T00000{index}-{index}.log"
        path.write_text("x")
        os.utime(path, (1000 + index, 1000 + index))
    new = logs / "update-new.log"
    subprocess.run(["bash", "-c", f'source "{SCRIPTS}/client_lib.sh"; echo "State: x" | solar_client_update_view "{new}"'],
                   check=True, capture_output=True, text=True)
    left = list(logs.glob("update-*.log"))
    assert len(left) == 10 and new in left and new.read_text() == "State: x\n"
    assert min(p.stat().st_mtime for p in left if p != new) == 1005


def view(text: str, tmp: Path) -> subprocess.CompletedProcess:
    """The short view over `text`, with the log it wrote."""
    return subprocess.run(["bash", "-c", f'source "{SCRIPTS}/client_lib.sh"; solar_client_update_view "{tmp}/v.log"'],
                          input=text, capture_output=True, text=True)


def test_the_view_shows_failures_that_do_not_start_with_error(tmp_path):
    for bad in ("fatal: not a git repository", "error: pathspec 'x' did not match", "/x/y.sh: line 9: nope: command not found",
                "/x/y.sh: line 9: ORIG_ARGS[@]: unbound variable"):
        done = view(f"State: migrating the runtime\nhidden cause line\n{bad}\n", tmp_path)
        assert bad in done.stderr and "hidden cause line" in done.stderr, (bad, done.stderr)
        assert bad not in done.stdout
    for level in ("WARN: something odd", "FAIL: a check"):
        done = view(f"hidden cause line\n{level}\n", tmp_path)
        assert "hidden cause line" in done.stderr and level in done.stderr


def test_the_view_infers_phases_without_inventing_them(tmp_path):
    # Nothing was running: no "services stopped" line; the migration is still reported when the
    # update is verified without any service having been started.
    quiet = view("State: migrating the runtime\nState: update verified; maintenance barrier released\n", tmp_path)
    assert "services stopped" not in quiet.stdout.lower()
    assert quiet.stdout.index("✓ Runtime migrated") < quiet.stdout.index("✓ Services started and verified")
    # A repeated phase does not repeat the services of the first one.
    twice = view("State: stopping console\nState: migrating the runtime\nState: migrating the runtime\n", tmp_path)
    assert twice.stdout.lower().count("services stopped") == 1


def test_the_view_words_the_legacy_subtasks_in_plain_language(tmp_path):
    counted = view("Legacy subtasks without a derived authorization: 15 (15 not executable until approved again). Nothing was backfilled.\n", tmp_path)
    assert "15 older subtasks need approval again before they can run" in counted.stdout
    assert "backfilled" not in counted.stdout and "(15" not in counted.stdout
    odd = view("Legacy subtasks without a derived authorization: many\n", tmp_path)
    assert "Older subtasks need approval" in odd.stdout and "many" not in odd.stdout


def test_a_bare_update_with_no_flags_runs_under_bash_3(rig):
    """`solar client update` with no arguments left the re-launch with an empty array: bash 3.2
    (macOS) aborts on that under set -u."""
    rig.runtime_state(5)
    env = rig.env(SOLAR_STABLE_RELEASE_TAG="v0.0.2")
    rig.guard(env)
    entry = rig.install / "core" / "skills" / "solar-client" / "scripts" / "client_update.sh"
    done = subprocess.run(["bash", str(entry)], env=env, cwd=rig.ws, capture_output=True, text=True, timeout=300)
    assert "unbound variable" not in done.stderr and done.returncode != 127, done.stdout + done.stderr
    assert done.returncode == 0, done.stdout + done.stderr
    assert "✓ Update complete - " in done.stdout


def retag(rig, tag: str, edits: dict[str, str]) -> None:
    """A tag on top of v0.0.2 whose files were rewritten: `edits` maps a path under core/skills/solar-client/scripts to its text."""
    rig.git("checkout", "-q", "v0.0.2")
    for name, text in edits.items():
        (rig.install / "core" / "skills" / "solar-client" / "scripts" / name).write_text(text)
    rig.git("commit", "-q", "-am", tag)
    rig.git("tag", tag)
    rig.git("checkout", "-q", "v0.0.1")


def old_staged_text() -> str:
    """The staged entrypoint as published before the short output: it rejects --verbose and --no-sync."""
    kept = [line for line in (SCRIPTS / "client_update_staged.sh").read_text().splitlines(keepends=True)
            if "--verbose" not in line and "--no-sync" not in line]
    return "".join(kept)


@pytest.mark.parametrize("flags", [("--no-sync",), ("--verbose",), ("--no-sync", "--verbose")])
def test_a_target_that_predates_the_options_is_not_given_them(rig, flags):
    rig.runtime_state(5)
    retag(rig, "v0.0.3", {"client_update_staged.sh": old_staged_text()})
    done = rig.update("--ref", "v0.0.3", "--yes", *flags)
    assert "Unknown option" not in done.stdout + done.stderr
    assert done.returncode == 0, done.stdout + done.stderr


def test_staged_support_is_read_from_the_entrypoint_of_the_target(tmp_path):
    new, old = tmp_path / "new.sh", tmp_path / "old.sh"
    new.write_text("--no-sync) RUN_SYNC=false ;;\n")
    old.write_text("--did-backup) x ;;\n")
    check = lambda script, flag: subprocess.run(["bash", "-c", f'source "{SCRIPTS}/client_lib.sh"; solar_client_staged_supports "{script}" "{flag}"']).returncode
    assert check(new, "--no-sync") == 0 and check(old, "--no-sync") != 0 and check(tmp_path / "missing.sh", "--no-sync") != 0


def test_a_plain_update_syncs_the_workspace_and_a_failing_sync_is_only_a_warning(rig):
    rig.runtime_state(5)
    done = rig.update("--ref", "v0.0.2", "--yes")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "✓ Skills, agents and commands published to the IDEs" in done.stdout
    assert "✓ Doctor:" in done.stdout or "! Doctor:" in done.stdout          # the doctor line is always there
    assert json.loads((rig.ws / ".solar" / "settings.json").read_text())["core_version"] == "v0.0.2"
    # A target whose sync fails: the update is still a success, and says what to run.
    rig.runtime_state(5)
    retag(rig, "v0.0.4", {"client_sync.sh": "#!/usr/bin/env bash\necho boom >&2\nexit 1\n"})
    rig.git("checkout", "-q", "-f", "v0.0.1")
    failed = rig.update("--ref", "v0.0.4", "--yes")
    assert failed.returncode == 0, failed.stdout + failed.stderr
    assert "! Sync failed: run solar client sync in" in failed.stdout


def test_no_sync_applies_to_a_resume_too(rig):
    rig.runtime_state(5)
    rig.busy.unlink()
    assert rig.update("--ref", "v0.0.2", "--yes", "--no-restart", "--no-sync").returncode == 0
    resumed = rig.update("--resume", "--no-sync")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "published to the IDEs" not in resumed.stdout and "Next: solar client sync" in resumed.stdout


def _upgrade_needed(install: Path, workspace: Path) -> bool:
    done = subprocess.run(["bash", "-c", f'source "{SCRIPTS}/client_lib.sh"; solar_client_upgrade_needed "{install}" "{workspace}"'],
                          capture_output=True, text=True)
    return done.returncode == 0


def test_upgrade_is_hinted_only_when_there_is_something_to_upgrade(tmp_path):
    install, ws = tmp_path / "install", tmp_path / "ws"
    (ws / ".solar").mkdir(parents=True)
    install.mkdir()
    (ws / ".solar" / "settings.json").write_text(json.dumps(dict(layout="solar-client-v1.2")))
    assert not _upgrade_needed(install, ws)                       # a clean global install: no hint
    (install / ".cursor").mkdir()
    assert _upgrade_needed(install, ws)                           # IDE artifacts under the install
    (install / ".cursor").rmdir()
    (ws / ".solar" / "core").mkdir()
    assert _upgrade_needed(install, ws)                           # the obsolete .solar/core
    (ws / ".solar" / "core").rmdir()
    (ws / ".solar" / "settings.json").write_text(json.dumps(dict(layout="solar-client-v1.0")))
    assert _upgrade_needed(install, ws)                           # an older layout


def test_the_layout_is_compared_against_one_shared_name():
    out = subprocess.run(["bash", "-c", f'source "{SCRIPTS}/client_lib.sh"; echo "$SOLAR_CLIENT_LAYOUT_CURRENT"'],
                         capture_output=True, text=True).stdout.strip()
    assert out == "solar-client-v1.2"
    assert "(layout $SOLAR_CLIENT_LAYOUT_CURRENT)" in (SCRIPTS / "client_upgrade.sh").read_text()


def test_upgrade_next_steps_do_not_ask_for_the_smoke_or_the_launchagent(tmp_path):
    text = (SCRIPTS / "client_upgrade.sh").read_text()
    assert "smoke-solar-client.sh" not in text.split("Next:")[-1]
    assert "install_launchagent_macos.sh" not in text


def test_the_short_output_with_sync_and_doctor_stays_short(rig):
    rig.runtime_state(5, tasks=3)
    done = rig.update("--ref", "v0.0.2", "--yes")
    assert done.returncode == 0, done.stdout + done.stderr
    shown = done.stdout.splitlines()
    assert "✓ Skills, agents and commands published to the IDEs" in done.stdout
    # Doctor's own OK lines are hidden; only its summary (and any WARN/ERROR line) is shown.
    assert not any(line.startswith("OK:") for line in shown), done.stdout
    assert len(shown) <= 16, done.stdout


def test_a_doctor_warning_does_not_drag_in_the_lines_of_the_sync(tmp_path):
    done = view("State: update verified; maintenance barrier released\nOK: update complete — v1 (abc)\n"
                "Follow-up: sync\nsync noise line\nFollow-up: doctor\nOK: a doctor check\nWARN: settings layout=old\n", tmp_path)
    assert "WARN: settings layout=old" in done.stderr
    assert "sync noise line" not in done.stderr and "a doctor check" not in done.stderr
    assert "Follow-up" not in done.stdout and "Follow-up" not in done.stderr
    # ...while an error of the update itself still brings its own context.
    failed = view("hidden cause\nERROR: the update did not complete\n", tmp_path)
    assert "hidden cause" in failed.stderr


# --------------------------------------------------------------------------
# colors: the Solar Console palette, only on a terminal
# --------------------------------------------------------------------------

APP_CSS = CORE / "skills" / "solar-app" / "assets" / "app.css"
SAMPLE = ("  current=v0.1.0 (abc)\n  target=v0.2.0 (stable release)\nOK: staged and checked: x\nState: stopping console\nState: migrating the runtime\n"
          "Legacy subtasks without a derived authorization: 15 (x)\nState: update verified; x\n"
          "OK: update complete — v1 (abc)\nNext: solar client sync\nERROR: broken\n")


def colored(tmp: Path, **env) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "COLORTERM", "SOLAR_CLIENT_COLOR")}
    base.update({"TERM": "xterm-256color", **env})
    return subprocess.run(["bash", "-c", f'source "{SCRIPTS}/client_lib.sh"; solar_client_update_view "{tmp}/c.log"'],
                          input=SAMPLE, capture_output=True, text=True, env=base)


def console_dark_palette() -> dict[str, str]:
    dark = next(line for line in APP_CSS.read_text().splitlines() if line.startswith(".t-dark{"))
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", dark))


def rgb_of(token: str) -> tuple[int, int, int]:
    hexa = console_dark_palette()[token].lstrip("#")
    return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))


def nearest_256(rgb: tuple[int, int, int]) -> int:
    """The xterm-256 index closest to `rgb`: the 6x6x6 cube (16-231) and the grey ramp (232-255)."""
    levels = (0, 95, 135, 175, 215, 255)
    colors = {16 + 36 * r + 6 * g + b: (levels[r], levels[g], levels[b]) for r in range(6) for g in range(6) for b in range(6)}
    colors.update({232 + n: (8 + 10 * n,) * 3 for n in range(24)})
    return min(colors, key=lambda index: sum((a - b) ** 2 for a, b in zip(colors[index], rgb)))


def run_on_tty(snippet: str, text: str, env: dict, tty_fd: str) -> tuple[str, str]:
    """Run the view with stdout (or stderr) on a real terminal and the other stream on a pipe."""
    pty = pytest.importorskip("pty")
    master, slave = pty.openpty()
    stdout, stderr = (slave, subprocess.PIPE) if tty_fd == "out" else (subprocess.PIPE, slave)
    proc = subprocess.Popen(["bash", "-c", snippet], stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, env=env)
    os.close(slave)                      # the child holds the only other copy: the read below ends with it
    proc.stdin.write(text.encode())
    proc.stdin.close()
    tty_text = b""
    try:
        while True:
            chunk = os.read(master, 4096)
            if not chunk:
                break
            tty_text += chunk
    except OSError:                      # EIO: the child closed its side
        pass
    os.close(master)
    piped = (proc.stdout if tty_fd == "err" else proc.stderr).read().decode()
    proc.wait(timeout=60)
    return tty_text.decode().replace("\r\n", "\n"), piped


def test_there_are_no_colors_when_the_output_is_not_a_terminal(tmp_path):
    done = colored(tmp_path)                       # captured by the test: not a tty
    assert "\x1b" not in done.stdout + done.stderr
    assert "✓ Runtime migrated" in done.stdout


def test_colors_use_the_solar_console_palette(tmp_path):
    done = colored(tmp_path, SOLAR_CLIENT_COLOR="always", COLORTERM="truecolor")

    def rgb(token: str) -> str:
        return ";".join(str(part) for part in rgb_of(token))
    assert f"\x1b[38;2;{rgb('--ok')}m✓\x1b[0m Runtime migrated" in done.stdout          # ✓ in --ok
    header = done.stdout.splitlines()[0]
    assert header.startswith(f"\x1b[38;2;{rgb('--brand')}mSolar\x1b[0m client update")   # only "Solar" in --brand, not bold
    assert f"\x1b[38;2;{rgb('--info')}m" in header                                      # the versions in --info
    assert f"  \x1b[38;2;{rgb('--warn')}m!\x1b[0m 15 older subtasks" in done.stdout          # only the ! in --warn
    assert f"\x1b[38;2;{rgb('--info')}mNext:\x1b[0m solar client sync" in done.stdout   # only "Next:" in --info
    assert f"\x1b[38;2;{rgb('--err')}mERROR: broken\x1b[0m" in done.stderr             # errors in --err, on stderr
    assert "\x1b" not in (tmp_path / "c.log").read_text()                              # the log stays plain


ROLES = {"brand": "--brand", "ok": "--ok", "warn": "--warn", "err": "--err", "muted": "--muted", "info": "--info"}


@pytest.mark.parametrize("role,token", ROLES.items())
def test_each_role_falls_back_to_the_nearest_256_color(role, token):
    env = {k: v for k, v in os.environ.items() if k != "COLORTERM"}
    done = subprocess.run(["bash", "-c", f'source "{SCRIPTS}/client_lib.sh"; solar_client_sgr {role}'],
                          capture_output=True, text=True, env=env)
    assert done.stdout == f"\x1b[38;5;{nearest_256(rgb_of(token))}m"


def test_an_explicit_choice_wins_and_the_environment_decides_the_rest(tmp_path):
    # SOLAR_CLIENT_COLOR is explicit: it wins over NO_COLOR and TERM=dumb, as a flag would.
    assert "\x1b[38;5;72m✓" in colored(tmp_path, SOLAR_CLIENT_COLOR="always").stdout
    assert "\x1b" in colored(tmp_path, SOLAR_CLIENT_COLOR="always", NO_COLOR="1").stdout
    assert "\x1b" in colored(tmp_path, SOLAR_CLIENT_COLOR="always", TERM="dumb").stdout
    assert "\x1b" not in colored(tmp_path, SOLAR_CLIENT_COLOR="never").stdout
    assert "\x1b" not in colored(tmp_path, SOLAR_CLIENT_COLOR="never", COLORTERM="truecolor").stdout


def _view_snippet(tmp: Path) -> str:
    return f'source "{SCRIPTS}/client_lib.sh"; solar_client_update_view "{tmp}/t.log"'


def _clean_env(**env) -> dict:
    base = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "COLORTERM", "SOLAR_CLIENT_COLOR")}
    base.update({"TERM": "xterm-256color", **env})
    return base


def test_on_a_terminal_the_environment_decides(tmp_path):
    on, _ = run_on_tty(_view_snippet(tmp_path), SAMPLE, _clean_env(), "out")
    assert "\x1b[38;5;72m✓" in on
    off, _ = run_on_tty(_view_snippet(tmp_path), SAMPLE, _clean_env(NO_COLOR="1"), "out")
    assert "\x1b" not in off
    dumb, _ = run_on_tty(_view_snippet(tmp_path), SAMPLE, _clean_env(TERM="dumb"), "out")
    assert "\x1b" not in dumb


def test_each_stream_is_colored_by_whether_it_is_a_terminal(tmp_path):
    # stdout on a terminal, stderr captured: the summary has colors, the captured ERROR has none.
    out_tty, err_pipe = run_on_tty(_view_snippet(tmp_path), SAMPLE, _clean_env(), "out")
    assert "\x1b[38;5;72m✓" in out_tty and "ERROR: broken" in err_pipe and "\x1b" not in err_pipe
    # the reverse: stderr on a terminal gets the red ERROR, the captured stdout has no escapes.
    err_tty, out_pipe = run_on_tty(_view_snippet(tmp_path), SAMPLE, _clean_env(), "err")
    assert "\x1b[38;5;203mERROR: broken\x1b[0m" in err_tty and "\x1b" not in out_pipe


def test_the_version_is_still_colored_when_the_complete_line_has_no_dash(tmp_path):
    done = subprocess.run(["bash", "-c", _view_snippet(tmp_path)], input="OK: update complete v1 (abc)\n",
                          capture_output=True, text=True, env=_clean_env(SOLAR_CLIENT_COLOR="always", COLORTERM="truecolor"))
    assert "Update complete - \x1b[38;2;" in done.stdout and "v1\x1b[0m (abc)" in done.stdout
    assert "-  v1" not in done.stdout


def test_launchagent_lines_other_than_ok_are_warnings_in_the_same_pattern(tmp_path):
    for text in ("skipped (solar-system helpers missing under install)", "not installed (optional on this machine)"):
        done = view(f"LaunchAgent: {text}\n", tmp_path)
        assert done.stdout.splitlines()[0] == f"  ! LaunchAgent {text}"
    assert view("LaunchAgent: ok (plist SOLAR_ROOT matches install)\n", tmp_path).stdout.splitlines()[0] == "  ✓ LaunchAgent points to this install"
    # Edge cases of the same pattern: a bare "o" and nothing after the colon are warnings too.
    assert view("LaunchAgent: o\n", tmp_path).stdout.splitlines()[0] == "  ! LaunchAgent o"
    assert view("LaunchAgent: \n", tmp_path).stdout.splitlines()[0] == "  ! LaunchAgent "


def test_resuming_prints_one_plain_line(tmp_path):
    done = subprocess.run(["bash", "-c", _view_snippet(tmp_path)], input="State: resuming update update-1 at phase restarting\n",
                          capture_output=True, text=True, env=_clean_env(SOLAR_CLIENT_COLOR="always"))
    assert done.stdout.splitlines()[0] == "Resuming the interrupted update (update-1 at phase restarting)"
