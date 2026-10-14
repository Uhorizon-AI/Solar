"""Console identity: a console is reusable only if it serves this workspace AND runtime.

Covers the policy (host_identity.py) and every path that applies it: check_host.sh
with and without flag, ensure_host.sh, and the supervisor verdict.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "solar-app" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import host_identity  # noqa: E402

EXPECTED = {"workspace": "/w", "runtime": "/r"}


# -- the policy itself --------------------------------------------------------

@pytest.mark.parametrize("payload,state", [
    ({"workspace": "/w", "runtime": "/r"}, "match"),
    ({"workspace": "/other", "runtime": "/r"}, "mismatch"),
    ({"workspace": "/w", "runtime": "/other"}, "mismatch"),
    ({"workspace": "/other"}, "mismatch"),          # a differing value is final, even when partial
    ({"workspace": "/w"}, "partial"),
    ({"runtime": "/r"}, "partial"),
    ({}, "legacy"),
    ({"workspace": "", "runtime": "  "}, "legacy"),
    ("not a dict", "legacy"),
])
def test_compare_is_the_single_rule(payload, state):
    assert host_identity.compare(payload, EXPECTED)[0] == state


# 31. The port override is for tests only.
def test_port_override_cannot_move_production():
    assert host_identity.resolve_port({}) == 9000
    assert host_identity.resolve_port({"SOLAR_APP_PORT": "1234"}) == 9000
    assert host_identity.resolve_port({"SOLAR_APP_TEST_PORT": "19999"}) == 9000          # no test mode
    assert host_identity.resolve_port({"SOLAR_APP_TEST_MODE": "1"}) == 9000              # no port
    assert host_identity.resolve_port({"SOLAR_APP_TEST_MODE": "1", "SOLAR_APP_TEST_PORT": "9000"}) == 9000
    assert host_identity.resolve_port({"SOLAR_APP_TEST_MODE": "1", "SOLAR_APP_TEST_PORT": "80"}) == 9000
    assert host_identity.resolve_port({"SOLAR_APP_TEST_MODE": "1", "SOLAR_APP_TEST_PORT": "x"}) == 9000
    assert host_identity.resolve_port({"SOLAR_APP_TEST_MODE": "1", "SOLAR_APP_TEST_PORT": "19999"}) == 19999


def test_workspace_env_file_cannot_move_the_port(harness):
    (harness.ws / ".env").write_text("SOLAR_APP_TEST_MODE=1\nSOLAR_APP_TEST_PORT=19998\nSOLAR_APP_PORT=19997\n")
    result = harness.lib('echo "$SOLAR_APP_PORT"', SOLAR_APP_TEST_MODE=None, SOLAR_APP_TEST_PORT=None)
    assert result.stdout.strip() == "9000", result.stderr
    # The caller's own environment still wins, and .env cannot change it.
    result = harness.lib('echo "$SOLAR_APP_PORT"')
    assert result.stdout.strip() == str(harness.port)


def test_server_port_is_fixed_without_test_mode():
    code = "import host_server; print(host_server.PORT)"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOLAR_APP")}
    env["SOLAR_APP_TEST_PORT"] = "19999"
    out = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "9000", out.stderr
    env["SOLAR_APP_TEST_MODE"] = "1"
    out = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "19999", out.stderr


# -- check_host.sh, both modes -------------------------------------------------

MODES = [("--liveness",), ()]


def check(harness, *args, **env):
    return harness.script("check_host.sh", *args, **env)


# 5. matching identity is accepted
def test_matching_identity_is_accepted(harness):
    harness.spawn("full")
    assert check(harness, "--liveness").returncode == 0
    assert harness.script("ensure_host.sh").returncode == 0


# 6, 7. a different workspace or runtime is rejected in both modes, and nothing is stopped
@pytest.mark.parametrize("flag", MODES, ids=["liveness", "no-flag"])
@pytest.mark.parametrize("kwargs,differs", [
    ({"workspace": "/somewhere/else"}, "workspace"),
    ({"runtime": "/somewhere/else"}, "runtime"),
])
def test_other_identity_is_rejected(harness, flag, kwargs, differs):
    other = harness.spawn("full", **kwargs)
    result = check(harness, *flag)
    assert result.returncode == 3, result.stdout + result.stderr
    assert differs in result.stdout and "mismatch" in result.stdout
    assert harness.script("ensure_host.sh").returncode == 3
    assert other.poll() is None  # still running: rejected, never killed


# 8. equivalent paths through symlinks are the same console
@pytest.mark.parametrize("flag", MODES, ids=["liveness", "no-flag"])
def test_symlinked_paths_resolve_to_the_same_console(harness, flag, tmp_path):
    runtime_link = tmp_path / "runtime-link"
    runtime_link.symlink_to(harness.runtime)
    harness.claim_state()
    harness.start_real_console()  # reports the physical paths
    result = check(harness, *flag, SOLAR_RUNTIME_ROOT=str(runtime_link))
    assert result.returncode == 0, result.stdout + result.stderr


# 13. the no-flag mode (the supervisor's) also requires identity
def test_no_flag_mode_requires_identity_on_a_real_console(harness):
    harness.claim_state()
    harness.start_real_console()
    ok = check(harness)
    assert ok.returncode == 0 and "OK:" in ok.stdout, ok.stdout + ok.stderr
    # The same real console seen from another runtime is not accepted, flag or not.
    other_runtime = harness.root / "another-runtime"
    other_runtime.mkdir()
    for flag in MODES:
        rejected = check(harness, *flag, SOLAR_RUNTIME_ROOT=str(other_runtime))
        assert rejected.returncode == 3, rejected.stdout


@pytest.mark.parametrize("flag", MODES, ids=["liveness", "no-flag"])
@pytest.mark.parametrize("mode", ["legacy", "workspace_only", "runtime_only"])
def test_missing_or_partial_identity_is_not_accepted(harness, flag, mode):
    harness.spawn(mode)
    result = check(harness, *flag)
    assert result.returncode == 3 and "identity" in result.stdout


# 14. JSON never fails open
@pytest.mark.parametrize("mode", ["legacy", "workspace_only", "runtime_only"])
def test_json_without_identity_reports_unavailable(harness, mode):
    harness.spawn(mode)
    result = check(harness, "--json")
    data = json.loads(result.stdout)
    assert data["available"] is False and data["storage_ok"] is False
    assert "identity" in data["error"]
    assert result.returncode == 3


def test_json_unreachable_is_unavailable(harness):
    result = check(harness, "--json")
    assert json.loads(result.stdout)["available"] is False and result.returncode == 1


# 29. a proxy in the environment is ignored for loopback probes
def test_loopback_probe_ignores_a_configured_proxy(harness):
    harness.spawn("full")
    dead_proxy = {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
                  "all_proxy": "http://127.0.0.1:9", "no_proxy": ""}
    assert check(harness, "--liveness", **dead_proxy).returncode == 0
    # The unit under it: the opener carries no proxy handler with a target.
    os.environ["http_proxy"] = "http://127.0.0.1:9"
    try:
        status, payload = host_identity.fetch_health(f"http://127.0.0.1:{harness.port}")
    finally:
        del os.environ["http_proxy"]
    assert status == 200 and payload["service"] == "solar-console"


# 27. the healthy path adds no lsof cost
def test_healthy_paths_never_run_lsof(harness):
    harness.spawn("full")
    marker = harness.root / "lsof-ran"
    harness.fake_tool("lsof", f"echo ran >> '{marker}'\n")
    assert check(harness, "--liveness").returncode == 0
    assert harness.script("ensure_host.sh").returncode == 0
    assert not marker.exists()


# 15. the supervisor does not trust a console of another workspace or runtime
def supervisor(harness, **env):
    for name, code in (("launchctl", 0), ("pgrep", 1)):
        harness.fake_tool(name, f"exit {code}\n")
    harness.fake_tool("timeout", 'shift; exec "$@"\n')
    (harness.ws / ".env").write_text("SOLAR_SYSTEM_FEATURES=host\n")
    return subprocess.run(["bash", str(SCRIPTS.parent.parent / "solar-system/scripts/check_orchestrator.sh")],
                          cwd=harness.ws, env=harness.env(**env), capture_output=True, text=True, timeout=90)


def host_block(output):
    return output.split("Feature: host", 1)[1].split("──", 1)[0]


@pytest.mark.parametrize("kwargs", [{"workspace": "/somewhere/else"}, {"runtime": "/somewhere/else"},
                                    {"mode": "legacy"}])
def test_supervisor_marks_a_foreign_console_untrusted(harness, kwargs):
    harness.spawn("full", **kwargs) if "mode" not in kwargs else harness.spawn(kwargs["mode"])
    out = supervisor(harness)
    block = host_block(out.stdout)
    assert "status: UNTRUSTED" in block and "HEALTHY" not in block, out.stdout
    assert "Verdict: DOWN" in out.stdout


def test_supervisor_accepts_the_matching_console(harness):
    harness.claim_state()
    harness.start_real_console()
    out = supervisor(harness)
    assert "status: HEALTHY" in host_block(out.stdout), out.stdout
