"""A question launched through each client with the client's own session.

No isolated HOME, no copied credentials: the client sees the environment the
user logged in with, and Solar asks it for its native read-only mode.
subprocess.run is mocked; no real AI binary is called.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from providers.agent import AgentProvider
from providers.agy import AgyProvider
from providers.claude import ClaudeProvider
from providers.codex import CodexProvider
from providers.ollama import OllamaProvider


def _proc(returncode=0, stdout="answer", stderr=""):
    proc = MagicMock()
    proc.returncode, proc.stdout, proc.stderr = returncode, stdout, stderr
    return proc


def _ask(provider, prompt="question", **kwargs):
    with patch("providers.base.shutil.which", side_effect=lambda b, path=None: f"/bin/{b}"), \
         patch("providers.base.subprocess.run", return_value=_proc()) as run:
        result = provider.ask(prompt, **kwargs)
    return result, run.call_args


class TestNativeReadOnlyMode(unittest.TestCase):
    def test_codex_asks_for_read_only_sandbox(self):
        result, call = _ask(CodexProvider())
        argv = call.args[0]
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(result.mode, "--sandbox read-only")
        self.assertEqual(argv[argv.index("-c") + 1], 'approval_policy="never"')
        self.assertLess(argv.index("-c"), argv.index("--"))  # before the separator and the prompt

    def test_cursor_asks_for_ask_mode(self):
        result, call = _ask(AgentProvider())
        argv = call.args[0]
        self.assertEqual(argv[argv.index("--mode") + 1], "ask")
        self.assertEqual(result.mode, "--mode ask")

    def test_antigravity_asks_for_plan_mode(self):
        result, call = _ask(AgyProvider())
        argv = call.args[0]
        self.assertEqual(argv[argv.index("--mode") + 1], "plan")
        self.assertEqual(result.mode, "--mode plan")

    def test_claude_asks_for_plan_mode(self):
        result, call = _ask(ClaudeProvider())
        argv = call.args[0]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")
        self.assertNotIn("bypassPermissions", argv)
        self.assertEqual(result.mode, "--permission-mode plan")

    def test_client_without_read_only_mode_says_so(self):
        result, _ = _ask(OllamaProvider())
        self.assertEqual(result.mode, "none")

    def test_ollama_still_runs_its_model(self):
        _, call = _ask(OllamaProvider())
        self.assertEqual(call.args[0][1:3], ["run", "solar"])

    def test_no_client_runs_with_write_everything_flags(self):
        for provider in (CodexProvider(), AgentProvider(), AgyProvider(), ClaudeProvider()):
            _, call = _ask(provider)
            argv = call.args[0]
            for forbidden in ("workspace-write", "--dangerously-skip-permissions", "-f"):
                self.assertNotIn(forbidden, argv, provider.name)


class TestPromptIsNeverAnOption(unittest.TestCase):
    def test_a_prompt_that_looks_like_an_option_stays_the_last_argument(self):
        hostile = "--mode agent"
        for provider in (CodexProvider(), AgentProvider(), AgyProvider(), ClaudeProvider()):
            _, call = _ask(provider, prompt=hostile)
            argv = call.args[0]
            self.assertEqual(argv[-1], hostile, provider.name)
            self.assertIn(argv[-2], ("--", "--print"), provider.name)
            self.assertEqual(argv.count("--mode"), 1 if provider.name in ("agent", "agy") else 0, provider.name)


class TestTimeout(unittest.TestCase):
    def test_a_timeout_says_which_client_and_why(self):
        import subprocess
        with patch("providers.base.shutil.which", return_value="/bin/codex"), \
             patch("providers.base.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1)):
            with self.assertRaises(RuntimeError) as ctx:
                CodexProvider().ask("q")
        self.assertIn("codex", str(ctx.exception))
        self.assertIn("timeout", str(ctx.exception))


class TestOwnSession(unittest.TestCase):
    def test_environment_keeps_the_real_home(self):
        with patch.dict(os.environ, {"HOME": "/Users/real", "CODEX_HOME": "/Users/real/.codex"}):
            for provider in (CodexProvider(), AgentProvider(), AgyProvider(), ClaudeProvider()):
                _, call = _ask(provider)
                env = call.kwargs["env"]
                self.assertEqual(env["HOME"], "/Users/real", provider.name)
                self.assertEqual(env.get("CODEX_HOME"), "/Users/real/.codex", provider.name)

    def test_nothing_is_copied_or_linked(self):
        with patch("shutil.copyfile") as copy, patch("os.symlink") as link, \
             patch("shutil.copytree") as tree:
            for provider in (CodexProvider(), AgentProvider(), AgyProvider()):
                _ask(provider)
        for spy in (copy, link, tree):
            spy.assert_not_called()


class TestFolderAndModel(unittest.TestCase):
    def test_given_folder_is_where_the_client_starts(self):
        for provider in (CodexProvider(), AgentProvider(), AgyProvider(), ClaudeProvider()):
            _, call = _ask(provider, cwd="/Users/real/Downloads")
            self.assertEqual(str(call.kwargs["cwd"]), "/Users/real/Downloads", provider.name)

    def test_model_is_passed_only_when_named(self):
        for provider in (CodexProvider(), AgentProvider(), AgyProvider(), ClaudeProvider()):
            _, plain = _ask(provider)
            self.assertNotIn("--model", plain.args[0], provider.name)
            _, named = _ask(provider, model="m-1")
            argv = named.args[0]
            self.assertEqual(argv[argv.index("--model") + 1], "m-1", provider.name)

    def test_prompt_is_the_last_argument(self):
        for provider in (CodexProvider(), AgentProvider(), AgyProvider(), ClaudeProvider()):
            _, call = _ask(provider)
            self.assertEqual(call.args[0][-1], "question", provider.name)


class TestResultAndFailure(unittest.TestCase):
    def test_text_comes_back_as_the_client_wrote_it(self):
        with patch("providers.base.shutil.which", return_value="/bin/codex"), \
             patch("providers.base.subprocess.run", return_value=_proc(stdout="  hola\n\n")):
            result = CodexProvider().ask("q")
        self.assertEqual(result.text, "hola")
        self.assertEqual(result.provider, "codex")

    def test_failure_carries_the_clients_own_message(self):
        with patch("providers.base.shutil.which", return_value="/bin/agent"), \
             patch("providers.base.subprocess.run",
                   return_value=_proc(returncode=1, stdout="", stderr="not logged in")):
            with self.assertRaises(RuntimeError) as ctx:
                AgentProvider().ask("q")
        self.assertIn("not_logged_in", str(ctx.exception))
        self.assertIn("agent", str(ctx.exception))

    def test_missing_binary_fails_with_a_clear_reason(self):
        with patch("providers.base.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                AgyProvider().ask("q")
        self.assertIn("client binary not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
