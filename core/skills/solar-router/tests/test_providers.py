"""
Unit tests for providers/*.py — subprocess.run is mocked throughout.
No real AI binaries are called.
"""
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure scripts/ is importable
_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from providers.base import BaseProvider, REPO_ROOT, FALLBACK_PATHS
from providers.claude import ClaudeProvider
from providers.codex import CodexProvider
from providers.gemini import GeminiProvider
from providers.agent import AgentProvider


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
    def test_uses_repo_root_as_cwd(self, mock_run, _):
        mock_run.return_value = _mock_proc()
        self.provider.run("prompt")
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["cwd"], REPO_ROOT)


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------

class TestGeminiProvider(unittest.TestCase):
    def setUp(self):
        self.provider = GeminiProvider()

    def test_prepare_env_sets_gemini_vars(self):
        env = self.provider.prepare_env({})
        self.assertIn("GEMINI_CLI_HOME", env)
        self.assertEqual(env["GEMINI_FORCE_ENCRYPTED_FILE_STORAGE"], "false")

    def test_prepare_env_does_not_overwrite_existing(self):
        env = self.provider.prepare_env({"GEMINI_CLI_HOME": "/custom"})
        self.assertEqual(env["GEMINI_CLI_HOME"], "/custom")

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

    def test_clean_output_passes_clean_text(self):
        result = self.provider.clean_output("normal response")
        self.assertEqual(result, "normal response")


# ---------------------------------------------------------------------------
# CodexProvider / AgentProvider — dynamic default_cmd
# ---------------------------------------------------------------------------

class TestCodexProvider(unittest.TestCase):
    def test_default_cmd_contains_repo_root(self):
        p = CodexProvider()
        self.assertIn(str(REPO_ROOT), p.build_default_cmd())

    def test_default_cmd_contains_skip_git(self):
        p = CodexProvider()
        self.assertIn("--skip-git-repo-check", p.build_default_cmd())


class TestAgentProvider(unittest.TestCase):
    def test_default_cmd_contains_repo_root(self):
        p = AgentProvider()
        self.assertIn(str(REPO_ROOT), p.build_default_cmd())

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
