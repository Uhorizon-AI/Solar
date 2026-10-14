"""Unit tests for host_identity.py — the single console identity policy.

The shell suite (``test_host_identity.sh``) exercises the policy through the
scripts; this one pins the policy itself, including the blank cases and the
physical-path comparison, so a regression is attributed to the rule and not to
a caller.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
