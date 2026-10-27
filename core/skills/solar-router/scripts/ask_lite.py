"""Opt-in ask_lite_v1 launches: cheap read-only questions with review-style isolation.

Same ask envelope shape (instructions + cwd). Default ask_readonly_v1 is unchanged.
MCP registries start empty (Solar MCP allowlist is a later phase).
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile

from ask_metering import output_flags
from cli_capabilities import unsupported
from execution_profiles import (
    ASK_LITE_PROFILE,
    ASK_PROVIDERS,
    ENV_ALLOWLIST,
    ProfileError,
    ask_cwd,
    ask_prompt,
    model_args,
    verify_envelope,
)
from repository_reviews import CODEX_CONFIG


def _error(code: str):
    return ProfileError(code)


@contextmanager
def launch(adapter, manifest, expected, before_launch):
    """Build an isolated argv/env for one lite question; cwd is the approved ask folder."""
    provider = adapter.name
    if provider not in ASK_PROVIDERS:
        raise _error("execution_profile_unsupported")
    prefixes = (
        "SOLAR_ROUTER_" + provider.upper() + "_",
        "SOLAR_AI_" + provider.upper() + "_",
    )
    if any(
        key.startswith(prefixes)
        and (key.endswith("_CMD") or any(s in key for s in ("FLAGS", "ARGS", "SETTINGS")))
        for key in os.environ
    ):
        raise _error("execution_profile_override_rejected")
    approved = verify_envelope(manifest, expected, provider=provider, profile=ASK_LITE_PROFILE)
    prompt = ask_prompt(approved)
    cwd = Path(ask_cwd(approved)).resolve()
    if not cwd.is_dir():
        raise _error("review_input_mismatch")
    env = {k: v for k, v in os.environ.items() if k in ENV_ALLOWLIST}
    binary = adapter.resolve_binary(provider)
    adapter.last_review_preflight = dict(
        provider=provider, version=None, read_only_mode="ask_lite_v1", isolation="review_style"
    )
    with tempfile.TemporaryDirectory(prefix="solar-ask-lite-", ignore_cleanup_errors=True) as temp:
        private = Path(temp)
        if provider == "claude":
            argv, env = _claude(binary, approved, prompt, cwd, env, adapter)
        elif provider == "codex":
            argv, env = _codex(binary, approved, prompt, cwd, env, private, adapter)
        elif provider == "agent":
            argv, env = _agent(binary, approved, prompt, cwd, env, private, adapter)
        elif provider == "agy":
            argv, env = _agy(binary, approved, prompt, cwd, env, private, adapter)
        else:
            raise _error("execution_profile_unsupported")
        before_launch()
        verify_envelope(manifest, expected, provider=provider, profile=ASK_LITE_PROFILE)
        yield argv, env, str(cwd)


def _claude(binary, manifest, prompt, cwd, env, adapter):
    from execution_profiles import preflight

    preflight(
        binary,
        env,
        str(cwd),
        adapter.last_review_preflight,
        **({} if manifest.get("model") else {"with_model": False}),
    )
    argv = [
        binary, "-p", "--no-session-persistence", "--safe-mode", "--restricted",
        "--setting-sources", "", "--tools", "",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--settings", '{"disableAllHooks":true}',
        "--permission-mode", "plan",
        *model_args(manifest), *output_flags("claude"), "--", prompt,
    ]
    return argv, env


def _codex(binary, manifest, prompt, cwd, env, private, adapter):
    from repository_reviews import codex_preflight

    home = private / "codex-home"
    home.mkdir(mode=0o700)
    origin = Path(os.environ.get("CODEX_HOME") or Path(env.get("HOME", str(Path.home()))) / ".codex")
    auth = origin / "auth.json"
    if not auth.is_file():
        raise unsupported("codex", "credentials", "credentials_unavailable")
    shutil.copyfile(auth, home / "auth.json")
    os.chmod(home / "auth.json", 0o600)
    env = dict(env)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    env["CODEX_HOME"] = str(home)
    config = [arg for value in CODEX_CONFIG for arg in ("-c", value)]
    codex_preflight(
        binary, env, str(cwd), config, adapter.last_review_preflight,
        **({} if manifest.get("model") else {"with_model": False}),
    )
    # --no-daemon is a top-level codex flag (not under `exec`).
    argv = [
        binary, "--no-daemon", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
        "--ignore-user-config", "--ignore-rules", "--ephemeral",
        "-C", str(cwd), *model_args(manifest), *output_flags("codex"), *config, "--", prompt,
    ]
    return argv, env


def _private_home(env, private):
    origin = Path(env.get("HOME", str(Path.home())))
    home = private / "home"
    home.mkdir(mode=0o700)
    temp = private / "tmp"
    temp.mkdir(mode=0o700)
    slim = {k: v for k, v in env.items() if k in {"PATH", "LANG", "LC_ALL", "LC_CTYPE"}}
    slim.update(
        HOME=str(home),
        TMPDIR=str(temp),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local/share"),
        XDG_CACHE_HOME=str(home / ".cache"),
    )
    return origin, home, slim


def _agent(binary, manifest, prompt, cwd, env, private, adapter):
    from repository_cli_guards import cursor_auth, write_json

    origin, home, env = _private_home(env, private)
    managed = [
        Path("/Library/Application Support/Cursor"),
        Path("/etc/cursor"),
        origin / ".cursor/managed",
    ]
    if any(p.exists() for p in managed):
        raise unsupported("agent", "managed_policy", "managed_policy_present")
    cursor_auth(origin, home, "agent")
    config = home / ".cursor"
    write_json(
        config / "cli-config.json",
        dict(
            version=1,
            editor=dict(vimMode=False),
            approvalMode="allowlist",
            sandbox=dict(mode="enabled", readBoundary="workspace"),
            permissions=dict(
                allow=["Read(**)"],
                deny=["Write(**)", "Shell(*)", "Mcp(*:*)", "WebFetch(*)"],
            ),
        ),
    )
    write_json(config / "mcp.json", dict(mcpServers={}))
    write_json(config / "hooks.json", dict(version=1, hooks={}))
    env.update(
        CURSOR_CONFIG_DIR=str(config),
        CURSOR_DATA_DIR=str(home / "cursor-data"),
        AGENT_CLI_CREDENTIAL_STORE="file",
    )
    argv = [
        binary, "--print", "--mode", "ask", "--sandbox", "enabled", "--trust",
        "--workspace", str(cwd), *model_args(manifest), *output_flags("agent"), "--", prompt,
    ]
    return argv, env


def _agy(binary, manifest, prompt, cwd, env, private, adapter):
    """Private HOME + jetski token only (same as repository reviews). Fail closed on auth gaps."""
    from repository_cli_guards import credential, write_json

    origin, home, env = _private_home(env, private)
    gemini = home / ".gemini"
    credential(
        origin / ".gemini/jetski-standalone-oauth-token",
        gemini / "jetski-standalone-oauth-token",
        "agy",
    )
    write_json(
        gemini / "antigravity-cli/settings.json",
        dict(
            toolPermission="strict",
            enableTerminalSandbox=True,
            allowNonWorkspaceAccess=False,
            permissions=dict(
                allow=[f"read_file({cwd})"],
                ask=[],
                deny=[
                    "write_file(*)", "command(*)", "unsandboxed(*)", "mcp(*)",
                    "read_url(*)", "execute_url(*)",
                ],
            ),
        ),
    )
    log = private / "agy.log"
    argv = [
        binary, "--add-dir", str(cwd), "--mode", "plan", "--sandbox",
        "--disable-slash-commands", *model_args(manifest), *output_flags("agy"),
        "--log-file", str(log), "--print", prompt,
    ]
    return argv, env
