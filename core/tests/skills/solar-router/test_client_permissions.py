"""Client permission checks: static reading of each client's settings and the opt-in probe.

No real client runs: `subprocess.run` is mocked or `ask` is replaced. Settings live in
temporary directories, never in the real home.
"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import client_permissions as cp
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

    def test_allow_rules_for_both_tools_are_ok(self):
        _json(self.home / ".claude" / "settings.json",
              {"permissions": {"allow": ["mcp__solar__solar_search", "mcp__solar__solar_docs"]}})
        self.assertEqual(self.checks(ClaudeProvider())["mcp_read"].status, cp.OK)

    def test_a_server_rule_in_the_workspace_settings_counts(self):
        _json(self.workspace / ".claude" / "settings.local.json", {"permissions": {"allow": ["mcp__solar"]}})
        self.assertEqual(self.checks(ClaudeProvider())["mcp_read"].status, cp.OK)

    def test_no_rule_is_unknown_not_missing_because_the_cause_is_not_assumed(self):
        found = self.checks(ClaudeProvider())["mcp_read"]
        self.assertEqual(found.status, cp.UNKNOWN)
        self.assertIn("probe", found.detail)

    def test_a_deny_rule_is_missing(self):
        _json(self.home / ".claude" / "settings.json", {"permissions": {"deny": ["mcp__solar__solar_search"]}})
        self.assertEqual(self.checks(ClaudeProvider())["mcp_read"].status, cp.MISSING)

    def test_write_guard_is_unknown(self):
        self.assertEqual(self.checks(ClaudeProvider())["write_guard"].status, cp.UNKNOWN)


class TestCodexStatic(Env):
    def config(self, text):
        _write(self.home / ".codex" / "config.toml", text)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_an_automatic_reviewer_with_on_request_is_too_permissive(self):
        self.config('approval_policy = "on-request"\napprovals_reviewer = "guardian_subagent"\n'
                    'sandbox_mode = "workspace-write"\n[mcp_servers.solar]\ncommand = "x"\n')
        found = self.checks(CodexProvider())["write_guard"]
        self.assertEqual(found.status, cp.TOO_PERMISSIVE)
        self.assertEqual(found.setting, "approval_policy")
        self.assertIn('"never"', found.fix)

    @patch.dict("os.environ", {"CODEX_HOME": ""})
    def test_the_workspace_entry_overrides_the_top_level(self):
        self.config('approval_policy = "on-request"\napprovals_reviewer = "guardian_subagent"\n'
                    f'[projects."{self.workspace}"]\napproval_policy = "never"\n')
        self.assertEqual(self.checks(CodexProvider())["write_guard"].status, cp.OK)

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
        self.assertEqual({f.status for f in found.values()}, {cp.UNKNOWN})


class TestContractPerProvider(Env):
    def test_every_client_answers_both_checks_with_a_valid_status(self):
        for cls in PROVIDERS:
            with self.subTest(client=cls.name):
                found = cp.static_checks(cls(), self.home, self.workspace)
                self.assertEqual(sorted(f.check for f in found), sorted(cp.CHECKS))
                for f in found:
                    self.assertIn(f.status, cp.STATUSES)
                    self.assertEqual(f.client, cls.name)

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
        self.assertEqual(sorted(before), sorted(p for p in self.home.rglob("*") if p.is_file()))


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

    def test_claude_probe_names_the_setting_and_file_without_assuming_the_cause(self):
        claude = ClaudeProvider()
        claude.ask = lambda *a, **k: _answer("Plan mode blocked it")
        with patch.object(cp, "audit_has_call", return_value=False):
            found = cp.probe_mcp_read(claude, self.workspace)
        self.assertEqual(found.status, cp.MISSING)
        self.assertEqual(found.setting, "permissions.allow")
        self.assertTrue(found.file.endswith(".claude/settings.json"))
        self.assertIn("mcp__solar__solar_search", found.fix)
        self.assertIn("Plan mode blocked it", found.detail)  # the client's own words, not our guess

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

    def test_audit_evidence_comes_from_the_server_log(self):
        sys.path.insert(0, str(Path(cp.__file__).resolve().parents[2] / "solar-mcp" / "scripts"))
        import mcp_gate  # noqa: F401
        with TemporaryDirectory() as root:
            audit = Path(root) / "audit.jsonl"
            audit.write_text(json.dumps(dict(kind="decision", allowed=True, arguments=dict(query="probe-abc"))) + "\n")
            with patch("mcp_gate.gate_root", return_value=Path(root)):
                self.assertTrue(cp.audit_has_call("probe-abc"))
                self.assertFalse(cp.audit_has_call("probe-other"))


class TestStoreAndSummary(Env):
    def setUp(self):
        super().setUp()
        patcher = patch.object(cp, "store_path", return_value=Path(self._tmp.name) / "client-permissions.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_summary_without_a_probe_says_so_and_flags_a_static_problem(self):
        bad = cp.Finding("agent", "mcp_read", cp.MISSING, fix="x")
        state, detail = cp.summary([bad])
        self.assertEqual(state, "WARN")
        self.assertIn("agent mcp_read missing", detail)
        self.assertIn("probe never run", detail)

    def test_a_stored_probe_is_shown_with_its_age_and_never_runs_a_client(self):
        cp.save_probe([cp.Finding("agent", "mcp_read", cp.OK, "probe"), cp.Finding("agent", "write_guard", cp.OK, "probe")])
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

    def test_age_label(self):
        self.assertEqual(cp.age_label("2026-10-26T00:00:00Z", now=cp.time.mktime((2026, 10, 28, 0, 0, 0, 0, 0, 0)) - cp.time.timezone), "2d ago")
        self.assertEqual(cp.age_label("garbage"), "unknown age")

    def test_finding_rejects_an_invalid_status(self):
        with self.assertRaises(ValueError):
            cp.Finding("agent", "mcp_read", "fine")


if __name__ == "__main__":
    unittest.main()
