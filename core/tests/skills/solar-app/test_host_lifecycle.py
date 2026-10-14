"""Console lifecycle: a process is signalled only when it is a host_server.py that is
provably this runtime's console. Foreign consoles are reported, never stopped.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import console_harness as ch

SCRIPTS = ch.APP_SCRIPTS
sys.path.insert(0, str(SCRIPTS))
import host_identity  # noqa: E402

LEGACY_MODES = ["legacy", "workspace_only", "runtime_only"]


def serves_this_runtime(h) -> bool:
    return h.script("check_host.sh", "--liveness").returncode == 0


def stop_orphans(h, **env):
    return h.lib("solar_host_stop_orphan_listeners", **env)


# -- solar_host_stop_orphan_listeners ------------------------------------------

# 16. a foreign console is never stopped
@pytest.mark.parametrize("kwargs", [{"workspace": "/somewhere/else"}, {"runtime": "/somewhere/else"}])
def test_orphan_stop_never_kills_a_foreign_console(harness, kwargs):
    foreign = harness.spawn("full", install="this", **kwargs)  # even with this install's path on its line
    result = stop_orphans(harness)
    assert result.returncode != 0, result.stdout + result.stderr
    assert foreign.poll() is None
    assert "left untouched" in result.stderr


# 17. an own console really stops
def test_own_console_stops_for_real(harness):
    pid = harness.start_real_console()
    harness.pid_file().unlink()  # orphan path: no pid file
    result = stop_orphans(harness)
    assert result.returncode == 0, result.stderr
    assert harness.gone(pid)


def test_stop_host_stops_the_recorded_console(harness):
    pid = harness.start_real_console()
    result = harness.script("stop_host.sh")
    assert result.returncode == 0 and "OK: Solar Host stopped" in result.stdout
    assert harness.gone(pid) and not harness.pid_file().exists()


# 18. an own console that hangs (listening, never answering, no pid file) is recognised by its install path
def test_hung_own_console_is_recognised_and_stopped(harness):
    hung = harness.spawn("drop", install="this")
    result = stop_orphans(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert harness.gone(hung)


# 19. the same with the macOS Python.app interpreter
def test_hung_own_console_under_python_app_is_recognised(harness):
    interpreter = harness.root / "Python.app" / "Contents" / "MacOS" / "Python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(shutil.which("python3") or sys.executable)
    hung = harness.spawn("drop", install="this", interpreter=str(interpreter))
    assert "Python.app" in subprocess.run(["ps", "-p", str(hung.pid), "-o", "args="], capture_output=True,
                                          text=True).stdout
    result = stop_orphans(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert harness.gone(hung)


# 20. a hung console of another install stays foreign
def test_hung_console_of_another_install_is_left_alone(harness):
    other = harness.spawn("drop", install="other")
    result = stop_orphans(harness)
    assert result.returncode != 0
    assert other.poll() is None


# 21. stop_host.sh never signals anything that is not a live host_server.py
def test_stop_host_ignores_a_recycled_pid(harness):
    sleeper = harness.spawn_sleeper()
    harness.write_pid_file(sleeper.pid)
    result = harness.script("stop_host.sh")
    assert result.returncode == 0 and "stale pid file" in result.stderr
    assert sleeper.poll() is None
    assert not harness.pid_file().exists()


def test_stop_host_refuses_a_foreign_console(harness):
    foreign = harness.spawn("full", install="this", workspace="/somewhere/else")
    harness.write_pid_file(foreign.pid)
    result = harness.script("stop_host.sh")
    assert result.returncode == 3 and "NOT stopped" in result.stderr
    assert foreign.poll() is None


# -- start_host.sh ------------------------------------------------------------

# 22. an own hung console is recovered instead of failing
def test_start_recovers_an_own_hung_console(harness):
    hung = harness.spawn("drop", install="this")
    result = harness.script("start_host.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert harness.gone(hung)
    assert serves_this_runtime(harness)


# 23. start never kills a host_server.py of another workspace
@pytest.mark.parametrize("state", ["answering-other-workspace", "answering-other-runtime", "hung-other-install"])
def test_start_never_kills_another_workspaces_console(harness, state):
    if state == "answering-other-workspace":
        other = harness.spawn("full", install="this", workspace="/somewhere/else")
    elif state == "answering-other-runtime":
        other = harness.spawn("full", install="this", runtime="/somewhere/else")
    else:
        other = harness.spawn("drop", install="other")
    if state != "hung-other-install":
        # Even a pid file that points at it: identity says it serves another workspace/runtime.
        # (A pid file is proof for a console that cannot answer; it never overrides a mismatch.)
        harness.write_pid_file(other.pid)
    result = harness.script("start_host.sh")
    assert result.returncode == 3, result.stdout + result.stderr
    assert other.poll() is None
    assert "Automatic checks will not retry" in result.stderr or "cannot be shown" in result.stderr


def test_foreign_console_diagnostic_names_who_removes_it_and_how(harness):
    harness.spawn("full", workspace="/somewhere/else")
    result = harness.script("start_host.sh")
    text = result.stderr
    assert "/somewhere/else" in text                       # what it serves
    assert "NOT reused and NOT stopped" in text
    assert "check_host.sh" in text and "--json" in text    # confirm identity first
    assert "stop_host.sh" in text and "lsof" in text       # the owner's stop, or a manual stop
    assert "will not retry" in text


def test_foreign_console_does_not_loop(harness):
    harness.spawn("full", workspace="/somewhere/else")
    import time
    began = time.time()
    result = harness.script("ensure_host.sh")
    assert result.returncode == 3 and time.time() - began < 20


# 24. a stale pid file is repaired while the console answers
def test_start_repairs_a_stale_pid_file(harness):
    pid = harness.start_real_console()
    harness.write_pid_file(2147483646)  # not a process
    result = harness.script("start_host.sh")
    assert result.returncode == 0 and "pid file repaired" in result.stdout, result.stdout + result.stderr
    assert int(harness.pid_file().read_text()) == pid


# 25. a valid pid file that is not the first listener is kept
def test_start_keeps_a_valid_pid_file_that_is_not_the_first_listener(harness):
    pid = harness.start_real_console()
    decoy = harness.spawn("drop", install="other", port=ch.free_port())
    harness.fake_lsof((decoy.pid, "127.0.0.1"), (pid, "127.0.0.1"))
    result = harness.script("start_host.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert int(harness.pid_file().read_text()) == pid
    assert decoy.poll() is None


# 26. adoption needs host_server.py in the pid: a recycled pid is rejected
@pytest.mark.parametrize("mode", ["legacy", "full"])
def test_a_recycled_pid_is_never_adopted_or_signalled(harness, mode):
    sleeper = harness.spawn_sleeper()
    harness.write_pid_file(sleeper.pid)
    console = harness.spawn(mode, install="other")
    result = harness.script("start_host.sh")
    assert sleeper.poll() is None and console.poll() is None
    if mode == "legacy":
        assert result.returncode == 3, result.stdout + result.stderr
    else:  # identity proves the console; the bad pid file is replaced, not trusted
        assert result.returncode == 0
        assert harness.pid_file().exists() is False or int(harness.pid_file().read_text()) != sleeper.pid


# 9, 11. an older console with no (or partial) identity is adopted only through this runtime's pid file
@pytest.mark.parametrize("mode", LEGACY_MODES)
def test_old_console_adopted_through_the_runtime_pid_file(harness, mode):
    old = harness.spawn(mode, install="other")
    harness.write_pid_file(old.pid)
    result = harness.script("start_host.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "adopting" in result.stderr
    assert harness.gone(old)
    assert serves_this_runtime(harness)  # replaced by a console that reports identity


# 10, 11. no pid file, no proof: neither adopted nor stopped
@pytest.mark.parametrize("mode", LEGACY_MODES)
def test_old_console_without_proof_is_neither_adopted_nor_killed(harness, mode):
    old = harness.spawn(mode, install="other")
    result = harness.script("start_host.sh")
    assert result.returncode == 3 and "Ownership of that console could not be shown" in result.stderr
    assert old.poll() is None and not harness.pid_file().exists()


# 12. an older console of THIS install is recovered, not left stranded
@pytest.mark.parametrize("mode", LEGACY_MODES)
def test_old_console_of_this_install_is_recovered(harness, mode):
    old = harness.spawn(mode, install="this")
    result = harness.script("start_host.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert harness.gone(old)
    assert serves_this_runtime(harness)


# 28. without lsof nothing without identity is adopted or stopped
def test_without_lsof_an_unidentified_console_is_left_alone(harness):
    assert shutil.which("lsof", path=harness.scrubbed_path()) is None
    old = harness.spawn("legacy", install="this")
    harness.write_pid_file(old.pid)
    result = harness.script("start_host.sh", PATH=harness.scrubbed_path())
    assert result.returncode == 3, result.stdout + result.stderr
    assert old.poll() is None
    orphans = stop_orphans(harness, PATH=harness.scrubbed_path())
    assert orphans.returncode != 0 and old.poll() is None


def test_without_lsof_listener_discovery_is_empty(harness, monkeypatch):
    monkeypatch.setenv("PATH", harness.scrubbed_path())
    harness.spawn("legacy", install="this")
    assert host_identity.loopback_listener_pids(harness.port) == []


# 30. a listener on another address is not our console
def test_listener_on_another_address_is_not_ours(harness):
    decoy = harness.spawn("drop", install="this", port=ch.free_port())
    harness.fake_lsof((decoy.pid, "192.0.2.1"), (decoy.pid, "0.0.0.0"))
    assert harness.lib("solar_host_port_listener_pids").stdout.strip() == ""
    result = harness.script("start_host.sh")
    assert result.returncode == 0, result.stdout + result.stderr  # loopback was free; a console started
    assert decoy.poll() is None
    stop_orphans(harness)
    assert decoy.poll() is None


def test_loopback_listeners_are_listed(harness):
    proc = harness.spawn("drop", install="this")
    pids = harness.lib("solar_host_port_listener_pids").stdout.split()
    assert str(proc.pid) in pids


# 4. nothing is left behind on the production port, compared with the baseline taken first
def test_baseline_is_recorded_before_any_double(harness, console_port_baseline):
    import port_watch
    if console_port_baseline is None:
        pytest.skip("lsof is not available: the port cannot be observed")
    assert harness.baseline is console_port_baseline
    double = harness.spawn("full")
    # The baseline predates the double, so it cannot contain it; the production port is unchanged.
    assert all(pid != str(double.pid) for pid, _ in console_port_baseline)
    assert port_watch.new_listeners(console_port_baseline, port_watch.snapshot(port_watch.PRODUCTION_PORT)) == frozenset()


def test_port_watch_reports_a_new_listener():
    import port_watch
    port = ch.free_port()
    before = port_watch.snapshot(port)
    if before is None:
        pytest.skip("lsof is not available")
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
        sock.listen()
        after = port_watch.snapshot(port)
        assert len(port_watch.new_listeners(before, after)) == 1
    assert port_watch.new_listeners(before, port_watch.snapshot(port)) == frozenset()


def test_doubles_leave_no_listener_after_teardown(tmp_path, console_port_baseline):
    import port_watch
    h = ch.Harness(tmp_path, console_port_baseline)
    h.spawn("full")
    h.spawn_sleeper()
    h.cleanup()
    snap = port_watch.snapshot(h.port)
    assert not snap
