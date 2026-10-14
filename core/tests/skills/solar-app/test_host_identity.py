"""Unit tests for host_identity.py — the single console identity policy.

The shell suite (``test_host_identity.sh``) exercises the policy through the
scripts; this one pins the policy itself, including the blank cases and the
physical-path comparison, so a regression is attributed to the rule and not to
a caller.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[3] / "skills" / "solar-app" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import host_identity  # noqa: E402


def own_roots(install: Path):
    return [str(install)]


class CanonicalTest(unittest.TestCase):
    def test_resolves_symlinks_and_relative_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real)
            self.assertEqual(host_identity.canonical(str(link)), host_identity.canonical(str(real)))
            self.assertEqual(host_identity.canonical(str(real / "." )), host_identity.canonical(str(real)))

    def test_keeps_trailing_slash_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(host_identity.canonical(tmp + "/"), host_identity.canonical(tmp))


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "ws"
        self.rt = self.root / "runtime"
        self.other_ws = self.root / "other-ws"
        self.other_rt = self.root / "other-runtime"
        for path in (self.ws, self.rt, self.other_ws, self.other_rt):
            path.mkdir()
        self.install = self.root / "install"
        (self.install / "core/skills/solar-app/scripts").mkdir(parents=True)
        self.server = self.install / "core/skills/solar-app/scripts/host_server.py"
        self.server.write_text("#!/usr/bin/env python3\n")

    def tearDown(self):
        self.tmp.cleanup()

    def evaluate(self, health, **kwargs):
        kwargs.setdefault("workspace", str(self.ws))
        kwargs.setdefault("runtime", str(self.rt))
        kwargs.setdefault("install_roots", own_roots(self.install))
        return host_identity.evaluate(health=health, **kwargs)

    def test_matching_identity_is_own(self):
        self.assertIsNone(self.evaluate({"workspace": str(self.ws), "runtime": str(self.rt)}))

    def test_symlinked_workspace_is_own(self):
        link = self.root / "ws-link"
        link.symlink_to(self.ws)
        self.assertIsNone(self.evaluate({"workspace": str(link), "runtime": str(self.rt)}))

    def test_other_workspace_is_rejected(self):
        reason = self.evaluate({"workspace": str(self.other_ws), "runtime": str(self.rt)})
        self.assertIn("another workspace", reason)

    def test_other_runtime_is_rejected(self):
        reason = self.evaluate({"workspace": str(self.ws), "runtime": str(self.other_rt)})
        self.assertIn("another runtime", reason)

    def test_blank_health_without_a_proof_is_rejected(self):
        reason = self.evaluate({})
        self.assertIn("no identity and no process", reason)

    def test_blank_health_with_the_own_command_is_own(self):
        command = f"python3 {self.server}"
        self.assertIsNone(self.evaluate({}, listener_command=command))

    def test_blank_health_with_an_install_path_containing_spaces_is_own(self):
        # An install under "Application Support" has spaces: a command line must
        # not be split on them.
        spaced = self.root / "Application Support" / "solar"
        (spaced / "core/skills/solar-app/scripts").mkdir(parents=True)
        server = spaced / "core/skills/solar-app/scripts/host_server.py"
        server.write_text("#!/usr/bin/env python3\n")
        self.assertIsNone(self.evaluate(
            {}, listener_command=f"python3 {server}", install_roots=[str(spaced)]))

    def test_blank_health_with_the_own_command_in_quotes_is_own(self):
        # The path is not re-split on spaces: an install under "Application
        # Support" is one path even when the command line quotes it.
        spaced = self.root / "Application Support" / "solar"
        (spaced / "core/skills/solar-app/scripts").mkdir(parents=True)
        server = spaced / "core/skills/solar-app/scripts/host_server.py"
        server.write_text("#!/usr/bin/env python3\n")
        self.assertIsNone(self.evaluate(
            {}, listener_command=f"python3 {server}", install_roots=[str(spaced)]))

    def test_pid_file_of_another_process_does_not_adopt_a_foreign_listener(self):
        # The pid file names a live own host_server.py, but the port's listener is
        # a different process: the pid file must not adopt it.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = host_identity.pid_file_own_server
        host_identity.pid_file_own_server = lambda path, pid=None: True
        try:
            # The port's listener differs from the pid in the file, and the
            # listener has no identity, so it must be rejected.
            reason = self.evaluate({}, pid_file=str(pid_file), listener_pids=["424242"])
        finally:
            host_identity.pid_file_own_server = original
        self.assertIn("no identity and no process", reason)

    def test_pid_file_matching_the_listener_adopts_it(self):
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = host_identity.pid_file_own_server
        host_identity.pid_file_own_server = lambda path, pid=None: True
        try:
            self.assertIsNone(self.evaluate(
                {}, pid_file=str(pid_file), listener_pids=[str(os.getpid())]))
        finally:
            host_identity.pid_file_own_server = original

    def test_pid_file_matching_a_second_listener_is_adopted(self):
        # Several listeners on the port and the pid file names one that is not
        # the first: it is still a listener, so it must be adopted.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = host_identity.pid_file_own_server
        host_identity.pid_file_own_server = lambda path, pid=None: True
        try:
            self.assertIsNone(self.evaluate(
                {}, pid_file=str(pid_file),
                listener_pids=["424242", str(os.getpid())]))
        finally:
            host_identity.pid_file_own_server = original

    def test_pid_file_without_listeners_needs_the_install_proof(self):
        # lsof failed (or is missing): no listener could be enumerated. An own
        # pid file alone only proves runtime membership and would adopt a foreign
        # console on the port, so it must not be enough: the pid's own command
        # has to be this install's host_server.py.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_pid_file = host_identity.pid_file_own_server
        original_command = host_identity.pid_command
        host_identity.pid_file_own_server = lambda path, pid=None: True
        try:
            host_identity.pid_command = lambda pid: "python3 /somewhere/else/host_server.py"
            reason = self.evaluate({}, pid_file=str(pid_file), listener_pids=[])
            self.assertIn("no identity and no process", reason)

            host_identity.pid_command = lambda pid: f"python3 {self.server}"
            self.assertIsNone(self.evaluate({}, pid_file=str(pid_file), listener_pids=[]))
        finally:
            host_identity.pid_file_own_server = original_pid_file
            host_identity.pid_command = original_command

    def test_blank_health_with_another_install_command_is_rejected(self):
        command = "python3 /somewhere/else/core/skills/solar-app/scripts/host_server.py"
        self.assertIn("no identity and no process", self.evaluate({}, listener_command=command))

    def test_blank_health_resolves_the_command_from_the_listener_pid(self):
        # A pid that runs host_server.py of this install is a proof on its own.
        command = host_identity.pid_command(os.getpid())
        if "host_server.py" in command:
            self.skipTest("this test's own command line mentions host_server.py")
        self.assertIn("no identity and no process", self.evaluate({}, listener_pids=[str(os.getpid())]))

    def test_partial_identity_needs_a_proof(self):
        reason = self.evaluate({"runtime": str(self.rt)})
        self.assertIn("partial identity", reason)
        self.assertIn("runtime=" + str(self.rt), reason)

    def test_workspace_only_identity_is_partial(self):
        reason = self.evaluate({"workspace": str(self.ws)})
        self.assertIn("partial identity", reason)

    def test_partial_identity_is_own_with_the_own_command(self):
        command = f"python3 {self.server}"
        self.assertIsNone(self.evaluate({"runtime": str(self.rt)}, listener_command=command))

    def test_other_workspace_wins_over_a_proof(self):
        reason = self.evaluate({"workspace": str(self.other_ws)}, listener_command=f"python3 {self.server}")
        self.assertIn("another workspace", reason)

    def test_own_command_beyond_the_first_listener_is_found(self):
        # The first pid on the port is not the server but the second one is: the
        # answer must not depend on numeric pid order. Patch pid_command so the
        # "first" listener resolves to a foreign command and the "second" to the
        # own one.
        original = host_identity.pid_command
        host_identity.pid_command = lambda pid: (
            f"python3 {self.server}" if pid == 22222 else "python3 /elsewhere/other.py"
        )
        try:
            self.assertIsNone(self.evaluate({}, listener_pids=["11111", "22222"]))
        finally:
            host_identity.pid_command = original

    def test_no_listener_is_own_when_none_runs_the_install_server(self):
        original = host_identity.pid_command
        host_identity.pid_command = lambda pid: "python3 /elsewhere/other.py"
        try:
            reason = self.evaluate({}, listener_pids=["11111", "22222"])
        finally:
            host_identity.pid_command = original
        self.assertIn("no identity and no process", reason)


class PidFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_pid_file_is_not_own(self):
        self.assertFalse(host_identity.pid_file_own_server(""))
        self.assertFalse(host_identity.pid_file_own_server(str(self.root / "absent.pid")))

    def test_garbage_pid_file_is_not_own(self):
        pid_file = self.root / "garbage.pid"
        pid_file.write_text("not-a-pid\n")
        self.assertFalse(host_identity.pid_file_own_server(str(pid_file)))

    def test_dead_pid_is_not_own(self):
        pid_file = self.root / "dead.pid"
        pid_file.write_text("999999\n")
        self.assertFalse(host_identity.pid_file_own_server(str(pid_file)))

    def test_a_pid_value_passed_as_a_path_is_not_own(self):
        # The stop_host.sh bug: the helper takes the path of the pid file, never
        # the pid value. A bare number must resolve to "not a pid file", not to
        # a file called "12345".
        self.assertFalse(host_identity.pid_file_own_server("12345"))

    def test_zero_and_negative_pids_are_not_alive(self):
        # os.kill(0, 0) signals the whole process group and os.kill(-1, 0) every
        # signalable process, so both would report "alive" without naming one.
        self.assertFalse(host_identity._pid_alive(0))
        self.assertFalse(host_identity._pid_alive(-1))
        self.assertFalse(host_identity._pid_alive(-12345))

    def test_a_pid_file_with_zero_or_negative_is_not_own(self):
        for value in ("0\n", "-1\n", "\n", "  \n"):
            pid_file = self.root / "odd.pid"
            pid_file.write_text(value)
            self.assertFalse(
                host_identity.pid_file_own_server(str(pid_file)),
                repr(value),
            )


class InstallServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.install = self.root / "install"
        (self.install / "core/skills/solar-app/scripts").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_install_path_matches(self):
        command = f"python3 {self.install}/core/skills/solar-app/scripts/host_server.py"
        self.assertTrue(host_identity.command_is_install_server(command, [str(self.install)]))

    def test_trailing_slash_on_the_root_still_matches(self):
        command = f"python3 {self.install}/core/skills/solar-app/scripts/host_server.py"
        self.assertTrue(host_identity.command_is_install_server(command, [str(self.install) + "/"]))

    def test_other_install_does_not_match(self):
        command = f"python3 {self.install}/core/skills/solar-app/scripts/host_server.py"
        self.assertFalse(host_identity.command_is_install_server(command, [str(self.root / "other")]))

    def test_unrelated_command_does_not_match(self):
        self.assertFalse(host_identity.command_is_install_server("python3 other.py", [str(self.install)]))
        self.assertFalse(host_identity.command_is_install_server("", [str(self.install)]))

    def test_the_path_merely_mentioned_as_an_argument_is_not_own(self):
        # A foreign script that takes our script path as an argument is not our
        # console: the interpreter must be running host_server.py itself.
        command = f"python3 otro.py {self.install}/core/skills/solar-app/scripts/host_server.py"
        self.assertFalse(host_identity.command_is_install_server(command, [str(self.install)]))

    def test_an_interpreter_with_flags_still_matches(self):
        # start_host.sh runs `python3 -u <script>`; the flags must not hide it.
        command = f"python3 -u {self.install}/core/skills/solar-app/scripts/host_server.py"
        self.assertTrue(host_identity.command_is_install_server(command, [str(self.install)]))

    def test_a_quoted_script_path_matches(self):
        command = f"python3 '{self.install}/core/skills/solar-app/scripts/host_server.py'"
        self.assertTrue(host_identity.command_is_install_server(command, [str(self.install)]))

    def test_a_symlinked_install_matches_on_physical_paths(self):
        link = self.root / "install-link"
        link.symlink_to(self.install)
        command = f"python3 {link}/core/skills/solar-app/scripts/host_server.py"
        self.assertTrue(host_identity.command_is_install_server(command, [str(self.install)]))

    def test_a_spaced_install_still_matches_bit_for_bit(self):
        # The "Application Support" layout has spaces: the exact spelling branch
        # is the only one that may carry it.
        spaced = self.root / "Application Support" / "solar"
        (spaced / "core/skills/solar-app/scripts").mkdir(parents=True)
        command = f"python3 {spaced}/core/skills/solar-app/scripts/host_server.py"
        self.assertTrue(host_identity.command_is_install_server(command, [str(spaced)]))
        self.assertFalse(host_identity.command_is_install_server(command, [str(self.install)]))

    def test_a_binary_that_merely_contains_python_is_not_an_interpreter(self):
        # ipython-wrapper / python-my-tool are not the interpreter running the
        # script: the name must be `python` plus optional digits/dots.
        for binary in ("ipython-wrapper", "python-my-tool", "mypython",
                       "python-wrapper", "python3-config"):
            command = f"{binary} {self.install}/core/skills/solar-app/scripts/host_server.py"
            self.assertFalse(
                host_identity.command_is_install_server(command, [str(self.install)]),
                binary,
            )
        for binary in ("python3", "python3.12"):
            command = f"{binary} {self.install}/core/skills/solar-app/scripts/host_server.py"
            self.assertTrue(
                host_identity.command_is_install_server(command, [str(self.install)]),
                binary,
            )

    def test_the_macos_capital_python_and_platform_suffixes_match(self):
        # macOS runs the interpreter as `Python` (Python.app) and a universal
        # build as `python3.12-intel64`; Windows ships `pythonw`. Missing these
        # would strand an own console as foreign.
        for binary in ("Python", "Python3", "python3.12-intel64", "pythonw"):
            command = f"{binary} -u {self.install}/core/skills/solar-app/scripts/host_server.py"
            self.assertTrue(
                host_identity.command_is_install_server(command, [str(self.install)]),
                binary,
            )

    def test_interpreter_flags_with_a_value_do_not_hide_the_interpreter(self):
        # `python3 -X dev <script>`: the value of -X must not be read as the
        # interpreter, or an own hung console launched that way is refused.
        for flags in ("-X dev", "-W ignore", "-X importtime -u"):
            command = f"python3 {flags} {self.install}/core/skills/solar-app/scripts/host_server.py"
            self.assertTrue(
                host_identity.command_is_install_server(command, [str(self.install)]),
                flags,
            )

    def test_joined_and_repeated_flags_stay_flags(self):
        # `-Xdev` carries its value in the same token and `-W ignore -u` chains
        # two flags: neither may push an argument past the interpreter, and the
        # list must not be trimmable without a test breaking.
        for flags in ("-Xdev", "-Wignore", "-Xdev -u", "-W ignore -u", "-u -X dev"):
            command = f"python3 {flags} {self.install}/core/skills/solar-app/scripts/host_server.py"
            self.assertTrue(
                host_identity.command_is_install_server(command, [str(self.install)]),
                flags,
            )

    def test_a_real_argument_after_the_interpreter_is_not_the_interpreter(self):
        # If a non-flag argument sits between the interpreter-looking token and
        # the script, that token is not executing the script: refuse it.
        command = f"something python3 arg {self.install}/core/skills/solar-app/scripts/host_server.py"
        self.assertFalse(
            host_identity.command_is_install_server(command, [str(self.install)]),
            command,
        )


class CliTest(unittest.TestCase):
    """The CLI is what every shell script calls; a dispatch bug is a silent bug."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.install = self.root / "install"
        (self.install / "core/skills/solar-app/scripts").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_command_subcommand_is_dispatched_not_swallowed(self):
        # Regression: --command used to overwrite the subcommand selector, so this
        # call fell through to `evaluate` and raised AttributeError.
        command = f"python3 {self.install}/core/skills/solar-app/scripts/host_server.py"
        rc = host_identity.main([
            "command-is-install-server", "--command", command,
            "--install-root", str(self.install),
        ])
        self.assertEqual(rc, 0)

    def test_command_subcommand_rejects_another_install(self):
        command = f"python3 {self.install}/core/skills/solar-app/scripts/host_server.py"
        rc = host_identity.main([
            "command-is-install-server", "--command", command,
            "--install-root", str(self.root / "other"),
        ])
        self.assertEqual(rc, 1)

    def test_evaluate_subcommand_still_works(self):
        health = self.root / "health.json"
        health.write_text('{"workspace": "/tmp/ws", "runtime": "/tmp/rt"}')
        rc = host_identity.main([
            "evaluate", "--health-file", str(health),
            "--workspace", "/tmp/ws", "--runtime", "/tmp/rt",
        ])
        self.assertEqual(rc, 0)

    def test_evaluate_subcommand_survives_a_corrupt_health_file(self):
        # A malformed payload must not raise a traceback: the run still ends with
        # the `mismatch:` line the contract promises.
        health = self.root / "health.json"
        health.write_text("{not json")
        rc = host_identity.main([
            "evaluate", "--health-file", str(health),
            "--workspace", "/tmp/ws", "--runtime", "/tmp/rt",
        ])
        self.assertEqual(rc, 1)

    def test_evaluate_subcommand_survives_a_missing_health_file(self):
        rc = host_identity.main([
            "evaluate", "--health-file", str(self.root / "absent.json"),
            "--workspace", "/tmp/ws", "--runtime", "/tmp/rt",
        ])
        self.assertEqual(rc, 1)

    def test_evaluate_accepts_a_comma_separated_listener_list(self):
        # The wire format is a list; a pid that is not the first entry still
        # counts, which is the fix this CLI option carries.
        health = self.root / "health.json"
        health.write_text("{}")
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = host_identity.pid_file_own_server
        host_identity.pid_file_own_server = lambda path, pid=None: True
        try:
            rc = host_identity.main([
                "evaluate", "--health-file", str(health),
                "--workspace", "/tmp/ws", "--runtime", "/tmp/rt",
                "--pid-file", str(pid_file),
                "--listener-pids", "424242,%d" % os.getpid(),
            ])
        finally:
            host_identity.pid_file_own_server = original
        self.assertEqual(rc, 0)

    def test_port_listener_pids_returns_the_list_in_numeric_order(self):
        # `lsof -t` can print several pids; they come back numerically sorted, so
        # "999" precedes "1002"/"10000" even though it sorts later as text. The
        # shell applies the same rule with `sort -n -u`.
        shown = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="10000\n999\n1002\n",
        )
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            self.assertEqual(host_identity.port_listener_pids(9000), ["999", "1002", "10000"])

    def test_port_listener_pids_is_empty_without_a_listener(self):
        shown = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            self.assertEqual(host_identity.port_listener_pids(9000), [])

    def test_port_listener_pids_ignores_non_numeric_output(self):
        # A warning line on stdout (not a pid) must not raise, and must not be
        # chosen over a real pid.
        shown = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="lsof: WARNING: can't stat()\n4242\n",
        )
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            self.assertEqual(host_identity.port_listener_pids(9000), ["4242"])

    def test_port_listener_pids_returns_empty_when_only_noise(self):
        shown = subprocess.CompletedProcess(args=[], returncode=0, stdout="lsof: WARNING\n")
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            self.assertEqual(host_identity.port_listener_pids(9000), [])

    def test_port_listener_pids_deduplicates_the_same_pid(self):
        shown = subprocess.CompletedProcess(args=[], returncode=0, stdout="7\n7\n")
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            self.assertEqual(host_identity.port_listener_pids(9000), ["7"])

    def test_port_listener_pids_matches_the_shell_order(self):
        # Parity between the two implementations of the same rule: Python sorts
        # with key=int and the shell with `sort -n -u`. Feed both the identical
        # lsof output and require the identical list, so a change to one that
        # diverges from the other fails here.
        shown = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="100\n99\n1000\n99\n",
        )
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            from_python = host_identity.port_listener_pids(9000)
        from_shell = subprocess.run(
            ["bash", "-c", 'printf "%s\\n" 100 99 1000 99 | sort -n -u'],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        self.assertEqual(from_python, from_shell)


if __name__ == "__main__":
    unittest.main()
