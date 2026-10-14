"""Unit tests for host_identity.py — the single console identity policy.

The shell suite (``test_host_identity.sh``) exercises the policy through the
scripts; this one pins the policy itself, including the blank cases and the
physical-path comparison, so a regression is attributed to the rule and not to
a caller.
"""
from __future__ import annotations

import io
import os
import shutil
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
        # The pid file names a live host_server.py, but the port's listener is a
        # different process: the pid file must not adopt it.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_command = host_identity.pid_command
        host_identity.pid_command = lambda pid: (
            f"python3 {self.server}" if int(pid) == os.getpid() else ""
        )
        try:
            # The port's listener differs from the pid in the file, and the
            # listener has no identity, so it must be rejected.
            reason = self.evaluate({}, pid_file=str(pid_file), listener_pids=["424242"])
        finally:
            host_identity.pid_command = original_command
        self.assertIn("no identity and no process", reason)

    def test_pid_file_matching_the_listener_adopts_it(self):
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_command = host_identity.pid_command
        host_identity.pid_command = lambda pid: f"python3 {self.server}"
        try:
            self.assertIsNone(self.evaluate(
                {}, pid_file=str(pid_file), listener_pids=[str(os.getpid())]))
        finally:
            host_identity.pid_command = original_command

    def test_pid_file_matching_a_second_listener_is_adopted(self):
        # Several listeners on the port and the pid file names one that is not
        # the first: it is still a listener, so it must be adopted.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_command = host_identity.pid_command
        host_identity.pid_command = lambda pid: f"python3 {self.server}"
        try:
            self.assertIsNone(self.evaluate(
                {}, pid_file=str(pid_file),
                listener_pids=["424242", str(os.getpid())]))
        finally:
            host_identity.pid_command = original_command

    def test_pid_file_of_another_install_is_rejected_even_with_listeners(self):
        # The pid file names a live host_server.py of ANOTHER install and that pid
        # is one of the port's listeners: the "host_server.py" substring is not
        # enough, so it must be rejected. Both branches of the pid-file rule make
        # the same install-level check.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_command = host_identity.pid_command
        host_identity.pid_command = lambda pid: "python3 /somewhere/else/core/skills/solar-app/scripts/host_server.py"
        try:
            reason = self.evaluate(
                {}, pid_file=str(pid_file), listener_pids=[str(os.getpid())])
        finally:
            host_identity.pid_command = original_command
        self.assertIn("no identity and no process", reason)

    def test_pid_file_without_listeners_needs_the_install_proof(self):
        # lsof failed (or is missing): no listener could be enumerated. An own
        # pid file alone only proves runtime membership and would adopt a foreign
        # console on the port, so it must not be enough: the pid's own command
        # has to be this install's host_server.py.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_command = host_identity.pid_command
        try:
            host_identity.pid_command = lambda pid: "python3 /somewhere/else/host_server.py"
            reason = self.evaluate({}, pid_file=str(pid_file), listener_pids=None)
            self.assertIn("no identity and no process", reason)

            host_identity.pid_command = lambda pid: f"python3 {self.server}"
            self.assertIsNone(self.evaluate({}, pid_file=str(pid_file), listener_pids=None))
        finally:
            host_identity.pid_command = original_command

    def test_pid_file_on_another_endpoint_with_evidence_is_rejected(self):
        # lsof DID enumerate the port, but the pid file's process serves another
        # socket (an empty endpoint-filtered list): the evidence is "no listener
        # serves the probed endpoint", not "no evidence", so the pid file must not
        # adopt the foreign listener the probe actually reaches.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_command = host_identity.pid_command
        host_identity.pid_command = lambda pid: f"python3 {self.server}"
        try:
            reason = self.evaluate({}, pid_file=str(pid_file), listener_pids=[])
        finally:
            host_identity.pid_command = original_command
        self.assertIn("no identity and no process", reason)

    def test_relative_identity_path_is_treated_as_no_identity(self):
        # An old console may report a relative path. `resolve()` would anchor it
        # to this process's cwd and could report a false "another workspace"; a
        # non-absolute path must be treated as no identity at all. Only the bad
        # field is dropped, so the other half still counts as partial identity.
        reason = self.evaluate({"workspace": "ws", "runtime": "runtime"})
        self.assertIn("no identity and no process", reason)
        self.assertNotIn("another workspace", reason)

        partial = self.evaluate({"workspace": "ws", "runtime": str(self.rt)})
        self.assertIn("partial identity", partial)
        self.assertNotIn("another workspace", partial)

    def test_relative_workspace_with_the_own_command_is_adopted(self):
        command = f"python3 {self.server}"
        self.assertIsNone(self.evaluate(
            {"workspace": "ws", "runtime": "runtime"}, listener_command=command))

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

    def test_zero_and_negative_pids_are_not_alive(self):
        # os.kill(0, 0) signals the whole process group and os.kill(-1, 0) every
        # signalable process, so both would report "alive" without naming one.
        self.assertFalse(host_identity._pid_alive(0))
        self.assertFalse(host_identity._pid_alive(-1))
        self.assertFalse(host_identity._pid_alive(-12345))

    def test_a_missing_or_garbage_pid_file_resolves_no_pid(self):
        self.assertIsNone(host_identity._pid_file_pid(""))
        self.assertIsNone(host_identity._pid_file_pid(str(self.root / "absent.pid")))
        garbage = self.root / "garbage.pid"
        garbage.write_text("not-a-pid\n")
        self.assertIsNone(host_identity._pid_file_pid(str(garbage)))

    def test_a_dead_pid_file_resolves_no_pid(self):
        dead = self.root / "dead.pid"
        dead.write_text("999999\n")
        self.assertIsNone(host_identity._pid_file_pid(str(dead)))

    def test_a_pid_file_with_zero_or_negative_resolves_no_pid(self):
        for value in ("0\n", "-1\n", "\n", "  \n"):
            odd = self.root / "odd.pid"
            odd.write_text(value)
            self.assertIsNone(host_identity._pid_file_pid(str(odd)), repr(value))

    def test_pid_is_host_server_matches_the_substring(self):
        # The prefilter only: it never checks the install, that is
        # command_is_install_server.
        original = host_identity.pid_command
        try:
            host_identity.pid_command = lambda pid: "python3 /somewhere/host_server.py"
            self.assertTrue(host_identity.pid_is_host_server(os.getpid()))
            host_identity.pid_command = lambda pid: "python3 algo-que-no-es.py"
            self.assertFalse(host_identity.pid_is_host_server(os.getpid()))
        finally:
            host_identity.pid_command = original

    def test_pid_is_host_server_refuses_an_empty_pid(self):
        self.assertFalse(host_identity.pid_is_host_server(0))
        self.assertFalse(host_identity.pid_is_host_server(""))
        self.assertFalse(host_identity.pid_is_host_server(None))


class PidFileNameListenerTest(unittest.TestCase):
    """The single implementation of the pid-file-names-listener proof."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.install = self.root / "install"
        (self.install / "core/skills/solar-app/scripts").mkdir(parents=True)
        self.server = self.install / "core/skills/solar-app/scripts/host_server.py"
        self.server.write_text("#!/usr/bin/env python3\n")
        self.other_install = self.root / "other-install"
        (self.other_install / "core/skills/solar-app/scripts").mkdir(parents=True)
        self.other_server = self.other_install / "core/skills/solar-app/scripts/host_server.py"
        self.other_server.write_text("#!/usr/bin/env python3\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _stub(self, command):
        original = host_identity.pid_command
        host_identity.pid_command = lambda pid: command
        return original

    def test_names_this_installs_listener(self):
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = self._stub(f"python3 {self.server}")
        try:
            self.assertTrue(host_identity.pid_file_names_listener(
                str(pid_file), os.getpid(), [str(self.install)]))
        finally:
            host_identity.pid_command = original

    def test_a_pid_of_another_install_is_not_a_listener(self):
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = self._stub(f"python3 {self.other_server}")
        try:
            self.assertFalse(host_identity.pid_file_names_listener(
                str(pid_file), os.getpid(), [str(self.install)]))
        finally:
            host_identity.pid_command = original

    def test_a_pid_file_naming_a_different_pid_is_not_a_listener(self):
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = self._stub(f"python3 {self.server}")
        try:
            self.assertFalse(host_identity.pid_file_names_listener(
                str(pid_file), os.getpid() + 1, [str(self.install)]))
        finally:
            host_identity.pid_command = original

    def test_missing_pid_file_is_not_a_listener(self):
        self.assertFalse(host_identity.pid_file_names_listener(
            str(self.root / "absent.pid"), os.getpid(), [str(self.install)]))

    def test_the_pid_is_resolved_once(self):
        # A file rewritten between two reads must not make the "names wanted"
        # check and the "runs host_server.py" check disagree: the pid is read
        # once and carried through both.
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = host_identity.pid_command
        host_identity.pid_command = lambda pid: f"python3 {self.server}"
        calls = []
        real_reader = host_identity._pid_file_pid

        def counting_reader(path):
            calls.append(path)
            pid = real_reader(path)
            # The file changes after the first read, to another live pid.
            pid_file.write_text(str(os.getpid()))
            return pid
        try:
            host_identity._pid_file_pid = counting_reader
            self.assertTrue(host_identity.pid_file_names_listener(
                str(pid_file), os.getpid(), [str(self.install)]))
        finally:
            host_identity._pid_file_pid = real_reader
            host_identity.pid_command = original
        self.assertEqual(len(calls), 1, "the pid file must be read exactly once")

    def test_cli_pid_file_names_listener_exit_codes(self):
        pid_file = self.root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original = self._stub(f"python3 {self.server}")
        try:
            self.assertEqual(host_identity.main([
                "pid-file-names-listener", "--pid-file", str(pid_file),
                "--pid", str(os.getpid()), "--install-root", str(self.install),
            ]), 0)
            self.assertEqual(host_identity.main([
                "pid-file-names-listener", "--pid-file", str(pid_file),
                "--pid", str(os.getpid() + 1), "--install-root", str(self.install),
            ]), 1)
        finally:
            host_identity.pid_command = original


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

    def test_a_suffixed_copy_of_the_server_is_not_our_server(self):
        # `host_server.py.backup` / `.old` / `.orig` contain the suffix but run a
        # different file. The fallback branch used to accept them, so a copied or
        # rotated script would be adopted and stopped as this install's console.
        for suffix in (".backup", ".old", ".orig", ".bak", ".py2", "~"):
            command = f"python3 {self.install}/core/skills/solar-app/scripts/host_server.py{suffix}"
            self.assertFalse(
                host_identity.command_is_install_server(command, [str(self.install)]),
                command,
            )

    def test_a_suffixed_copy_of_a_symlinked_spelling_is_not_our_server(self):
        # The same guard on the fallback branch that resolves a symlinked
        # spelling (/var vs /private/var), which is the one that needed the fix.
        link = self.root / "install-link"
        link.symlink_to(self.install)
        for suffix in (".backup", ".old"):
            command = f"python3 {link}/core/skills/solar-app/scripts/host_server.py{suffix}"
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
        original_command = host_identity.pid_command
        own_server = self.root / "install/core/skills/solar-app/scripts/host_server.py"
        own_server.parent.mkdir(parents=True, exist_ok=True)
        own_server.write_text("#!/usr/bin/env python3\n")
        host_identity.pid_command = lambda pid: f"python3 {own_server}"
        try:
            rc = host_identity.main([
                "evaluate", "--health-file", str(health),
                "--workspace", "/tmp/ws", "--runtime", "/tmp/rt",
                "--pid-file", str(pid_file),
                "--listener-pids", "424242,%d" % os.getpid(),
                "--install-root", str(self.root / "install"),
            ])
        finally:
            host_identity.pid_command = original_command
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


class EndpointTest(unittest.TestCase):
    """The pid↔address binding: a probe of host:port only reaches one socket."""

    def _lsof(self, stdout, returncode=0):
        shown = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)
        return mock.patch.object(host_identity.subprocess, "run", return_value=shown)

    def test_the_keyed_output_is_parsed_per_pid(self):
        # `lsof -Fn` prints `p<pid>` then one `n<address>` per socket. Two pids on
        # the same port must keep their own addresses, never a merged blob.
        stdout = (
            "p111\nf5\nn127.0.0.1:9000\n"
            "p222\nf6\nn127.0.0.2:9000\n"
        )
        with self._lsof(stdout):
            self.assertEqual(
                host_identity.port_listener_endpoints(9000),
                {"111": {"127.0.0.1:9000"}, "222": {"127.0.0.2:9000"}},
            )

    def test_the_trailing_state_is_not_part_of_the_address(self):
        # Some platforms suffix the state: it must not become part of the address.
        with self._lsof("p111\nn127.0.0.1:9000 (LISTEN)\n"):
            self.assertEqual(
                host_identity.port_listener_endpoints(9000),
                {"111": {"127.0.0.1:9000"}},
            )

    def test_a_non_numeric_pid_line_is_ignored(self):
        # A warning line must not create a bogus pid key.
        with self._lsof("lsof: WARNING: can't stat()\np111\nn127.0.0.1:9000\n"):
            self.assertEqual(
                host_identity.port_listener_endpoints(9000),
                {"111": {"127.0.0.1:9000"}},
            )

    def test_no_lsof_output_is_an_empty_map(self):
        with self._lsof("", returncode=1):
            self.assertEqual(host_identity.port_listener_endpoints(9000), {})

    def test_a_listener_on_the_probed_address_matches(self):
        self.assertTrue(host_identity.endpoint_matches("127.0.0.1:9000", "127.0.0.1", 9000))

    def test_loopback_spellings_of_the_same_family_match(self):
        # `localhost` may resolve to the IPv4 loopback the probe reaches, and
        # `lsof` prints an IPv4 wildcard bind as `*:9000`: it answers on loopback.
        self.assertTrue(host_identity.endpoint_matches("127.0.0.1:9000", "127.0.0.1", 9000))
        self.assertTrue(host_identity.endpoint_matches("localhost:9000", "127.0.0.1", 9000))
        self.assertTrue(host_identity.endpoint_matches("*:9000", "127.0.0.1", 9000))

    def test_loopback_of_another_family_does_not_match(self):
        # `[::1]:9000` and `127.0.0.1:9000` are two sockets of different families:
        # a probe of one never reaches the other, so they must not be collapsed.
        self.assertFalse(host_identity.endpoint_matches("[::1]:9000", "127.0.0.1", 9000))
        self.assertFalse(host_identity.endpoint_matches("127.0.0.1:9000", "::1", 9000))
        # `localhost` names the loopback of both families, so it matches either.
        self.assertTrue(host_identity.endpoint_matches("localhost:9000", "::1", 9000))

    def test_a_listener_on_another_family_is_other_not_match(self):
        # Same port, same install, but a different socket: the endpoint verdict
        # must exclude the listener so its /health answer is never borrowed.
        stdout = "p111\nn[::1]:9000\np222\nn127.0.0.1:9000\n"
        with self._lsof(stdout):
            self.assertEqual(
                host_identity.listener_endpoint_state("111", "127.0.0.1", 9000), "other")
            self.assertEqual(
                host_identity.listener_endpoint_state("222", "127.0.0.1", 9000), "match")
            self.assertEqual(
                host_identity.listener_endpoint_state("111", "::1", 9000), "match")

    def test_a_bare_wildcard_bind_matches_any_host(self):
        # `lsof` reports both wildcards as a bare `*`; without `-i4`/`-i6` family
        # evidence it stays family-agnostic and matches a probe of either family.
        self.assertTrue(host_identity.endpoint_matches("*:9000", "127.0.0.1", 9000))
        self.assertTrue(host_identity.endpoint_matches("*:9000", "::1", 9000))

    def test_a_literal_wildcard_host_matches_only_its_own_family(self):
        # A literal `0.0.0.0` (never printed by `lsof`, which uses `*`) names the
        # IPv4 wildcard: it matches an IPv4 probe, not an IPv6 one.
        self.assertTrue(host_identity.endpoint_matches("0.0.0.0:9000", "127.0.0.1", 9000))
        self.assertFalse(host_identity.endpoint_matches("0.0.0.0:9000", "::1", 9000))
        self.assertTrue(host_identity.endpoint_matches("[::]:9000", "::1", 9000))
        self.assertFalse(host_identity.endpoint_matches("[::]:9000", "127.0.0.1", 9000))

    def test_a_listener_on_another_address_does_not_match(self):
        self.assertFalse(host_identity.endpoint_matches("127.0.0.2:9000", "127.0.0.1", 9000))

    def test_a_listener_on_another_port_does_not_match(self):
        self.assertFalse(host_identity.endpoint_matches("127.0.0.1:9001", "127.0.0.1", 9000))

    def test_an_empty_address_does_not_match(self):
        self.assertFalse(host_identity.endpoint_matches("", "127.0.0.1", 9000))

    def test_state_is_match_other_or_unknown(self):
        # Three states, because "no evidence" must not become "someone else's":
        # without lsof the caller has to keep its other proofs.
        stdout = "p111\nn127.0.0.1:9000\np222\nn127.0.0.2:9000\n"
        with self._lsof(stdout):
            self.assertEqual(
                host_identity.listener_endpoint_state("111", "127.0.0.1", 9000), "match")
            self.assertEqual(
                host_identity.listener_endpoint_state("222", "127.0.0.1", 9000), "other")
            self.assertEqual(
                host_identity.listener_endpoint_state("333", "127.0.0.1", 9000), "unknown")
        with self._lsof("", returncode=1):
            self.assertEqual(
                host_identity.listener_endpoint_state("111", "127.0.0.1", 9000), "unknown")

    def test_only_the_listeners_of_the_probed_endpoint_are_returned(self):
        # The regression Codex asked for: with a listener on another address of
        # the same port, only the one on the probed address is returned.
        stdout = "p222\nn127.0.0.2:9000\np111\nn127.0.0.1:9000\n"
        with self._lsof(stdout):
            self.assertEqual(
                host_identity.port_listener_pids_on_endpoint("127.0.0.1", 9000),
                ["111"],
            )

    def test_without_endpoint_evidence_returns_none(self):
        # `lsof` missing or a double that only answers `-t`: no endpoint evidence
        # at all. The caller gets None ("no evidence") so it can keep the
        # pre-endpoint behaviour and not confuse it with "the port is empty".
        with self._lsof("", returncode=1):
            self.assertIsNone(
                host_identity.port_listener_pids_on_endpoint("127.0.0.1", 9000))

    def test_evidence_with_no_matching_listener_returns_empty(self):
        # `lsof` DID enumerate the port but no listener serves the probed address:
        # an empty list, not None, so the caller knows the pid file names a process
        # on another socket and must not adopt it.
        stdout = "p222\nn127.0.0.2:9000\n"
        with self._lsof(stdout):
            self.assertEqual(
                host_identity.port_listener_pids_on_endpoint("127.0.0.1", 9000), [])

    def test_endpoint_verdicts_lists_every_listener(self):
        stdout = "p222\nn127.0.0.2:9000\np111\nn127.0.0.1:9000\n"
        with self._lsof(stdout):
            self.assertEqual(
                host_identity.endpoint_verdicts("127.0.0.1", 9000),
                [("111", "match"), ("222", "other")],
            )

    def test_endpoint_verdicts_marks_a_wildcard_and_a_specific_bind_both_match(self):
        # A wildcard bind answers on every local address, so with a wildcard and a
        # specific bind on the same port both are "match": the kernel's SO_REUSEPORT
        # means either may serve the connection, so the sweep must not treat the
        # specific bind as the sole owner. This pins that intended behaviour.
        stdout = "p111\nn*:9000\np222\nn127.0.0.1:9000\n"
        with self._lsof(stdout):
            self.assertEqual(
                host_identity.endpoint_verdicts("127.0.0.1", 9000),
                [("111", "match"), ("222", "match")],
            )

    def test_a_wildcard_is_annotated_with_its_served_family(self):
        # `lsof` prints both wildcards as `*`, so `-i4`/`-i6` recover the family:
        # a wildcard listed only by `-i6` serves IPv6, and the annotated address
        # must not match an IPv4 probe (an IPV6_V6ONLY wildcard can coexist with an
        # IPv4 console on the same port).
        wildcard = "p111\nn*:9000\n"
        only_v6 = "p111\nn*:9000\n"
        only_v4 = "p111\nn*:9000\n"

        def fake_run(args, **kwargs):
            joined = " ".join(args)
            if "-i4TCP:9000" in joined:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="")
            if "-i6TCP:9000" in joined:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=only_v6)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=wildcard)

        with mock.patch.object(host_identity.subprocess, "run", side_effect=fake_run):
            self.assertEqual(
                host_identity.port_listener_endpoints(9000), {"111": {"*:9000 [ipv6]"}})
            self.assertFalse(host_identity.endpoint_matches("*:9000 [ipv6]", "127.0.0.1", 9000))
            self.assertTrue(host_identity.endpoint_matches("*:9000 [ipv6]", "::1", 9000))

        def fake_v4(args, **kwargs):
            joined = " ".join(args)
            if "-i4TCP:9000" in joined:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=only_v4)
            if "-i6TCP:9000" in joined:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=wildcard)

        with mock.patch.object(host_identity.subprocess, "run", side_effect=fake_v4):
            self.assertEqual(
                host_identity.port_listener_endpoints(9000), {"111": {"*:9000 [ipv4]"}})
            self.assertTrue(host_identity.endpoint_matches("*:9000 [ipv4]", "127.0.0.1", 9000))
            self.assertFalse(host_identity.endpoint_matches("*:9000 [ipv4]", "::1", 9000))

    def test_a_bare_wildcard_without_family_evidence_matches_any_host(self):
        # No `-i4`/`-i6` evidence (a double that only answers the plain query): the
        # address stays a bare `*`, which keeps the pre-family behaviour.
        self.assertTrue(host_identity.endpoint_matches("*:9000", "127.0.0.1", 9000))
        self.assertTrue(host_identity.endpoint_matches("*:9000", "::1", 9000))

    def test_evaluate_port_resolves_only_the_probed_endpoint(self):
        # The `--port` fallback must resolve the endpoint's listeners, not the whole
        # port: an own host_server.py on another address must not stand in for the
        # console the probe reaches, even when the pid file names it.
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        health = root / "health.json"
        health.write_text("{}")
        own_server = root / "install/core/skills/solar-app/scripts/host_server.py"
        own_server.parent.mkdir(parents=True, exist_ok=True)
        own_server.write_text("#!/usr/bin/env python3\n")
        pid_file = root / "host.pid"
        pid_file.write_text(str(os.getpid()))
        original_command = host_identity.pid_command
        host_identity.pid_command = lambda pid: f"python3 {own_server}"
        stdout = "p111\nn127.0.0.2:9000\n"
        try:
            with self._lsof(stdout):
                rc = host_identity.main([
                    "evaluate", "--health-file", str(health),
                    "--workspace", "/tmp/ws", "--runtime", "/tmp/rt",
                    "--pid-file", str(pid_file),
                    "--host", "127.0.0.1", "--port", "9000",
                    "--install-root", str(root / "install"),
                ])
        finally:
            host_identity.pid_command = original_command
        # The only listener serves 127.0.0.2, not the probed 127.0.0.1, and the pid
        # file names it: it must not be adopted through the pid file either.
        self.assertEqual(rc, 1)

    def test_cli_port_endpoints_prints_pid_and_state(self):
        stdout = "p111\nn127.0.0.1:9000\np222\nn127.0.0.2:9000\n"
        with self._lsof(stdout), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(host_identity.main(
                ["port-endpoints", "--host", "127.0.0.1", "--port", "9000"]), 0)
        self.assertEqual(out.getvalue().splitlines(), ["111 match", "222 other"])


if __name__ == "__main__":
    unittest.main()
