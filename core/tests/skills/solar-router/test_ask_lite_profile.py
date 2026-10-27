"""ask_lite_v1: same envelope as ask, isolated launch; providers mocked."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import ask_lite
import execution_profiles as ep
from providers import PROVIDERS


def test_lite_envelope_differs_from_default_ask(tmp_path):
    normal = ep.build_ask_envelope(provider="codex", prompt="Hi", cwd=str(tmp_path))
    lite = ep.build_ask_envelope(provider="codex", prompt="Hi", cwd=str(tmp_path),
                                 profile=ep.ASK_LITE_PROFILE)
    assert normal["manifest"]["execution_profile"] == "ask_readonly_v1"
    assert lite["manifest"]["execution_profile"] == "ask_lite_v1"
    assert lite["manifest"]["composition"] == "ask_lite_envelope_v1"
    assert normal["review_input_digest"] != lite["review_input_digest"]
    again = ep.verify_envelope(lite["manifest"], lite["review_input_digest"],
                               provider="codex", profile=ep.ASK_LITE_PROFILE)
    assert again == lite["manifest"]


def test_claude_lite_argv_is_restricted(tmp_path):
    built = ep.build_ask_envelope(provider="claude", prompt="Hi", cwd=str(tmp_path),
                                  profile=ep.ASK_LITE_PROFILE)
    adapter = PROVIDERS["claude"]
    adapter.last_review_preflight = {}
    with patch.object(adapter, "resolve_binary", return_value="/bin/claude"), \
         patch("execution_profiles.preflight"), \
         ask_lite.launch(adapter, built["manifest"], built["review_input_digest"],
                         lambda: None) as (argv, env, cwd):
        assert argv[:2] == ["/bin/claude", "-p"]
        assert "--restricted" in argv
        assert "--setting-sources" in argv
        assert '{"mcpServers":{}}' in argv
        assert cwd == str(tmp_path.resolve())


def test_codex_lite_uses_private_home_and_ignore_flags(tmp_path, monkeypatch):
    origin = tmp_path / "origin-codex"
    origin.mkdir()
    (origin / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(origin))
    built = ep.build_ask_envelope(provider="codex", prompt="Hi", cwd=str(tmp_path),
                                  profile=ep.ASK_LITE_PROFILE)
    adapter = PROVIDERS["codex"]
    adapter.last_review_preflight = {}
    with patch.object(adapter, "resolve_binary", return_value="/bin/codex"), \
         patch("repository_reviews.codex_preflight"), \
         ask_lite.launch(adapter, built["manifest"], built["review_input_digest"],
                         lambda: None) as (argv, env, cwd):
        assert "--ignore-user-config" in argv
        assert "--ephemeral" in argv
        assert "--no-daemon" in argv
        assert "--sandbox" in argv and "read-only" in argv
        assert env["CODEX_HOME"].endswith("codex-home")
        assert cwd == str(tmp_path.resolve())


def test_agent_lite_uses_private_cursor_config(tmp_path):
    built = ep.build_ask_envelope(provider="agent", prompt="Hi", cwd=str(tmp_path),
                                  profile=ep.ASK_LITE_PROFILE)
    adapter = PROVIDERS["agent"]
    adapter.last_review_preflight = {}
    with patch.object(adapter, "resolve_binary", return_value="/bin/agent"), \
         patch("repository_cli_guards.cursor_auth"), \
         ask_lite.launch(adapter, built["manifest"], built["review_input_digest"],
                         lambda: None) as (argv, env, cwd):
        assert "--mode" in argv and "ask" in argv
        assert env["CURSOR_CONFIG_DIR"].endswith(".cursor")
        assert Path(env["HOME"]).name == "home"
        assert cwd == str(tmp_path.resolve())


def test_agy_lite_denies_mcp_in_private_home(tmp_path):
    built = ep.build_ask_envelope(provider="agy", prompt="Hi", cwd=str(tmp_path),
                                  profile=ep.ASK_LITE_PROFILE)
    adapter = PROVIDERS["agy"]
    adapter.last_review_preflight = {}
    with patch.object(adapter, "resolve_binary", return_value="/bin/agy"), \
         patch("repository_cli_guards.credential"), \
         ask_lite.launch(adapter, built["manifest"], built["review_input_digest"],
                         lambda: None) as (argv, env, cwd):
        assert "--mode" in argv and "plan" in argv
        assert "--disable-slash-commands" in argv
        assert Path(env["HOME"]).name == "home"
        settings = Path(env["HOME"]) / ".gemini/antigravity-cli/settings.json"
        assert settings.is_file()
        assert cwd == str(tmp_path.resolve())


def test_default_ask_path_unchanged(tmp_path):
    built = ep.build_ask_envelope(provider="codex", prompt="Hi", cwd=str(tmp_path))
    adapter = PROVIDERS["codex"]
    proc = MagicMock()
    proc.returncode, proc.stdout, proc.stderr = 0, "the answer", ""
    with patch("providers.base.shutil.which", return_value="/bin/codex"), \
         patch("providers.base.subprocess.run", return_value=proc) as run:
        text = adapter.run(
            "",
            review=dict(
                manifest=built["manifest"],
                expected=built["review_input_digest"],
                profile="ask_readonly_v1",
                before_launch=lambda: None,
            ),
        )
    assert text == "the answer"
    assert "--ignore-user-config" not in run.call_args.args[0]
