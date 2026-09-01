"""
Unit tests for providers/*.py — subprocess.run is mocked throughout.
No real AI binaries are called.
"""
import io
import unittest
from unittest.mock import MagicMock, patch

from providers.base import BaseProvider, SOLAR_WORKSPACE, FALLBACK_PATHS
from providers.claude import ClaudeProvider
from providers.codex import CodexProvider
from providers.agy import AgyProvider
from providers.agent import AgentProvider
from providers.ollama import OllamaProvider
from providers import PROVIDERS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_proc(returncode=0, stdout="output", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


# ---------------------------------------------------------------------------
# BaseProvider
# ---------------------------------------------------------------------------

class TestBaseProviderGetCmd(unittest.TestCase):
    def setUp(self):
        self.provider = ClaudeProvider()

    @patch("providers.base.shutil.which")
    def test_returns_cmd_with_prompt(self, mock_which):
        mock_which.return_value = "/usr/bin/claude"
        cmd = self.provider.get_cmd("hello")
        self.assertEqual(cmd[0], "/usr/bin/claude")
        self.assertEqual(cmd[-1], "hello")

    @patch("providers.base.shutil.which")
    def test_env_var_override(self, mock_which):
        mock_which.side_effect = lambda binary, path=None: f"/custom/{binary}"
        with patch.dict("os.environ", {"SOLAR_ROUTER_CLAUDE_CMD": "custom-claude -p"}):
            cmd = self.provider.get_cmd("hi")
        self.assertEqual(cmd[0], "/custom/custom-claude")
        self.assertIn("-p", cmd)
        self.assertEqual(cmd[-1], "hi")

    @patch("providers.base.shutil.which", return_value=None)
    def test_binary_not_found_raises(self, _):
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.get_cmd("hello")
        self.assertIn("client binary not found", str(ctx.exception))

    @patch.dict("os.environ", {"SOLAR_ROUTER_CLAUDE_CMD": ""})
    @patch("providers.base.shutil.which", return_value="/usr/bin/claude")
    def test_empty_env_var_falls_back_to_default(self, mock_which):
        # Empty string → falls back to default_cmd
        cmd = self.provider.get_cmd("hello")
        self.assertEqual(cmd[0], "/usr/bin/claude")

    def test_fallback_paths_include_user_local_bin_for_launchagent(self):
        self.assertIn("/.local/bin", ":".join(FALLBACK_PATHS))


class TestBaseProviderRun(unittest.TestCase):
    def setUp(self):
        self.provider = ClaudeProvider()

    @patch("providers.base.shutil.which", return_value="/usr/bin/claude")
    @patch("providers.base.subprocess.run")
    def test_success_returns_stripped_output(self, mock_run, _):
        mock_run.return_value = _mock_proc(stdout="  hello world  ")
        result = self.provider.run("prompt")
        self.assertEqual(result, "hello world")

    @patch("providers.base.shutil.which", return_value="/usr/bin/false")
    @patch("providers.base.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run, _):
        mock_run.return_value = _mock_proc(returncode=1, stdout="", stderr="crashed")
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.run("prompt")
        self.assertIn("crashed", str(ctx.exception))

    @patch("providers.base.shutil.which", return_value="/usr/bin/claude")
    @patch("providers.base.subprocess.run")
    def test_empty_output_raises(self, mock_run, _):
        mock_run.return_value = _mock_proc(stdout="   ")
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.run("prompt")
        self.assertIn("empty output", str(ctx.exception))

    @patch("providers.base.shutil.which", return_value="/usr/bin/claude")
    @patch("providers.base.subprocess.run")
    def test_uses_repo_root_as_default_cwd(self, mock_run, _):
        mock_run.return_value = _mock_proc()
        self.provider.run("prompt")
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["cwd"], SOLAR_WORKSPACE)


# ---------------------------------------------------------------------------
# AgyProvider
# ---------------------------------------------------------------------------

class TestAgyProvider(unittest.TestCase):
    def setUp(self):
        self.provider = AgyProvider()

    def test_default_cmd_uses_agy(self):
        cmd = self.provider.build_default_cmd()
        self.assertTrue(cmd.startswith("agy -p "))
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn(f"--add-dir {SOLAR_WORKSPACE}", cmd)

    def test_name_is_agy(self):
        self.assertEqual(self.provider.name, "agy")
        self.assertIn("agy", PROVIDERS)
        self.assertNotIn("gemini", PROVIDERS)

    def test_clean_output_strips_ansi(self):
        raw = "\x1b[32mhello\x1b[0m"
        result = self.provider.clean_output(raw)
        self.assertEqual(result, "hello")

    def test_clean_output_detects_oauth_url(self):
        raw = "Please visit the following URL to authorize the application"
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.clean_output(raw)
        self.assertIn("OAuth", str(ctx.exception))

    def test_clean_output_detects_oauth_code_prompt(self):
        raw = "Enter the authorization code:"
        with self.assertRaises(RuntimeError):
            self.provider.clean_output(raw)

    def test_clean_output_detects_quota(self):
        raw = "Error: Individual quota reached. Please upgrade your subscription"
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.clean_output(raw)
        self.assertIn("quota", str(ctx.exception).lower())

    def test_clean_output_passes_clean_text(self):
        result = self.provider.clean_output("normal response")
        self.assertEqual(result, "normal response")


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------

class TestOllamaProvider(unittest.TestCase):
    def setUp(self):
        self.provider = OllamaProvider()

    def test_default_cmd_uses_solar_model(self):
        self.assertEqual(
            self.provider.build_default_cmd(),
            "ollama run solar --hidethinking --nowordwrap",
        )

    def test_clean_output_strips_ansi_and_spinner_noise(self):
        raw = "\x1b[?2026h\x1b[?25l\x1b[1G⠙ \x1b[K\x1b[?25h\x1b[?2026l\nOK\n"
        self.assertEqual(self.provider.clean_output(raw), "OK")

    def test_clean_output_detects_daemon_unavailable(self):
        raw = 'Error: Head "http://127.0.0.1:11434/": dial tcp 127.0.0.1:11434: connect: operation not permitted'
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.clean_output(raw)
        self.assertIn("ollama daemon unavailable", str(ctx.exception))

    @patch("providers.base.shutil.which", return_value="/usr/bin/ollama")
    @patch("providers.ollama.subprocess.run")
    def test_run_normalizes_daemon_error_from_stderr(self, mock_run, _mock_which):
        mock_run.return_value = _mock_proc(
            returncode=1,
            stdout="",
            stderr='Error: Head "http://127.0.0.1:11434/": dial tcp 127.0.0.1:11434: connect: operation not permitted',
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.run("prompt")
        self.assertIn("ollama daemon unavailable", str(ctx.exception))


# ---------------------------------------------------------------------------
# CodexProvider / AgentProvider — dynamic default_cmd
# ---------------------------------------------------------------------------

class TestCodexProvider(unittest.TestCase):
    def test_default_cmd_contains_repo_root(self):
        p = CodexProvider()
        self.assertIn(str(SOLAR_WORKSPACE), p.build_default_cmd())

    def test_default_cmd_contains_skip_git(self):
        p = CodexProvider()
        self.assertIn("--skip-git-repo-check", p.build_default_cmd())

    @patch("providers.codex.subprocess.Popen")
    @patch("providers.base.shutil.which", return_value="/usr/bin/codex")
    def test_stream_adds_json_flag_and_yields_delta(self, _mock_which, mock_popen):
        proc = MagicMock()
        proc.stdout = io.StringIO('{"type":"agent_message.delta","delta":"hi"}\n')
        proc.stderr = io.StringIO("")
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        p = CodexProvider()
        chunks = list(p.stream("prompt"))

        self.assertEqual(chunks, ["hi"])
        cmd = mock_popen.call_args.args[0]
        self.assertIn("--json", cmd)

    @patch("providers.codex.subprocess.Popen")
    @patch("providers.base.shutil.which", return_value="/usr/bin/codex")
    def test_stream_inserts_json_before_separator(self, _mock_which, mock_popen):
        proc = MagicMock()
        proc.stdout = io.StringIO('{"type":"agent_message.delta","delta":"ok"}\n')
        proc.stderr = io.StringIO("")
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        p = CodexProvider()
        with patch.dict(
            "os.environ",
            {
                "SOLAR_ROUTER_CODEX_CMD": (
                    "codex exec --skip-git-repo-check --full-auto -C /tmp "
                    "--add-dir /tmp/.codex --"
                )
            },
            clear=False,
        ):
            chunks = list(p.stream("prompt"))

        self.assertEqual(chunks, ["ok"])
        cmd = mock_popen.call_args.args[0]
        self.assertLess(cmd.index("--json"), cmd.index("--"))

    @patch("providers.codex.subprocess.Popen")
    @patch("providers.base.shutil.which", return_value="/usr/bin/codex")
    def test_stream_uses_completed_fallback_when_no_deltas(self, _mock_which, mock_popen):
        proc = MagicMock()
        proc.stdout = io.StringIO('{"type":"turn.completed","result":"final answer"}\n')
        proc.stderr = io.StringIO("")
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        p = CodexProvider()
        chunks = list(p.stream("prompt"))

        self.assertEqual(chunks, ["final answer"])

    @patch("providers.codex.subprocess.Popen")
    @patch("providers.base.shutil.which", return_value="/usr/bin/codex")
    def test_stream_reads_nested_item_text(self, _mock_which, mock_popen):
        proc = MagicMock()
        proc.stdout = io.StringIO(
            '{"type":"item.completed","item":{"type":"agent_message","text":"nested text"}}\n'
        )
        proc.stderr = io.StringIO("")
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        p = CodexProvider()
        chunks = list(p.stream("prompt"))

        self.assertEqual(chunks, ["nested text"])

    @patch("providers.codex.subprocess.Popen")
    @patch("providers.base.shutil.which", return_value="/usr/bin/codex")
    def test_stream_uses_last_buffered_item_message_only(self, _mock_which, mock_popen):
        proc = MagicMock()
        proc.stdout = io.StringIO(
            '{"type":"item.completed","item":{"type":"agent_message","text":"thinking..."}}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"final answer"}}\n'
            '{"type":"turn.completed"}\n'
        )
        proc.stderr = io.StringIO("")
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        p = CodexProvider()
        chunks = list(p.stream("prompt"))

        self.assertEqual(chunks, ["final answer"])

    @patch("providers.codex.subprocess.Popen")
    @patch("providers.base.shutil.which", return_value="/usr/bin/codex")
    def test_stream_captures_usage_from_turn_completed(self, _mock_which, mock_popen):
        proc = MagicMock()
        proc.stdout = io.StringIO(
            '{"type":"item.completed","item":{"type":"agent_message","text":"final"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2,"cached_input_tokens":3}}\n'
        )
        proc.stderr = io.StringIO("")
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        p = CodexProvider()
        chunks = list(p.stream("prompt"))

        self.assertEqual(chunks, ["final"])
        self.assertEqual(
            p.last_usage,
            {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 3},
        )

    @patch("providers.codex.subprocess.Popen")
    @patch("providers.base.shutil.which", return_value="/usr/bin/codex")
    def test_stream_debug_logs_unknown_event_once(self, _mock_which, mock_popen):
        proc = MagicMock()
        proc.stdout = io.StringIO(
            '{"type":"custom.unknown","foo":"a"}\n'
            '{"type":"custom.unknown","foo":"b"}\n'
            '{"type":"turn.completed","result":"done"}\n'
        )
        proc.stderr = io.StringIO("")
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        p = CodexProvider()
        with patch.dict("os.environ", {"SOLAR_ROUTER_CODEX_DEBUG_EVENTS": "1"}):
            with patch("providers.codex.print") as mock_print:
                chunks = list(p.stream("prompt"))

        self.assertEqual(chunks, ["done"])
        self.assertEqual(mock_print.call_count, 1)


class TestAgentProvider(unittest.TestCase):
    def test_default_cmd_contains_repo_root(self):
        p = AgentProvider()
        self.assertIn(str(SOLAR_WORKSPACE), p.build_default_cmd())

    def test_default_cmd_contains_approve_mcps(self):
        p = AgentProvider()
        self.assertIn("--approve-mcps", p.build_default_cmd())


# ---------------------------------------------------------------------------
# ClaudeProvider
# ---------------------------------------------------------------------------

class TestClaudeProvider(unittest.TestCase):
    def test_default_cmd_is_static(self):
        p = ClaudeProvider()
        self.assertIn("bypassPermissions", p.default_cmd)
        self.assertIn("--no-session-persistence", p.default_cmd)

    def test_name(self):
        self.assertEqual(ClaudeProvider().name, "claude")


if __name__ == "__main__":
    unittest.main()
