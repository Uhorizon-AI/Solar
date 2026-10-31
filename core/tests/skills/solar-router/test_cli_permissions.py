"""CLI permission checks: static reading of each client's settings and the opt-in probe.

No real client runs: `subprocess.run` is mocked or `ask` is replaced. Settings live in
temporary directories, never in the real home.
"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import cli_permissions as cp
from providers.agent import AgentProvider
from providers.agy import AgyProvider
from providers.base import AskResult
from providers.claude import ClaudeProvider
from providers.codex import CodexProvider

PROVIDERS = (ClaudeProvider, CodexProvider, AgentProvider, AgyProvider)


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _json(path: Path, data: dict):
    _write(path, json.dumps(data))


class Env(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.workspace = Path(self._tmp.name) / "workspace"
        self.home.mkdir()
        self.workspace.mkdir()

    def checks(self, provider):
        return {f.check: f for f in cp.static_checks(provider, self.home, self.workspace)}


class TestCursorStatic(Env):
    def config(self, **extra):
        _json(self.home / ".cursor" / "mcp.json", {"mcpServers": {"solar": {}}})
        _json(self.home / ".cursor" / "cli-config.json", dict(approvalMode="allowlist", **extra))

    def test_allowlist_without_solar_entries_is_missing_and_names_the_fix(self):
        self.config(permissions=dict(allow=["Shell(ls)"], deny=[]))
        found = self.checks(AgentProvider())["mcp_read"]
        self.assertEqual(found.status, cp.MISSING)
        self.assertIn("Mcp(solar:solar_search)", found.fix)
        self.assertIn("Mcp(solar:solar_docs)", found.fix)
        self.assertEqual(found.setting, "permissions.allow")
        self.assertTrue(found.file.endswith(".cursor/cli-config.json"))
        self.assertEqual(json.loads(found.snippet)["permissions"]["allow"],
                         ["Mcp(solar:solar_search)", "Mcp(solar:solar_docs)"])

    def test_the_same_config_with_the_entries_added_is_ok(self):
        self.config(permissions=dict(allow=["Shell(ls)", "Mcp(solar:solar_search)", "Mcp(solar:solar_docs)"], deny=[]))
        self.assertEqual(self.checks(AgentProvider())["mcp_read"].status, cp.OK)

    def test_a_server_wildcard_counts(self):
        self.config(permissions=dict(allow=["Mcp(solar:*)"], deny=[]))
        self.assertEqual(self.checks(AgentProvider())["mcp_read"].status, cp.OK)

    def test_a_deny_entry_is_missing_even_with_the_allow_entry(self):
        self.config(permissions=dict(allow=["Mcp(solar:solar_search)", "Mcp(solar:solar_docs)"],
                                     deny=["Mcp(solar:solar_docs)"]))
        found = self.checks(AgentProvider())["mcp_read"]
        self.assertEqual(found.status, cp.MISSING)
        self.assertEqual(found.setting, "permissions.deny")

    def test_a_server_wildcard_in_deny_is_missing(self):
        self.config(permissions=dict(allow=["Mcp(solar:solar_search)", "Mcp(solar:solar_docs)"],
                                     deny=["Mcp(solar:*)"]))
        self.assertEqual(self.checks(AgentProvider())["mcp_read"].status, cp.MISSING)

    def test_a_full_allowlist_with_no_readable_registration_is_unknown(self):
        self.config(permissions=dict(allow=["Mcp(solar:solar_search)", "Mcp(solar:solar_docs)"], deny=[]))
        (self.home / ".cursor" / "mcp.json").unlink()
        self.assertEqual(self.checks(AgentProvider())["mcp_read"].status, cp.UNKNOWN)

    def test_a_workspace_wildcard_deny_names_the_wildcard_and_its_own_file(self):
        self.config(permissions=dict(allow=["Mcp(solar:*)"], deny=[]))
        _json(self.workspace / ".cursor" / "cli.json", dict(permissions=dict(deny=["Mcp(solar:*)"])))
        found = self.checks(AgentProvider())["mcp_read"]
        self.assertEqual(found.status, cp.MISSING)
        self.assertIn("Mcp(solar:*)", found.fix)
        self.assertTrue(found.file.endswith(".cursor/cli.json"))
        self.assertFalse(found.file.startswith(str(self.home)))

    def test_deny_rules_in_two_files_name_each_file(self):
        self.config(permissions=dict(allow=[], deny=["Mcp(solar:solar_docs)"]))
        _json(self.workspace / ".cursor" / "cli.json", dict(permissions=dict(deny=["Mcp(solar:*)"])))
        found = self.checks(AgentProvider())["mcp_read"]
        self.assertIn("cli-config.json", found.file)
        self.assertIn(".cursor/cli.json", found.file)
        self.assertRegex(found.fix, r"Mcp\(solar:solar_docs\).*cli-config\.json.*Mcp\(solar:\*\).*cli\.json")

    def test_the_same_deny_rule_in_two_files_names_both(self):
        self.config(permissions=dict(allow=[], deny=["Mcp(solar:*)"]))
        _json(self.workspace / ".cursor" / "cli.json", dict(permissions=dict(deny=["Mcp(solar:*)"])))
        found = self.checks(AgentProvider())["mcp_read"]
        self.assertIn("cli-config.json", found.file)
        self.assertIn(".cursor/cli.json", found.file)
        self.assertIn("cli-config.json", found.fix)
        self.assertIn(".cursor/cli.json", found.fix)

    def test_null_rule_lists_are_no_rules(self):
        self.config(permissions=dict(allow=None, deny=None))
        self.assertEqual(self.checks(AgentProvider())["mcp_read"].status, cp.MISSING)

    def test_an_approval_mode_that_is_not_modelled_is_unknown(self):
        self.config()
        _json(self.home / ".cursor" / "cli-config.json", dict(approvalMode="something-new"))
        self.assertEqual(self.checks(AgentProvider())["mcp_read"].status, cp.UNKNOWN)

    def test_an_unregistered_server_is_missing(self):
        _json(self.home / ".cursor" / "mcp.json", {"mcpServers": {"other": {}}})
        found = self.checks(AgentProvider())["mcp_read"]
        self.assertEqual(found.status, cp.MISSING)
        self.assertIn("solar mcp install", found.fix)

    def test_write_guard_is_never_claimed_without_the_probe(self):
        self.config(permissions=dict(allow=["Mcp(solar:*)"], deny=[]))
        self.assertEqual(self.checks(AgentProvider())["write_guard"].status, cp.UNKNOWN)


class TestClaudeStatic(Env):
    def setUp(self):
        super().setUp()
        _json(self.home / ".claude.json", {"mcpServers": {"solar": {}}})

    def test_a_server_without_read_only_hints_is_missing_whatever_the_allow_rules_say(self):
        _json(self.home / ".claude" / "settings.json",
              {"permissions": {"allow": ["mcp__solar__solar_search", "mcp__solar__solar_docs"]}})
        with patch("providers.claude.solar_read_tools_declare_read_only", return_value=False):
            found = self.checks(ClaudeProvider())["mcp_read"]
        self.assertEqual(found.status, cp.MISSING)
        self.assertIn("readOnlyHint", found.detail)
        self.assertIn("update Solar", found.fix)

    def test_a_server_with_read_only_hints_leaves_the_rest_to_the_probe(self):
        with patch("providers.claude.solar_read_tools_declare_read_only", return_value=True):
            found = self.checks(ClaudeProvider())["mcp_read"]
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("probe", found.detail)

    def test_a_tool_table_that_cannot_be_read_is_unknown_not_missing(self):
        with patch("providers.claude.solar_read_tools_declare_read_only", return_value=None):
            found = self.checks(ClaudeProvider())["mcp_read"]
        self.assertEqual(found.status, cp.UNKNOWN)

    def test_null_permission_lists_do_not_break_the_check(self):
        _json(self.home / ".claude" / "settings.json", {"permissions": {"allow": None, "deny": None}})
        with patch("providers.claude.solar_read_tools_declare_read_only", return_value=True):
            found = self.checks(ClaudeProvider())["mcp_read"]
        self.assertEqual(found.status, cp.UNKNOWN)

    def test_this_solar_declares_its_read_tools_read_only(self):
        self.assertTrue(cp.solar_read_tools_declare_read_only())

    def test_a_deny_rule_is_missing(self):
        _json(self.home / ".claude" / "settings.json", {"permissions": {"deny": ["mcp__solar__solar_search"]}})
        self.assertEqual(self.checks(ClaudeProvider())["mcp_read"].status, cp.MISSING)

    def test_the_deny_finding_names_the_file_that_holds_the_rule(self):
        _json(self.workspace / ".claude" / "settings.local.json", {"permissions": {"deny": ["mcp__solar"]}})
        found = self.checks(ClaudeProvider())["mcp_read"]
        self.assertEqual(found.status, cp.MISSING)
        self.assertTrue(found.file.endswith("workspace/.claude/settings.local.json"))

    def test_a_server_registered_in_the_local_project_scope_is_registered(self):
        _json(self.home / ".claude.json", {"mcpServers": {}, "projects": {str(self.workspace): {"mcpServers": {"solar": {}}}}})
        with patch("providers.claude.solar_read_tools_declare_read_only", return_value=True):
            found = self.checks(ClaudeProvider())["mcp_read"]
        self.assertNotIn("not registered", found.detail)

    def test_write_guard_is_unknown(self):
        self.assertEqual(self.checks(ClaudeProvider())["write_guard"].status, cp.UNKNOWN)


class TestCodexStatic(Env):
    def config(self, text):
        _write(self.home / ".codex" / "config.toml", text)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_write_guard_is_ok_because_the_ask_command_pins_the_policy(self):
        self.config('approval_policy = "on-request"\napprovals_reviewer = "guardian_subagent"\n'
                    'sandbox_mode = "workspace-write"\n[mcp_servers.solar]\ncommand = "x"\n')
        found = self.checks(CodexProvider())["write_guard"]
        self.assertEqual(found.status, cp.OK)
        self.assertIn('approval_policy="never"', found.detail)

    def test_a_probe_failure_points_at_codex_not_at_config_toml(self):
        hint = CodexProvider().permission_fix_hint("write_guard")
        self.assertIn("-c", hint)
        with patch.object(CodexProvider, "read_only_args", return_value=(["--sandbox", "read-only"], "m")):
            self.assertEqual(cp.fix_for(CodexProvider(), "write_guard")["fix"], hint)

    def test_the_read_only_ask_carries_the_override_before_the_prompt(self):
        flags, mode = CodexProvider().read_only_args(self.workspace)
        self.assertEqual(mode, "--sandbox read-only")
        self.assertEqual(flags[flags.index("-c") + 1], 'approval_policy="never"')
        self.assertIn("read-only", flags)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_without_the_override_write_guard_is_not_claimed(self):
        with patch.object(CodexProvider, "read_only_args", return_value=(["--sandbox", "read-only"], "m")):
            found = self.checks(CodexProvider())["write_guard"]
        self.assertEqual(found.status, cp.UNKNOWN)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_odd_toml_shapes_do_not_raise(self):
        self.config('mcp_servers.solar = "x"\nprojects = "y"\napproval_policy = "never"\n')
        found = self.checks(CodexProvider())
        self.assertEqual(found["write_guard"].status, cp.OK)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_a_missing_tomllib_is_named(self):
        self.config('approval_policy = "never"\n')
        with patch("importlib.util.find_spec", return_value=None), patch("providers.codex.read_toml", return_value=None):
            found = self.checks(CodexProvider())["mcp_read"]
        self.assertIn("Python 3.11", found.detail)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_unregistered_server_is_missing(self):
        self.config('approval_policy = "never"\n')
        self.assertEqual(self.checks(CodexProvider())["mcp_read"].status, cp.MISSING)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_registered_server_is_not_claimed_ok(self):
        self.config('[mcp_servers.solar]\ncommand = "x"\n')
        self.assertEqual(self.checks(CodexProvider())["mcp_read"].status, cp.UNKNOWN)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_no_settings_file_is_unknown(self):
        found = self.checks(CodexProvider())
        self.assertEqual(found["mcp_read"].status, cp.UNKNOWN)
        self.assertEqual(found["write_guard"].status, cp.OK)  # comes from the ask command, not the file


class TestContractPerProvider(Env):
    def test_every_client_answers_both_checks_with_a_valid_status(self):
        for cls in PROVIDERS:
            with self.subTest(client=cls.name):
                found = cp.static_checks(cls(), self.home, self.workspace)
                self.assertEqual(sorted(f.check for f in found), sorted(cp.CHECKS))
                for f in found:
                    self.assertIn(f.status, cp.STATUSES)
                    self.assertEqual(f.cli, cls.name)

    def test_antigravity_has_no_settings_model_so_nothing_is_ok(self):
        self.assertEqual({f.status for f in cp.static_checks(AgyProvider(), self.home, self.workspace)}, {cp.UNKNOWN})

    def test_a_problem_always_names_the_setting_or_the_fix(self):
        _json(self.home / ".cursor" / "mcp.json", {"mcpServers": {"solar": {}}})
        _json(self.home / ".cursor" / "cli-config.json", dict(approvalMode="allowlist", permissions=dict(allow=[])))
        for f in cp.static_checks(AgentProvider(), self.home, self.workspace):
            if f.status in (cp.MISSING, cp.TOO_PERMISSIVE):
                self.assertTrue(f.file and f.fix)

    def test_static_checks_change_nothing_in_the_clients_files(self):
        _json(self.home / ".cursor" / "mcp.json", {"mcpServers": {"solar": {}}})
        _json(self.home / ".cursor" / "cli-config.json", dict(approvalMode="allowlist"))
        _write(self.home / ".codex" / "config.toml", 'approval_policy = "on-request"\n')
        before = {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        for cls in PROVIDERS:
            cp.static_checks(cls(), self.home, self.workspace)
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()})


def _answer(text="DONE"):
    return AskResult("x", text, "mode")


class TestProbe(Env):
    def provider(self, ask):
        provider = AgentProvider()
        provider.ask = ask
        return provider

    def test_read_is_ok_when_the_server_saw_the_call(self):
        seen = []

        def ask(prompt, *, cwd=None, **_):
            seen.append(prompt)
            return _answer()
        with patch.object(cp, "audit_has_call", return_value=True) as audit:
            found = cp.probe_mcp_read(self.provider(ask), self.workspace)
        self.assertEqual((found.status, found.tier), (cp.OK, "probe"))
        self.assertIn(audit.call_args.args[0], seen[0])  # the marker the server is asked about is in the prompt

    def test_read_is_missing_when_the_server_saw_nothing_whatever_the_client_said(self):
        with patch.object(cp, "audit_has_call", return_value=False):
            found = cp.probe_mcp_read(self.provider(lambda *a, **k: _answer("User rejected MCP: solar-solar_search")), self.workspace)
        self.assertEqual(found.status, cp.MISSING)
        self.assertIn("User rejected MCP", found.detail)
        self.assertTrue(found.fix)

    def test_read_is_unknown_without_a_fix_when_the_model_declined_for_a_non_permission_reason(self):
        calls = []

        def ask(prompt, **_):
            calls.append(prompt)
            return _answer("I need to discover the MCP schema with another tool before I can call solar_search.")
        with patch.object(cp, "audit_has_call", return_value=False):
            found = cp.probe_mcp_read(self.provider(ask), self.workspace)
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("discover the MCP schema", found.detail)  # the model's own sentence
        self.assertFalse(found.fix or found.setting or found.snippet)
        self.assertEqual(len(calls), 2)  # retried once before the verdict
        self.assertNotIn("Mcp(", cp.render([found]))

    def test_read_is_ok_when_a_declined_run_is_followed_by_a_successful_retry(self):
        answers = iter(["I cannot call it before reading its schema.", "DONE"])
        markers = []

        def ask(prompt, **_):
            markers.append(prompt)
            return _answer(next(answers))
        # The server sees the call only on the second attempt: the marker of the first one was never sent.
        with patch.object(cp, "audit_has_call", side_effect=lambda marker: marker in markers[-1] and len(markers) == 2):
            found = cp.probe_mcp_read(self.provider(ask), self.workspace)
        self.assertEqual((found.status, found.tier), (cp.OK, "probe"))
        self.assertEqual(len(markers), 2)

    def test_a_denial_is_not_retried(self):
        calls = []

        def ask(prompt, **_):
            calls.append(prompt)
            return _answer("User rejected MCP: solar-solar_search")
        with patch.object(cp, "audit_has_call", return_value=False):
            found = cp.probe_mcp_read(self.provider(ask), self.workspace)
        self.assertEqual((found.status, len(calls)), (cp.MISSING, 1))

    def test_status_does_not_warn_for_a_read_left_unknown_by_a_model_decline(self):
        with TemporaryDirectory() as runtime, patch.object(cp, "store_path", return_value=Path(runtime) / "cp.json"), \
             patch.object(cp, "audit_has_call", return_value=False):
            found = cp.probe_mcp_read(self.provider(lambda *a, **k: _answer("I chose not to call it")), self.workspace)
            cp.save_probe([found])
            static = [cp.Finding("agent", "mcp_read", cp.OK, "static", "allowed")]
            state, _ = cp.summary(static)
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertNotEqual(state, "WARN")

    def test_claude_probe_blocked_in_plan_mode_points_at_solar_not_at_user_settings(self):
        claude = ClaudeProvider()
        claude.ask = lambda *a, **k: _answer("Plan mode blocked it")
        with patch.object(cp, "audit_has_call", return_value=False), \
             patch("providers.claude.solar_read_tools_declare_read_only", return_value=False):
            found = cp.probe_mcp_read(claude, self.workspace)
        self.assertEqual(found.status, cp.MISSING)
        self.assertIn("readOnlyHint", found.setting)
        self.assertIn("Plan mode blocked it", found.detail)  # the client's own words

    def test_agy_blocked_probe_carries_the_documented_rule_as_a_snippet(self):
        agy = AgyProvider()
        agy.ask = lambda *a, **k: _answer("denied")
        with patch.object(cp, "audit_has_call", return_value=False):
            found = cp.probe_mcp_read(agy, self.workspace)
        self.assertIn("mcp(solar/solar_search)", found.snippet)
        self.assertTrue(found.file.endswith("antigravity-cli/settings.json"))

    def test_read_is_unknown_when_the_client_could_not_run(self):
        def ask(*a, **k):
            raise RuntimeError("agent exit 1: not logged in")
        found = cp.probe_mcp_read(self.provider(ask), self.workspace)
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("not logged in", found.detail)

    def test_write_is_too_permissive_when_the_canary_exists(self):
        def ask(prompt, *, cwd=None, **_):
            name = next(w for w in prompt.split() if w.startswith("canary-"))
            (Path(cwd) / name).write_text("canary")
            return _answer()
        self.assertEqual(cp.probe_write_guard(self.provider(ask)).status, cp.TOO_PERMISSIVE)

    def test_write_is_ok_when_nothing_was_created_and_the_scratch_folder_is_removed(self):
        folders = []

        def ask(prompt, *, cwd=None, **_):
            folders.append(Path(cwd))
            return _answer("I cannot write files in this mode")
        self.assertEqual(cp.probe_write_guard(self.provider(ask)).status, cp.OK)
        self.assertFalse(folders[0].exists())

    def test_a_silent_exit_without_a_file_is_ok_only_for_antigravity(self):
        def ask(*a, **k):
            raise RuntimeError("provider returned empty output")
        for cls, expected in ((AgyProvider, cp.OK), (AgentProvider, cp.UNKNOWN),
                              (CodexProvider, cp.UNKNOWN), (ClaudeProvider, cp.UNKNOWN)):
            with self.subTest(client=cls.name):
                provider = cls()
                provider.ask = ask
                self.assertEqual(cp.probe_write_guard(provider).status, expected)

    def test_write_is_unknown_when_the_client_failed_and_nothing_was_written(self):
        def ask(*a, **k):
            raise TimeoutError("timeout")
        self.assertEqual(cp.probe_write_guard(self.provider(ask)).status, cp.UNKNOWN)

    def test_the_probe_runs_the_exact_ask_command_without_write_everything_flags(self):
        proc = MagicMock(returncode=0, stdout="DONE", stderr="")
        for cls in PROVIDERS:
            with self.subTest(client=cls.name), \
                 patch("providers.base.shutil.which", side_effect=lambda b, path=None: f"/bin/{b}"), \
                 patch("providers.base.subprocess.run", return_value=proc) as run, \
                 patch.object(cp, "audit_has_call", return_value=True):
                cp.probe_mcp_read(cls(), self.workspace)
                probe_argv = run.call_args.args[0]
                cls().ask("same", cwd=self.workspace)
                ask_argv = run.call_args.args[0]
            self.assertEqual(probe_argv[:-1], ask_argv[:-1])  # only the prompt differs
            for flag in ("-f", "--force", "--yolo", "--dangerously-skip-permissions", "bypassPermissions"):
                self.assertNotIn(flag, probe_argv)

    def test_an_unreadable_audit_log_is_unknown_not_missing(self):
        sys.path.insert(0, str(Path(cp.__file__).resolve().parents[2] / "solar-mcp" / "scripts"))
        import mcp_gate  # noqa: F401
        with TemporaryDirectory() as root:
            with patch("mcp_gate.gate_root", return_value=Path(root)):
                self.assertFalse(cp.audit_has_call("x"))  # no log: the server saw nothing
            with patch("mcp_gate.gate_root", return_value=Path(root)), \
                 patch.object(Path, "open", side_effect=PermissionError("denied")):
                self.assertIsNone(cp.audit_has_call("x"))
        provider = self.provider(lambda *a, **k: _answer())
        with patch("cli_permissions.audit_has_call", return_value=None):
            self.assertEqual(cp.probe_mcp_read(provider, self.workspace).status, cp.UNKNOWN)

    def test_audit_evidence_comes_from_the_server_log(self):
        sys.path.insert(0, str(Path(cp.__file__).resolve().parents[2] / "solar-mcp" / "scripts"))
        import mcp_gate  # noqa: F401
        with TemporaryDirectory() as root:
            audit = Path(root) / "audit.jsonl"
            audit.write_text(json.dumps(dict(kind="decision", allowed=True, arguments=dict(query="probe-abc"))) + "\n")
            with patch("mcp_gate.gate_root", return_value=Path(root)):
                self.assertTrue(cp.audit_has_call("probe-abc"))
                self.assertFalse(cp.audit_has_call("probe-other"))
                audit.write_text(json.dumps(dict(kind="request", arguments=dict(query="probe-xyz"))) + "\n"
                                 + json.dumps(dict(kind="decision", allowed=True, arguments=dict(query="probe-xyz"))) + "\n")
                self.assertTrue(cp.audit_has_call("probe-xyz"))  # a later decision row counts
                audit.write_text("probe-bad {not json\n"
                                 + json.dumps(dict(kind="decision", allowed=True, arguments=dict(query="probe-bad"))) + "\n")
                self.assertTrue(cp.audit_has_call("probe-bad"))  # a malformed line is skipped, not fatal


class TestDoctorFlags(unittest.TestCase):
    def test_strict_cannot_be_combined_with_the_probe(self):
        import os
        import subprocess
        script = Path(cp.__file__).resolve().parents[2] / "solar-client" / "scripts" / "client_doctor.sh"
        env = {k: v for k, v in os.environ.items() if not k.startswith("SOLAR_")}
        done = subprocess.run(["bash", str(script), "--strict", "--probe-permissions"], capture_output=True,
                              text=True, timeout=60, env=env, cwd="/")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("--strict", done.stderr)


class TestStoreAndSummary(Env):
    def setUp(self):
        super().setUp()
        patcher = patch.object(cp, "store_path", return_value=Path(self._tmp.name) / "cli-permissions.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_summary_without_a_probe_says_so_and_flags_a_static_problem(self):
        bad = cp.Finding("agent", "mcp_read", cp.MISSING, fix="x")
        state, detail = cp.summary([bad])
        self.assertEqual(state, "WARN")
        self.assertIn("agent mcp_read missing", detail)
        self.assertIn("probe never run", detail)

    def test_a_stored_probe_is_shown_with_its_age_and_never_runs_a_client(self):
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.OK, "probe"),
                       cp.Finding("agent", "write_guard", cp.OK, "probe"),
                       cp.Finding("agent", "restricted_reader", cp.OK, "probe")])
        static = [cp.unknown("agent", c, "n/a") for c in cp.CHECKS]
        with patch("providers.base.subprocess.run") as run:
            state, detail = cp.summary(static)
        run.assert_not_called()
        self.assertEqual(state, "OK")
        self.assertIn("just now", detail)

    def test_a_probe_problem_stands_over_a_static_ok(self):
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.MISSING, "probe")])
        state, detail = cp.summary([cp.Finding("agent", "mcp_read", cp.OK)])
        self.assertEqual(state, "WARN")

    def test_unverified_checks_are_info_not_ok(self):
        state, _ = cp.summary([cp.unknown("agy", "mcp_read", "n/a")])
        self.assertEqual(state, "INFO")

    def _cursor_config(self, **extra):
        _json(self.home / ".cursor" / "cli-config.json", dict(approvalMode="allowlist", **extra))

    def test_a_probe_saved_before_a_settings_change_is_stale_not_trusted(self):
        """#95: the stored MISSING came from settings that no longer exist."""
        self._cursor_config(permissions=dict(allow=["Shell(ls)"], deny=[]))
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.MISSING, "probe")], self.home, self.workspace)
        static = [cp.Finding("agent", "mcp_read", cp.OK, "static")]
        self.assertEqual(cp.summary(static, self.home, self.workspace)[0], "WARN")  # unchanged: the verdict stands
        self._cursor_config(permissions=dict(allow=["Mcp(solar:solar_search)"], deny=[]))
        state, detail = cp.summary(static, self.home, self.workspace)
        self.assertEqual(state, "OK")
        self.assertIn("settings changed since the probe", detail)

    def test_a_stale_ok_no_longer_vouches_for_a_check_the_settings_cannot_settle(self):
        self._cursor_config(permissions=dict(allow=[], deny=[]))
        cp.save_probe([cp.Finding("agent", "write_guard", cp.OK, "probe")], self.home, self.workspace)
        static = [cp.unknown("agent", "write_guard", "n/a")]
        self.assertEqual(cp.summary(static, self.home, self.workspace)[0], "OK")
        self._cursor_config(permissions=dict(allow=["Write(*)"], deny=[]))
        state, detail = cp.summary(static, self.home, self.workspace)
        self.assertEqual(state, "INFO")
        self.assertIn("stale", detail)

    def test_a_new_solar_version_makes_the_stored_result_stale(self):
        self._cursor_config()
        with patch.object(cp, "solar_version", return_value="0.1.0"):
            cp.save_probe([cp.Finding("agent", "write_guard", cp.OK, "probe")], self.home, self.workspace)
        static = [cp.unknown("agent", "write_guard", "n/a")]
        with patch.object(cp, "solar_version", return_value="0.2.0"):
            self.assertEqual(cp.summary(static, self.home, self.workspace)[0], "INFO")

    def test_the_fingerprint_ignores_other_clients_and_claude_json_noise(self):
        _json(self.home / ".claude.json", {"mcpServers": {"solar": {}}, "numStartups": 1})
        before = cp.fingerprint("claude", self.home, self.workspace)
        _json(self.home / ".claude.json", {"mcpServers": {"solar": {}}, "numStartups": 2})
        self.assertEqual(cp.fingerprint("claude", self.home, self.workspace), before)
        _json(self.home / ".claude.json", {"mcpServers": {}, "numStartups": 2})
        self.assertNotEqual(cp.fingerprint("claude", self.home, self.workspace), before)
        agent_before = cp.fingerprint("agent", self.home, self.workspace)
        self._cursor_config()
        self.assertNotEqual(cp.fingerprint("agent", self.home, self.workspace), agent_before)
        self.assertEqual(cp.fingerprint("claude", self.home, self.workspace),
                         cp.fingerprint("claude", self.home, self.workspace))

    def test_a_row_stored_before_fingerprints_existed_is_trusted_as_before(self):
        path = cp.store_path()
        _json(path, dict(probed_at="2026-10-01T00:00:00Z",
                         results=[dict(cli="agent", check="mcp_read", status=cp.MISSING, tier="probe")]))
        self.assertEqual(cp.summary([cp.Finding("agent", "mcp_read", cp.OK)], self.home, self.workspace)[0], "WARN")

    def test_age_label_is_independent_of_the_local_timezone_and_daylight_saving(self):
        now = cp.calendar.timegm((2026, 7, 10, 12, 0, 0))
        self.assertEqual(cp.age_label("2026-07-08T12:00:00Z", now=now), "2d ago")
        self.assertEqual(cp.age_label("2026-07-10T11:59:30Z", now=now), "just now")  # a summer stamp stays "just now"
        self.assertEqual(cp.age_label("garbage"), "unknown age")

    def test_a_partial_probe_keeps_the_other_stored_results(self):
        cp.save_probe([cp.Finding("codex", "write_guard", cp.TOO_PERMISSIVE, "probe"),
                       cp.Finding("agent", "mcp_read", cp.OK, "probe")])
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.MISSING, "probe")])
        rows = cp.stored_rows()
        self.assertEqual(rows[("codex", "write_guard")]["status"], cp.TOO_PERMISSIVE)
        self.assertEqual(rows[("agent", "mcp_read")]["status"], cp.MISSING)

    def test_a_probe_saved_before_restricted_reader_is_not_a_failure_or_incomplete(self):
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.OK, "probe"),
                       cp.Finding("agent", "write_guard", cp.OK, "probe")])
        static = [cp.unknown("agent", c, "n/a") for c in cp.CHECKS]
        state, detail = cp.summary(static)
        self.assertEqual(state, "OK")
        self.assertNotIn("unverified", detail)
        self.assertNotIn("missing", detail)
        self.assertNotIn("incomplete", detail)
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.MISSING, "probe"),
                       cp.Finding("agent", "write_guard", cp.OK, "probe")])
        state, detail = cp.summary(static)
        self.assertEqual(state, "WARN")
        self.assertIn("agent mcp_read missing", detail)
        never = [cp.unknown("codex", c, "n/a") for c in cp.CHECKS]
        state, detail = cp.summary(never)
        self.assertEqual(state, "INFO")
        self.assertIn("unverified", detail)

    def test_the_summary_shows_the_age_of_the_oldest_stored_result(self):
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.OK, "probe")])
        path = cp.store_path()
        data = json.loads(path.read_text())
        data["results"][0]["probed_at"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(data))
        cp.save_probe([cp.Finding("agent", "write_guard", cp.OK, "probe")])
        _, detail = cp.summary([cp.unknown("agent", c, "n/a") for c in cp.CHECKS])
        self.assertIn("oldest probe", detail)
        self.assertNotIn("just now", detail)

    def test_finding_rejects_an_invalid_status(self):
        with self.assertRaises(ValueError):
            cp.Finding("agent", "mcp_read", "fine")


class TestRestrictedReaderProbe(Env):
    def test_static_tier_does_not_claim_the_reader_ran(self):
        found = self.checks(AgentProvider())["restricted_reader"]
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("probe", found.detail)

    def test_a_fake_client_that_starts_is_ok(self):
        found = cp.probe_restricted_reader(AgentProvider(), exercise=lambda provider: "restricted reader preflight passed")
        self.assertEqual((found.cli, found.check, found.status, found.tier),
                         ("agent", "restricted_reader", cp.OK, "probe"))
        self.assertIn("preflight passed", found.detail)

    def test_a_fake_client_outside_the_guard_names_the_cause_and_is_not_a_client_setting(self):
        from execution_profiles import ProfileError

        def exercise(provider):
            raise ProfileError("execution_profile_unsupported", detail=dict(
                provider="agent", stage="state", reason="cursor_project_path_outside_write_guard"))

        found = cp.probe_restricted_reader(AgentProvider(), exercise=exercise)
        self.assertEqual(found.status, cp.MISSING)
        self.assertIn("83", found.detail)
        self.assertIn("/tmp/.cursor", found.detail)
        self.assertIn("not a client setting", found.fix)
        self.assertEqual(found.setting, "review private directory")

    def test_a_stale_path_rule_is_unknown_not_a_guard_miss(self):
        from execution_profiles import ProfileError

        def exercise(provider):
            raise ProfileError("execution_profile_unsupported", detail=dict(
                provider="agent", stage="state", reason="cursor_project_path_drift"))

        found = cp.probe_restricted_reader(AgentProvider(), exercise=exercise)
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("83/91", found.detail)
        self.assertEqual(found.fix, "")
        self.assertEqual(found.setting, "")

    def test_an_unknown_bundle_shape_names_the_observer(self):
        from execution_profiles import ProfileError

        def exercise(provider):
            raise ProfileError("execution_profile_unsupported", detail=dict(
                provider="agent", stage="state", reason="cursor_project_path_shape_unknown"))

        found = cp.probe_restricted_reader(AgentProvider(), exercise=exercise)
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("observer", found.detail)
        self.assertIn("not the Cursor install", found.detail)

    def test_a_node_failure_is_unknown_and_names_node(self):
        from execution_profiles import ProfileError

        def exercise(provider):
            raise ProfileError("execution_profile_unsupported", detail=dict(
                provider="agent", stage="state", reason="cursor_project_path_unreadable"))

        found = cp.probe_restricted_reader(AgentProvider(), exercise=exercise)
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("node", found.detail)
        self.assertNotIn("observer", found.detail)

    def test_drift_is_named_before_an_outside_guard_refusal(self):
        from execution_profiles import ProfileError
        import repository_cli_guards as guards
        import repository_reviews as repo

        order = []

        def current(*args, **kwargs):
            order.append("drift")
            raise ProfileError("execution_profile_unsupported", detail=dict(
                provider="agent", stage="state", reason="cursor_project_path_drift"))

        def finish(*args, **kwargs):
            order.append("outside")
            raise ProfileError("execution_profile_unsupported", detail=dict(
                provider="agent", stage="state", reason="cursor_project_path_outside_write_guard"))

        class Agent:
            name = "agent"

            def resolve_binary(self, name):
                return "/usr/bin/false"

        with patch.object(guards, "prepare", return_value=(
                ["/usr/bin/false"], {"CURSOR_DATA_DIR": "/d", "TMPDIR": "/t"})), \
                patch.object(guards, "require_cursor_project_path_current", current), \
                patch.object(guards, "finish_cursor_launch", finish):
            found = cp.probe_restricted_reader(Agent(), exercise=repo._exercise_guarded)
        self.assertEqual(order, ["drift"])
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("83/91", found.detail)
        self.assertNotEqual(found.status, cp.MISSING)

    def test_a_fake_client_that_cannot_start_is_unknown(self):
        from execution_profiles import ProfileError

        def exercise(provider):
            raise ProfileError("execution_profile_unsupported", detail=dict(
                provider="codex", stage="credentials", reason="credentials_unavailable"))

        found = cp.probe_restricted_reader(CodexProvider(), exercise=exercise)
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("credentials_unavailable", found.detail)

    def test_the_probe_does_not_write_the_client_configuration(self):
        config = self.home / ".cursor" / "cli-config.json"
        _json(config, {"approvalMode": "allowlist", "permissions": {"allow": []}})
        before = config.read_bytes()
        cp.probe_restricted_reader(AgentProvider(), exercise=lambda provider: "ok")
        self.assertEqual(config.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
