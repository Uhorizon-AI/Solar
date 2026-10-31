"""The macOS-runner skip in Harness.script must hide only a slow start.

Measured on the GitHub macOS runner (issue 108): a start that reaches the readiness loop
takes ~35 s. start_host.sh prints "failed to start" for ANY failed start, including a crash
a moment after launch (an ImportError in host_server.py), so that phrase cannot tell a slow
start from a broken one. Only the 10 s cap may skip; a quick non-zero exit must fail.
"""
import subprocess

import pytest

FAILED = "ERROR: Solar Host failed to start (pid 1)\n--- last lines ---\nImportError: no module named x"


def _run_returning(monkeypatch, result):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)


def _run_timing_out(monkeypatch, seen):
    def fake(*args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))
    monkeypatch.setattr(subprocess, "run", fake)


def test_a_slow_start_is_skipped_on_the_slow_runner(harness, monkeypatch):
    monkeypatch.setenv("SOLAR_CI_SLOW_HEALTH_PROBE", "1")
    seen = {}
    _run_timing_out(monkeypatch, seen)
    with pytest.raises(pytest.skip.Exception):
        harness.script("start_host.sh")
    assert seen["timeout"] == 10


def test_a_start_that_crashes_at_once_still_fails_on_the_slow_runner(harness, monkeypatch):
    monkeypatch.setenv("SOLAR_CI_SLOW_HEALTH_PROBE", "1")
    crashed = subprocess.CompletedProcess(["bash"], 1, stdout="", stderr=FAILED)
    _run_returning(monkeypatch, crashed)
    result = harness.script("start_host.sh")      # returned, not skipped
    assert result.returncode == 1 and "failed to start" in result.stderr


def test_a_slow_start_is_not_hidden_when_the_marker_is_absent(harness, monkeypatch):
    monkeypatch.delenv("SOLAR_CI_SLOW_HEALTH_PROBE", raising=False)
    _run_timing_out(monkeypatch, {})
    with pytest.raises(subprocess.TimeoutExpired):
        harness.script("start_host.sh")


def test_other_scripts_keep_their_own_timeout_on_the_slow_runner(harness, monkeypatch):
    monkeypatch.setenv("SOLAR_CI_SLOW_HEALTH_PROBE", "1")
    seen = {}
    _run_timing_out(monkeypatch, seen)
    with pytest.raises(subprocess.TimeoutExpired):
        harness.script("stop_host.sh")
    assert seen["timeout"] == 90
