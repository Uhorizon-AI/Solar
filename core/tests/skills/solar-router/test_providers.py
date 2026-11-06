"""
Unit tests for providers/*.py — subprocess.run is mocked throughout.
No real AI binaries are called.
"""
import io
import json
import os
import shlex
import unittest
from unittest.mock import MagicMock, patch

from providers.base import BaseProvider, SOLAR_WORKSPACE, SOLAR_ROOT, FALLBACK_PATHS
from providers.claude import ClaudeProvider, native_sandbox_settings
from providers.codex import CodexProvider
from providers.agy import AgyProvider, native_sandbox_settings as native_agy_settings
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
    def test_empty_output_keeps_stderr_tail_and_scrubs_secrets(self, mock_run, _):
        mock_run.return_value = _mock_proc(stdout="", stderr="a\nb\ntoken=hunter2secret\ndenied: permission")
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.run("prompt")
        self.assertIn("empty output", str(ctx.exception))
        self.assertIn("denied: permission", str(ctx.exception))
        self.assertNotIn("hunter2secret", str(ctx.exception))

    @patch("providers.base.shutil.which", return_value="/usr/bin/claude")
    @patch("providers.base.subprocess.run")
    def test_empty_output_with_a_known_cause_stores_its_fixed_word(self, mock_run, _):
        mock_run.return_value = _mock_proc(stdout="", stderr="warming up\nError 429: rate limit exceeded")
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.run("prompt")
        self.assertEqual(str(ctx.exception), "provider returned empty output (exit 0: quota_or_rate_limit)")

    @patch("providers.base.shutil.which", return_value="/usr/bin/claude")
    @patch("providers.base.subprocess.run")
    def test_empty_output_stays_plain_when_the_summary_itself_fails(self, mock_run, _):
        mock_run.return_value = _mock_proc(stdout="", stderr="some cause")
        with patch("review_failure.summarize", side_effect=Exception("boom")):
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.run("prompt")
        self.assertEqual(str(ctx.exception), "provider returned empty output")
        with patch("review_failure.summarize", return_value="exit 0"):  # its own internal fallback
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.run("prompt")
        self.assertEqual(str(ctx.exception), "provider returned empty output")

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
        self.assertTrue(cmd.startswith("agy "))
        self.assertNotIn(" -p ", f" {cmd} ")
        self.assertNotIn("--print", cmd)
        self.assertIn(f"--add-dir {SOLAR_WORKSPACE}", cmd)

    def test_default_cmd_keeps_the_sandbox_on_and_never_skips_permissions(self):
        argv = shlex.split(self.provider.build_default_cmd())
        self.assertIn("--sandbox", argv)
        self.assertEqual(argv[argv.index("--mode") + 1], "accept-edits")
        for forbidden in ("--dangerously-skip-permissions", "-y", "--yolo", "auto"):
            self.assertNotIn(forbidden, argv)
        settings = json.loads(argv[argv.index("--settings") + 1])
        self.assertEqual(settings, native_agy_settings())
        self.assertEqual(settings["toolPermission"], "proceed-in-sandbox")
        allow = settings["permissions"]["allow"]
        # No blanket rule: `command(*)` also allows a command outside the sandbox.
        self.assertEqual(allow, ["mcp(solar/solar_search)", "mcp(solar/solar_docs)"])
        self.assertFalse([rule for rule in allow if rule.startswith(("command", "write_file"))])

    @patch("providers.base.shutil.which", return_value="/usr/bin/agy")
    def test_get_cmd_binds_prompt_to_print(self, _which):
        cmd = self.provider.get_cmd("review this")
        self.assertEqual(cmd[0], "/usr/bin/agy")
        self.assertEqual(cmd[-2:], ["--print", "review this"])
        self.assertNotIn("-p", cmd)
        # Flags must never sit where -p would eat them as the prompt value.
        self.assertLess(cmd.index("--sandbox"), cmd.index("--print"))
        self.assertLess(cmd.index("--settings"), cmd.index("--print"))
        # The JSON survives get_cmd as one argument, untouched by the -p/--print stripping.
        self.assertEqual(json.loads(cmd[cmd.index("--settings") + 1]), native_agy_settings())

    @patch("providers.base.shutil.which", return_value="/usr/bin/agy")
    def test_get_cmd_rewrites_legacy_p_before_flags(self, _which):
        with patch.dict(os.environ, {
            "SOLAR_ROUTER_AGY_CMD": "agy -p --sandbox --add-dir /tmp/ws",
        }, clear=False):
            cmd = self.provider.get_cmd("hello")
        self.assertEqual(cmd, [
            "/usr/bin/agy",
            "--sandbox",
            "--add-dir",
            "/tmp/ws",
            "--print",
            "hello",
        ])

    @patch("providers.base.shutil.which", return_value="/usr/bin/agy")
    def test_get_cmd_keeps_a_print_flag_inside_the_settings_value(self, _which):
        settings = '{"note":"-p --print --prompt","toolPermission":"proceed-in-sandbox"}'
        with patch.dict(os.environ, {"SOLAR_ROUTER_AGY_CMD": f"agy --sandbox --settings {shlex.quote(settings)}"}, clear=False):
            cmd = self.provider.get_cmd("hello")
        self.assertEqual(cmd[cmd.index("--settings") + 1], settings)
        self.assertEqual(cmd[-2:], ["--print", "hello"])

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

    def test_default_cmd_keeps_the_sandbox_and_never_asks_for_approval(self):
        argv = shlex.split(CodexProvider().build_default_cmd())
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        # An automatic approvals reviewer in the user's config can approve leaving the sandbox.
        pairs = [(a, b) for a, b in zip(argv, argv[1:]) if a == "-c"]
        self.assertIn(("-c", 'approval_policy="never"'), pairs)
        for forbidden in ("--dangerously-bypass-approvals-and-sandbox", "danger-full-access"):
            self.assertNotIn(forbidden, argv)

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

    def test_default_cmd_keeps_cursor_sandbox_on(self):
        argv = shlex.split(AgentProvider().build_default_cmd())
        self.assertEqual(argv[argv.index("--sandbox") + 1], "enabled")
        for forbidden in ("-f", "--force", "--yolo"):
            self.assertNotIn(forbidden, argv)  # `-f` runs commands outside the sandbox


# ---------------------------------------------------------------------------
# ClaudeProvider
# ---------------------------------------------------------------------------

class TestClaudeProvider(unittest.TestCase):
    def test_default_cmd_uses_native_protections(self):
        argv = shlex.split(ClaudeProvider().build_default_cmd())
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertIn("--no-session-persistence", argv)
        for forbidden in ("bypassPermissions", "--dangerously-skip-permissions"):
            self.assertNotIn(forbidden, argv)  # Write and Edit would leave the workspace

    def test_default_cmd_enables_the_sandbox_without_an_exit(self):
        argv = shlex.split(ClaudeProvider().build_default_cmd())
        settings = json.loads(argv[argv.index("--settings") + 1])
        self.assertEqual(settings["sandbox"], {"enabled": True, "autoAllowBashIfSandboxed": True,
                                               "allowUnsandboxedCommands": False,
                                               "failIfUnavailable": True})
        self.assertIn("mcp__solar", settings["permissions"]["allow"])  # a headless run cannot ask for it

    def test_the_sandbox_refuses_to_start_unconfined(self):
        # Without it Claude only warns when bubblewrap or socat are missing and runs the shell open.
        settings = native_sandbox_settings()
        self.assertIs(settings["sandbox"]["failIfUnavailable"], True)

    def test_framework_read_rule_is_an_absolute_path_with_two_slashes(self):
        # `Read(/x)` is relative to the project; only `Read(//x)` names an absolute path.
        rules = native_sandbox_settings()["permissions"]["allow"]
        self.assertIn(f"Read(//{str(SOLAR_ROOT).lstrip('/')}/**)", rules)
        self.assertTrue(all(not r.startswith("Read(/") or r.startswith("Read(//") for r in rules))

    def test_stream_launches_the_default_command(self):
        event = json.dumps({"type": "result", "result": "ok", "usage": {}})
        proc = MagicMock()
        proc.stdout = iter([event + "\n"])
        proc.returncode = 0
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOLAR_ROUTER_CLAUDE_CMD", None)
            os.environ.pop("SOLAR_AI_CLAUDE_CMD", None)
            p = ClaudeProvider()
            with patch.object(p, "resolve_binary", side_effect=lambda b: b), \
                 patch("providers.claude.subprocess.Popen", return_value=proc) as popen:
                self.assertEqual("".join(p.stream("q")), "ok")
                streamed = popen.call_args.args[0]
                blocking = p.get_cmd("q")
        base = shlex.split(p.build_default_cmd())
        self.assertEqual(streamed[:len(base)], base)  # the same flags, then the streaming ones
        self.assertEqual(blocking[:-1], base)
        self.assertEqual(streamed[-1], "q")
        self.assertIn("--include-partial-messages", streamed)

    def test_env_override_replaces_the_whole_command(self):
        with patch.dict(os.environ, {"SOLAR_ROUTER_CLAUDE_CMD": "claude -p --model x"}):
            with patch.object(ClaudeProvider, "resolve_binary", side_effect=lambda b: b):
                self.assertEqual(ClaudeProvider().get_cmd("q"), ["claude", "-p", "--model", "x", "q"])

    def test_name(self):
        self.assertEqual(ClaudeProvider().name, "claude")


class TestProviderKnowsWhereItIs(unittest.TestCase):
    """A prompt that names `core/...` must be openable from the provider's cwd."""

    def test_prepare_env_carries_the_framework_and_workspace_paths(self):
        provider = PROVIDERS["claude"]
        env = provider.prepare_env({})
        self.assertEqual(env["SOLAR_WORKSPACE"], str(SOLAR_WORKSPACE))
        self.assertEqual(env["SOLAR_ROOT"], str(SOLAR_ROOT))

    def test_every_provider_gets_them(self):
        for name, provider in PROVIDERS.items():
            with self.subTest(provider=name):
                env = provider.prepare_env({})
                self.assertIn("SOLAR_ROOT", env)
                self.assertIn("SOLAR_WORKSPACE", env)

    def test_an_exported_value_is_not_overwritten(self):
        env = PROVIDERS["claude"].prepare_env(
            {"SOLAR_WORKSPACE": "/elsewhere", "SOLAR_ROOT": "/another"}
        )
        self.assertEqual(env["SOLAR_WORKSPACE"], "/elsewhere")
        self.assertEqual(env["SOLAR_ROOT"], "/another")

class TestExitZeroWithoutOutputKeepsTheCause(unittest.TestCase):
    """#142 on the paths that do not go through BaseProvider.run: streaming clients and Ollama."""

    STDERR = "boot\nload\nsandbox\ndenied: the command permission\nretry later token=hunter2secret"

    def _stream_error(self, provider, module):
        proc = MagicMock()
        proc.stdout = iter([])
        proc.stderr = io.StringIO(self.STDERR)
        proc.returncode = 0
        with patch.object(provider, "resolve_binary", side_effect=lambda b: b), \
             patch(f"providers.{module}.subprocess.Popen", return_value=proc):
            with self.assertRaises(RuntimeError) as ctx:
                list(provider.stream("a question"))
        return str(ctx.exception)

    def _assert_cause_kept(self, message):
        self.assertTrue(message.startswith("provider returned empty output"))
        self.assertIn("denied: the command permission", message)
        self.assertNotIn("boot", message)  # only the last three lines
        self.assertNotIn("hunter2secret", message)

    def test_cursor_stream(self):
        self._assert_cause_kept(self._stream_error(AgentProvider(), "agent"))

    def test_claude_stream(self):
        self._assert_cause_kept(self._stream_error(ClaudeProvider(), "claude"))

    def test_ollama_run(self):
        done = _mock_proc(stdout="", stderr=self.STDERR)
        with patch("providers.base.shutil.which", return_value="/usr/bin/ollama"), \
             patch("providers.ollama.subprocess.run", return_value=done):
            with self.assertRaises(RuntimeError) as ctx:
                OllamaProvider().run("a question")
        self._assert_cause_kept(str(ctx.exception))

    def test_streams_and_ollama_keep_the_plain_message_when_stderr_is_empty(self):
        for provider, module in ((AgentProvider(), "agent"), (ClaudeProvider(), "claude")):
            proc = MagicMock()
            proc.stdout, proc.stderr, proc.returncode = iter([]), io.StringIO(""), 0
            with patch.object(provider, "resolve_binary", side_effect=lambda b: b), \
                 patch(f"providers.{module}.subprocess.Popen", return_value=proc):
                with self.assertRaises(RuntimeError) as ctx:
                    list(provider.stream("q"))
            self.assertEqual(str(ctx.exception), "provider returned empty output")

    def test_a_descendant_holding_stderr_open_does_not_hold_the_error_back(self):
        """PR 145 review: the client exits 0 but a child keeps stderr open; the error must not wait for it."""
        import sys
        import tempfile
        import time
        script = (
            "import subprocess, sys\n"
            "sys.stderr.write('denied: the command permission\\n'); sys.stderr.flush()\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'], stdout=subprocess.DEVNULL)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "client.py")
            with open(path, "w") as fh:
                fh.write(script)
            for provider, key in ((AgentProvider(), "SOLAR_ROUTER_AGENT_CMD"), (ClaudeProvider(), "SOLAR_ROUTER_CLAUDE_CMD")):
                with patch.dict(os.environ, {key: f"{sys.executable} {path}"}), \
                     patch.object(provider, "resolve_binary", side_effect=lambda b: b):
                    started = time.monotonic()
                    with self.assertRaises(RuntimeError) as ctx:
                        list(provider.stream("a question"))
                    elapsed = time.monotonic() - started
                self.assertLess(elapsed, 3.0, provider.name)
                self.assertIn("denied: the command permission", str(ctx.exception))

    def test_a_cut_never_separates_an_authorization_header_from_its_credential(self):
        """PR 145 review: the 16 KiB cut used to keep the credential of a header it had cut off."""
        header = "Authorization: Basic dGVzdDpmaWN0aXRpb3Vz"
        diagnosis = " denied: the command permission\n"
        limit = 32 + len(diagnosis)
        message = self._through_a_pipe("a" * 10 + "\n" + header + "\n" + diagnosis, limit, [])
        self.assertIn("denied: the command permission", message)
        self.assertNotIn("dGVzdDpmaWN0aXRpb3Vz", message)

    def test_a_cut_inside_a_multiline_prompt_still_hides_the_whole_prompt(self):
        """PR 145 review: cutting before scrubbing dropped the prompt's first line, so the rest leaked."""
        prompt = "first line of the private prompt\nsecond line of the private prompt\nthird line of the private prompt"
        diagnosis = "denied: the command permission\n"
        text = prompt + "\n" + diagnosis
        message = self._through_a_pipe(text, len(text) - 5, [prompt])
        self.assertNotIn("private prompt", message)
        self.assertIn("denied: the command permission", message)

    def test_a_prose_cause_survives_the_stream_path(self):
        """PR 145 review: scrubbing in the reader and again in summarize used to eat `denied ...`."""
        cause = "authorization: denied because the sandbox blocked the command\n"
        message = self._through_a_pipe(cause, 4096, ["some prompt that is not in the output"])
        self.assertIn("sandbox blocked the command", message)

    def test_a_cut_between_a_json_key_and_its_value_hides_the_value(self):
        """PR 145 review: the key's line was cut away and the value on the next line leaked."""
        diagnosis = "Command execution denied by the sandbox\n"
        for key, value in (('{"api_key":', ' "private-fixture-123"}'),
                           ('{"Authorization":', ' "Basic dGVzdDpmaWN0aXRpb3Vz"}')):
            payload = "x" * 30 + "\n" + key + "\n" + value + "\n" + diagnosis
            limit = len(value) + 1 + len(diagnosis) + 3  # the cut falls inside the key's line
            message = self._through_a_pipe(payload, limit, [])
            self.assertNotIn("private-fixture-123", message)
            self.assertNotIn("dGVzdDpmaWN0aXRpb3Vz", message)
            self.assertIn("denied by the sandbox", message)

    @staticmethod
    def _through_a_pipe(payload: str, limit: int, prompts) -> str:
        """Write a small payload to a real stderr pipe and read it back bounded; never waits unbounded."""
        import subprocess, sys
        proc = subprocess.Popen([sys.executable, "-c", f"import sys; sys.stderr.write({payload!r})"],
                                stderr=subprocess.PIPE, text=True)
        try:
            proc.wait(timeout=10)
            return AgentProvider._empty_output_error(
                AgentProvider._read_stderr_bounded(proc.stderr, limit=limit), "", prompts)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
            proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
