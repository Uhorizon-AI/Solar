"""Test isolation for the sync path: no test may stop or start a real service.

client_sync.sh ends in solar_client_state_cutover. These tests prove that
(1) with service detection simulated, a full sync neither detects nor signals a
running console, and (2) the opt-in guard (solar_test_guard --services) refuses
a setup that would let the cutover reach the real global install. The guard is
not automatic: see core/docs/test-isolation.md.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[3]
GUARD = CORE / "tests/support/shell_runtime_guard.sh"
SYNC = CORE / "skills/solar-client/scripts/client_sync.sh"
HOST_SERVER = CORE / "skills/solar-app/scripts/host_server.py"


def run_guard(tmp_path, *args, **env):
    """solar_test_guard in a clean environment: temp runtime, launchctl double."""
    double = tmp_path / "launchctl"
    double.write_text("#!/bin/sh\nexit 1\n")
    double.chmod(0o755)
    clean = {k: v for k, v in os.environ.items() if not k.startswith("SOLAR_")}
    clean.update(SOLAR_RUNTIME_ROOT=str(tmp_path / "runtime"), SOLAR_APP_DATA=str(tmp_path / "data"),
                 SOLAR_CLIENT_LAUNCHCTL=str(double), SOLAR_ROOT=str(CORE.parent))
    clean.update({k: v for k, v in env.items() if v is not None})
    for key in [k for k, v in env.items() if v is None]:
        clean.pop(key, None)
    return subprocess.run(["bash", "-c", 'source "$1"; shift; solar_test_guard "$@"; echo reached', "_",
                           str(GUARD), *args], env=clean, capture_output=True, text=True, timeout=30)


# 2. the flag rejects a temp runtime whose effective install is the real global install
def test_services_flag_rejects_the_real_global_install(tmp_path):
    result = run_guard(tmp_path, "--services")
    assert result.returncode == 97 and "reached" not in result.stdout, result.stdout + result.stderr
    assert "real global install" in result.stderr
    assert "does not cover" in result.stderr  # the LaunchAgent caveat is stated


# 3. without the flag nothing changes: the same setup passes
def test_guard_without_the_flag_is_unchanged(tmp_path):
    result = run_guard(tmp_path)
    assert result.returncode == 0 and "reached" in result.stdout, result.stderr


def test_unknown_guard_argument_aborts(tmp_path):
    assert run_guard(tmp_path, "--bogus").returncode == 97


def test_simulated_detection_passes(tmp_path):
    for env in ({"SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE": "none"},
                {"SOLAR_CLIENT_PS_OUTPUT_FILE": str(tmp_path / "ps.txt")}):
        (tmp_path / "ps.txt").write_text("")
        result = run_guard(tmp_path, "--services", **env)
        assert result.returncode == 0 and "reached" in result.stdout, result.stderr


def test_simulated_services_need_their_hooks(tmp_path):
    result = run_guard(tmp_path, "--services", SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="host")
    assert result.returncode == 97 and "SOLAR_CLIENT_HOST_STOP_SCRIPT" in result.stderr
    ok = run_guard(tmp_path, "--services", SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="host",
                   SOLAR_CLIENT_HOST_STOP_SCRIPT="/x/stop", SOLAR_CLIENT_HOST_START_SCRIPT="/x/start")
    assert ok.returncode == 0
    gateway = run_guard(tmp_path, "--services", SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway")
    assert gateway.returncode == 97 and "GATEWAY" in gateway.stderr


def test_global_install_is_compared_on_physical_paths(tmp_path):
    link = tmp_path / "install-link"
    link.symlink_to(CORE.parent)
    # Same install by two spellings: rejected, whether the pin or SOLAR_ROOT is the symlink.
    pinned = run_guard(tmp_path, "--services", SOLAR_ROOT=str(link),
                       SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE=str(CORE.parent))
    assert pinned.returncode == 97, pinned.stderr
    pinned_link = run_guard(tmp_path, "--services", SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE=str(link))
    assert pinned_link.returncode == 97, pinned_link.stderr


def test_a_different_pinned_install_or_no_global_install_passes(tmp_path):
    other = tmp_path / "other-install"
    (other / "core/skills/solar-client/scripts").mkdir(parents=True)
    (other / "core/skills/solar-client/scripts/solar").write_text("#!/bin/sh\n")
    assert run_guard(tmp_path, "--services", SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE=str(other)).returncode == 0
    # An empty pin means "no global install" in this framework.
    assert run_guard(tmp_path, "--services", SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="").returncode == 0


def test_without_solar_root_the_effective_install_is_the_repository(tmp_path):
    result = run_guard(tmp_path, "--services", SOLAR_ROOT=None)
    assert result.returncode == 97, result.stderr


# 1. a sync does not stop or start a (simulated) running console
@pytest.fixture
def sync_env(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    (ws / "sun").mkdir(parents=True)
    (ws / ".solar").mkdir()
    (ws / ".solar/settings.json").write_text('{"core_source":"global"}')
    skill = ws / "planets/demo/skills/analysis"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: analysis\ndescription: Fixture analysis\n---\nInstructions")
    codex = tmp_path / "codex"
    codex.mkdir()
    (codex / "config.toml").write_text("")
    launchctl = tmp_path / "launchctl"
    launchctl.write_text("#!/bin/sh\nexit 1\n")
    launchctl.chmod(0o755)
    log = tmp_path / "service-calls.log"
    for name in ("stop", "start"):
        hook = tmp_path / f"host-{name}.sh"
        hook.write_text(f"#!/bin/sh\necho host-{name} >> '{log}'\n")
        hook.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOLAR_")}
    env.update(SOLAR_ROOT=str(CORE.parent), SOLAR_WORKSPACE=str(ws), SOLAR_APP_DATA=str(tmp_path / "app-data"),
               SOLAR_RUNTIME_ROOT=str(tmp_path / "runtime"), SOLAR_CLIENT_LAUNCHCTL=str(launchctl),
               SOLAR_CLIENT_HOST_STOP_SCRIPT=str(tmp_path / "host-stop.sh"),
               SOLAR_CLIENT_HOST_START_SCRIPT=str(tmp_path / "host-start.sh"),
               CODEX_HOME=str(codex), HOME=str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return ws, env, log


def sync(ws, env, guard_args=("--services",)):
    command = 'source "$1"; solar_test_guard "${@:3}"; bash "$2" --codex-only'
    return subprocess.run(["bash", "-c", command, "_", str(GUARD), str(SYNC), *guard_args], cwd=ws, env=env,
                          capture_output=True, text=True, timeout=60)


def test_sync_with_detection_disabled_never_touches_a_running_console(sync_env, tmp_path):
    ws, env, log = sync_env
    # A process whose command line holds THIS install's host_server.py: what detection would find.
    console = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", str(HOST_SERVER)], start_new_session=True)
    try:
        env["SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE"] = "none"
        result = sync(ws, env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not log.exists(), log.read_text() if log.exists() else ""
        assert console.poll() is None
        assert "stopping console" not in result.stdout
    finally:
        console.kill()
        console.wait()


def test_the_same_sync_does_reach_the_service_hooks_when_detection_sees_a_console(sync_env, tmp_path):
    # Control: proves the test above would notice a stop/start. Detection is simulated with a
    # ps listing, and the hooks are doubles, so nothing real is touched.
    ws, env, log = sync_env
    ps = tmp_path / "ps.txt"
    ps.write_text(f"python3 -u {HOST_SERVER}\n")
    env["SOLAR_CLIENT_PS_OUTPUT_FILE"] = str(ps)
    result = sync(ws, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().split() == ["host-stop", "host-start"]


def test_the_guard_refuses_this_sync_without_simulated_detection(sync_env):
    ws, env, log = sync_env
    result = sync(ws, env)  # no override, SOLAR_ROOT is the repository: the global install
    assert result.returncode == 97 and "real global install" in result.stderr
    assert not log.exists()
