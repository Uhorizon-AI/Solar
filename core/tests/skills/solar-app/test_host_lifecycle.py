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
    assert "Python.app" in subprocess.run(["ps", "-ww", "-p", str(hung.pid), "-o", "args="], capture_output=True,
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
    foreign = harness.spawn("full", install="this", runtime="/somewhere/else")
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


# 23. start never kills a host_server.py of another workspace or runtime
@pytest.mark.parametrize("state", ["other-workspace", "other-runtime-with-pid-file", "hung-other-install"])
def test_start_never_kills_another_workspaces_console(harness, state):
    if state == "other-workspace":
        # Another workspace and nothing from this runtime pointing at it: not ours.
        other = harness.spawn("full", install="this", workspace="/somewhere/else")
    elif state == "other-runtime-with-pid-file":
        # A pid file never overrides a runtime mismatch: the runtime is the machine's, not a hint.
        other = harness.spawn("full", install="this", runtime="/somewhere/else")
        harness.write_pid_file(other.pid)
    else:
        other = harness.spawn("drop", install="other")
    result = harness.script("start_host.sh")
    assert result.returncode == 3, result.stdout + result.stderr
    assert other.poll() is None
    assert "Automatic checks will not retry" in result.stderr or "cannot be shown" in result.stderr


def switch_active_workspace(harness):
    second = harness.root / "ws2"
    (second / "sun").mkdir(parents=True)
    (second / ".solar").mkdir()
    (second / ".solar" / "settings.json").write_text('{"layout":"solar-client-v1.1","core_source":"global"}')
    for command in ("add", "use"):
        subprocess.run([sys.executable, str(SCRIPTS / "host_registry.py"), command, str(second)],
                       env=harness.env(), check=True, capture_output=True)
    return second


# The active workspace is switched while this runtime's console runs. The real console
# re-reads the registry on every request, so it follows the switch and stays accepted.
def test_the_running_console_follows_an_active_workspace_switch(harness):
    pid = harness.start_real_console()
    switch_active_workspace(harness)
    assert harness.script("check_host.sh", "--liveness").returncode == 0
    assert harness.script("stop_host.sh").returncode == 0 and harness.gone(pid)


# Safety net for a console that still reports the previous workspace (same runtime, this
# runtime's pid file points at the very pid that answered): it is ours, so it can be stopped
# and replaced; a bare `mismatch` would strand it as UNTRUSTED and block the cutover.
def test_our_console_on_a_previous_workspace_is_stopped_and_replaced(harness):
    stale = harness.spawn("full", install="other", workspace="/previous/workspace")
    harness.write_pid_file(stale.pid)
    assert harness.script("check_host.sh", "--liveness").returncode == 3  # not reusable as is
    result = harness.script("ensure_host.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert harness.gone(stale)
    assert harness.script("check_host.sh", "--liveness").returncode == 0


def test_stop_host_stops_our_console_on_a_previous_workspace(harness):
    stale = harness.spawn("full", install="other", workspace="/previous/workspace")
    harness.write_pid_file(stale.pid)
    result = harness.script("stop_host.sh")
    assert result.returncode == 0 and "OK: Solar Host stopped" in result.stdout, result.stderr
    assert harness.gone(stale)


def test_a_previous_workspace_console_without_our_pid_file_is_left_alone(harness):
    other = harness.spawn("full", install="this", workspace="/previous/workspace")
    result = harness.script("stop_host.sh")
    assert result.returncode == 3 and other.poll() is None


# Identity belongs to the pid that answered, not to every listener of the port.
def test_orphan_stop_ignores_listeners_on_other_addresses(harness):
    own = harness.start_real_console()
    stranger = harness.spawn("drop", install="this", port=ch.free_port())  # host_server.py-named, not on our port
    harness.fake_lsof((own, "127.0.0.1"), (stranger.pid, "127.0.0.2"), (stranger.pid, "::1"))
    assert harness.lib("solar_host_port_listener_pids").stdout.split() == [str(own)]
    result = stop_orphans(harness)
    assert result.returncode == 0, result.stderr
    assert harness.gone(own)
    assert stranger.poll() is None


def test_pid_file_repair_uses_the_pid_the_console_reports(harness):
    own = harness.start_real_console()
    decoy = harness.spawn("drop", install="other", port=ch.free_port())
    harness.pid_file().unlink()
    harness.fake_lsof((decoy.pid, "127.0.0.1"), (own, "127.0.0.1"))  # the decoy comes first
    result = harness.script("start_host.sh")
    assert result.returncode == 0 and "pid file repaired" in result.stdout, result.stdout + result.stderr
    assert int(harness.pid_file().read_text()) == own
    assert decoy.poll() is None


# A console that proves its identity but reports no pid is still stoppable and recoverable.
def test_console_without_a_reported_pid_is_stopped_through_its_listener(harness):
    console = harness.spawn("nopid", install="other")
    harness.write_pid_file(console.pid)
    result = harness.script("stop_host.sh")
    assert result.returncode == 0 and "OK: Solar Host stopped" in result.stdout, result.stderr
    assert harness.gone(console)


def test_orphan_stop_falls_back_to_the_listener_when_no_pid_is_reported(harness):
    console = harness.spawn("nopid", install="other")
    result = stop_orphans(harness)
    assert result.returncode == 0, result.stderr
    assert harness.gone(console)


def test_start_repairs_the_pid_file_of_a_console_without_a_reported_pid(harness):
    console = harness.spawn("nopid", install="other")
    result = harness.script("start_host.sh")
    assert result.returncode == 0 and "pid file repaired" in result.stdout, result.stdout + result.stderr
    assert int(harness.pid_file().read_text()) == console.pid


def test_a_reported_pid_that_is_not_the_listener_is_not_signalled(harness):
    console = harness.spawn("full", install="other")
    decoy = harness.spawn("drop", install="other", port=ch.free_port())
    harness.fake_lsof((decoy.pid, "127.0.0.1"))  # lsof says the listener is someone else
    result = stop_orphans(harness)
    assert result.returncode != 0 and "not its listener" in result.stderr
    assert console.poll() is None and decoy.poll() is None


def test_install_path_match_is_anchored_to_the_whole_argument(harness):
    # /other/prefix + this install's path must not count as this install.
    folder = harness.root / "other-prefix"
    script = folder.joinpath(*Path(harness.install_script).parts[1:])
    script.parent.mkdir(parents=True)
    script.write_text(ch.FAKE_CONSOLE)
    proc = subprocess.Popen([sys.executable, "-u", str(script), str(harness.port), "drop", "/w", "/r"],
                            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    harness.procs.append(proc)
    harness.wait_listening(harness.port)
    result = harness.lib(f"solar_host_pid_is_this_install {proc.pid} && echo yes || echo no")
    assert result.stdout.strip() == "no"
    assert harness.lib(f"solar_host_stop_orphan_listeners").returncode != 0
    assert proc.poll() is None


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
    assert all(pid != str(double.pid) for pid, *_ in console_port_baseline)
    assert port_watch.new_listeners(console_port_baseline, port_watch.snapshot(port_watch.PRODUCTION_PORT)) == frozenset()


# 4 (replacement). The same address with another command line is the original incident.
def test_port_watch_detects_a_console_replaced_by_another_program(harness):
    import port_watch
    first = harness.spawn("full", install="other")
    baseline = port_watch.snapshot(harness.port)
    if baseline is None:
        pytest.skip("lsof is not available")
    assert port_watch.new_listeners(baseline, baseline) == frozenset()
    first.terminate()
    assert harness.gone(first)
    harness.spawn("full", install="other")  # another folder: another command line, same address
    after = port_watch.snapshot(harness.port)
    leaked = port_watch.new_listeners(baseline, after)
    assert len(leaked) == 1


def test_port_watch_accepts_the_same_program_restarted(harness):
    import port_watch
    script = harness.root / "host_server.py"
    script.write_text(ch.FAKE_CONSOLE)
    argv = [sys.executable, "-u", str(script), str(harness.port), "full", "/w", "/r"]

    def run():
        proc = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        harness.procs.append(proc)
        harness.wait_listening(harness.port)
        return proc

    first = run()
    baseline = port_watch.snapshot(harness.port)
    if baseline is None:
        pytest.skip("lsof is not available")
    first.terminate()
    assert harness.gone(first)
    run()  # new pid, same command line: a LaunchAgent restart
    assert port_watch.new_listeners(baseline, port_watch.snapshot(harness.port)) == frozenset()


# Same command line and port, other environment: the identity in /health tells them apart.
def test_port_watch_detects_a_replacement_with_the_same_command_and_another_identity(harness):
    import port_watch
    script = harness.root / "host_server.py"
    script.write_text(ch.FAKE_CONSOLE.replace("workspace, runtime = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]",
                                               "workspace, runtime = int(sys.argv[1]), sys.argv[2], os.environ['FAKE_WS'], sys.argv[4]"))
    argv = [sys.executable, "-u", str(script), str(harness.port), "full", "unused", "/r"]

    def run(workspace):
        proc = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=dict(os.environ, FAKE_WS=workspace))
        harness.procs.append(proc)
        harness.wait_listening(harness.port)
        return proc

    first = run("/original/workspace")
    baseline = port_watch.snapshot(harness.port)
    if baseline is None:
        pytest.skip("lsof is not available")
    first.terminate()
    assert harness.gone(first)
    run("/original/workspace")  # same command, same identity, new pid: a restart
    assert port_watch.new_listeners(baseline, port_watch.snapshot(harness.port)) == frozenset()
    harness.procs[-1].terminate()
    assert harness.gone(harness.procs[-1])
    run("/another/workspace")  # same command and port, different environment
    assert len(port_watch.new_listeners(baseline, port_watch.snapshot(harness.port))) == 1


def test_port_watch_treats_an_unreadable_identity_as_a_replacement(harness):
    import port_watch
    script = harness.root / "host_server.py"
    script.write_text(ch.FAKE_CONSOLE)
    argv = [sys.executable, "-u", str(script), str(harness.port), "drop", "/w", "/r"]  # never answers /health

    def run():
        proc = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        harness.procs.append(proc)
        harness.wait_listening(harness.port)
        return proc

    first = run()
    baseline = port_watch.snapshot(harness.port)
    if baseline is None:
        pytest.skip("lsof is not available")
    first.terminate()
    assert harness.gone(first)
    run()
    assert len(port_watch.new_listeners(baseline, port_watch.snapshot(harness.port))) == 1


# A console may declare any pid: it is only signalled if it is also the listener.
def test_a_declared_pid_of_another_host_server_is_never_signalled(harness):
    victim = harness.spawn("drop", install="this", port=ch.free_port())  # a live host_server.py elsewhere
    liar = harness.spawn("full", install="other", workspace="/previous/workspace", report_pid=victim.pid)
    harness.write_pid_file(victim.pid)  # even with the pid file naming the declared pid
    for script in ("stop_host.sh", "start_host.sh"):
        result = harness.script(script)
        assert victim.poll() is None, (script, result.stdout, result.stderr)
        assert liar.poll() is None, script
    assert stop_orphans(harness).returncode != 0
    assert victim.poll() is None and liar.poll() is None


def test_port_watch_identity_needs_both_fields(harness):
    import port_watch
    for mode in ("legacy", "workspace_only", "runtime_only"):
        proc = harness.spawn(mode, install="other")
        address = f"127.0.0.1:{harness.port}"
        assert port_watch._identity(str(proc.pid), address) == "", mode
        proc.terminate()
        assert harness.gone(proc)
    proc = harness.spawn("full", install="other")
    assert port_watch._identity(str(proc.pid), f"127.0.0.1:{harness.port}") != ""


def test_port_watch_does_not_verify_consoles_that_report_no_identity(harness):
    import port_watch
    script = harness.root / "host_server.py"
    script.write_text(ch.FAKE_CONSOLE)
    argv = [sys.executable, "-u", str(script), str(harness.port), "legacy", "/w", "/r"]

    def run():
        proc = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        harness.procs.append(proc)
        harness.wait_listening(harness.port)
        return proc

    first = run()
    baseline = port_watch.snapshot(harness.port)
    if baseline is None:
        pytest.skip("lsof is not available")
    first.terminate()
    assert harness.gone(first)
    run()  # same command, new pid, and no identity to prove it is the same program
    assert len(port_watch.new_listeners(baseline, port_watch.snapshot(harness.port))) == 1


def test_a_lying_pid_is_not_signalled_by_the_orphan_stop_without_a_pid_file(harness):
    victim = harness.spawn("drop", install="this", port=ch.free_port())
    for mode, kwargs in (("match", {}), ("stale", {"workspace": "/previous/workspace"})):
        liar = harness.spawn("full", install="other", report_pid=victim.pid, **kwargs)
        result = stop_orphans(harness)
        assert result.returncode != 0, (mode, result.stderr)
        if mode == "match":  # the cross-check; without a pid file the other case is a plain mismatch
            assert "not its listener" in result.stderr, result.stderr
        assert victim.poll() is None and liar.poll() is None, mode
        liar.terminate()
        assert harness.gone(liar)


def test_a_lying_pid_is_not_signalled_when_the_identity_matches(harness):
    victim = harness.spawn("drop", install="this", port=ch.free_port())
    liar = harness.spawn("full", install="other", report_pid=victim.pid)  # match, but declares another pid
    harness.write_pid_file(victim.pid)
    for script in ("stop_host.sh", "start_host.sh"):
        harness.script(script)
        assert victim.poll() is None and liar.poll() is None, script


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
