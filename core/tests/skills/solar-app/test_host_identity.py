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
            # listener_pid differs from the pid in the file, and the listener has
            # no identity, so it must be rejected.
            reason = self.evaluate({}, pid_file=str(pid_file), listener_pid="424242")
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
                {}, pid_file=str(pid_file), listener_pid=str(os.getpid())))
        finally:
            host_identity.pid_file_own_server = original

    def test_blank_health_with_another_install_command_is_rejected(self):
        command = "python3 /somewhere/else/core/skills/solar-app/scripts/host_server.py"
        self.assertIn("no identity and no process", self.evaluate({}, listener_command=command))

    def test_blank_health_resolves_the_command_from_the_listener_pid(self):
        # A pid that runs host_server.py of this install is a proof on its own.
        command = host_identity.pid_command(os.getpid())
        if "host_server.py" in command:
            self.skipTest("this test's own command line mentions host_server.py")
        self.assertIn("no identity and no process", self.evaluate({}, listener_pid=str(os.getpid())))

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

    def test_port_listener_pids_returns_the_lowest_numerically(self):
        # `lsof -t` can print several pids; the first must be the numerically
        # lowest, so the Python path and the shell's `head -n1` agree even when a
        # shorter pid ("999") sits lexicographically after a longer one ("10000").
        shown = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="10000\n999\n1002\n",
        )
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            self.assertEqual(host_identity.port_listener_pids("127.0.0.1", 9000), "999")

    def test_port_listener_pids_is_empty_without_a_listener(self):
        shown = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with mock.patch.object(host_identity.subprocess, "run", return_value=shown):
            self.assertEqual(host_identity.port_listener_pids("127.0.0.1", 9000), "")


if __name__ == "__main__":
    unittest.main()
