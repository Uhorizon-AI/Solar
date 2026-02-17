#!/usr/bin/env python3
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from typing import Dict, List


SUPPORTED_PROVIDERS = {"codex", "claude", "gemini"}
CODEX_STATE_DIR = pathlib.Path.home() / ".codex"
FALLBACK_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]

# REPO_ROOT: script lives at core/skills/solar-router/scripts/ -> 4 levels up to repo
REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

DEFAULT_CMDS: Dict[str, str] = {
    "codex": (
        f"codex exec --skip-git-repo-check --full-auto -C {REPO_ROOT} "
        f"--add-dir {CODEX_STATE_DIR} --"
    ),
    "claude": "claude -p --permission-mode bypassPermissions --no-session-persistence",
    "gemini": "gemini -y -p",
}

MAX_CONTEXT_TURNS = int(
    os.getenv("SOLAR_ROUTER_CONTEXT_TURNS") or os.getenv("SOLAR_CONTEXT_TURNS") or "12"
)

# All paths resolved against REPO_ROOT when relative (same context for all providers)
_raw_runtime_dir = (
    os.getenv("SOLAR_ROUTER_RUNTIME_DIR")
    or os.getenv("SOLAR_RUNTIME_DIR")
    or "sun/runtime/router"
)
_runtime_path = pathlib.Path(_raw_runtime_dir)
if _runtime_path.is_absolute():
    RUNTIME_ROOT = _runtime_path
else:
    RUNTIME_ROOT = REPO_ROOT / _runtime_path

_raw_system_prompt_file = (
    os.getenv("SOLAR_ROUTER_SYSTEM_PROMPT_FILE")
    or os.getenv("SOLAR_SYSTEM_PROMPT_FILE")
    or "core/skills/solar-router/assets/system_prompt.md"
)
_system_prompt_path = pathlib.Path(_raw_system_prompt_file)
if _system_prompt_path.is_absolute():
    SYSTEM_PROMPT_FILE = _system_prompt_path
else:
    SYSTEM_PROMPT_FILE = REPO_ROOT / _system_prompt_path


def sanitize_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return cleaned[:120] if cleaned else "unknown"


def conversation_file(conversation_id: str) -> pathlib.Path:
    return RUNTIME_ROOT / "conversations" / f"{sanitize_id(conversation_id)}.jsonl"


def read_system_prompt() -> str:
    if not SYSTEM_PROMPT_FILE.exists():
        return (
            "You are Solar, a practical AI assistant. Keep continuity with previous"
            " conversation turns and answer with clear, useful output."
        )
    return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()


def load_recent_messages(path: pathlib.Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    items: List[Dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = str(record.get("role", "")).strip().lower()
        text = str(record.get("text", "")).strip()
        if role in {"user", "assistant"} and text:
            items.append({"role": role, "text": text})
    keep = MAX_CONTEXT_TURNS * 2
    return items[-keep:] if keep > 0 else items


def append_message(path: pathlib.Path, role: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"role": role, "text": text}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")


def build_prompt(
    system_prompt: str,
    recent: List[Dict[str, str]],
    user_text: str,
    conversation_id: str,
) -> str:
    lines: List[str] = []
    lines.append(system_prompt)
    lines.append("")
    lines.append("Conversation context")
    lines.append(f"- conversation_id: {conversation_id}")
    lines.append("")
    if recent:
        lines.append("Recent turns (oldest -> newest):")
        for item in recent:
            label = "USER" if item["role"] == "user" else "ASSISTANT"
            lines.append(f"{label}: {item['text']}")
        lines.append("")
    lines.append("Current user message:")
    lines.append(user_text)
    lines.append("")
    lines.append("Respond directly to the current user message.")
    return "\n".join(lines)


def get_cmd(provider: str) -> List[str]:
    # Try new naming first, fallback to old naming
    new_key = f"SOLAR_ROUTER_{provider.upper()}_CMD"
    old_key = f"SOLAR_AI_{provider.upper()}_CMD"
    raw = (os.getenv(new_key) or os.getenv(old_key) or DEFAULT_CMDS[provider]).strip()
    cmd = shlex.split(raw)
    if not cmd:
        raise RuntimeError(f"{new_key} is empty")
    found = shutil.which(cmd[0])
    if found is None:
        current_path = os.getenv("PATH", "")
        merged_path = os.pathsep.join(FALLBACK_PATHS + ([current_path] if current_path else []))
        found = shutil.which(cmd[0], path=merged_path)
    if found is None:
        raise RuntimeError(
            f"client binary not found: {cmd[0]} (provider={provider}, env={new_key}, PATH={os.getenv('PATH','')})"
        )
    cmd[0] = found
    return cmd


def run_provider(provider: str, prompt: str) -> str:
    timeout_sec = int(
        os.getenv("SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC")
        or os.getenv("SOLAR_AI_PROVIDER_TIMEOUT_SEC")
        or "300"
    )
    cmd = get_cmd(provider) + [prompt]
    env = os.environ.copy()
    if provider == "gemini":
        # Keep Gemini credentials anchored to user-level ~/.gemini regardless of launcher env.
        env.setdefault("GEMINI_CLI_HOME", str(pathlib.Path.home()))
        # Prefer file-based oauth creds in ~/.gemini/oauth_creds.json unless explicitly overridden.
        env.setdefault("GEMINI_FORCE_ENCRYPTED_FILE_STORAGE", "false")

    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        cwd=REPO_ROOT,
        env=env,
    )
    if proc.returncode != 0:
        error = proc.stderr.strip() or proc.stdout.strip() or "provider returned non-zero"
        raise RuntimeError(error)
    output = proc.stdout.strip()
    if not output:
        raise RuntimeError("provider returned empty output")

    if provider == "gemini":
        # Gemini can return auth prompts with exit code 0 in non-interactive mode.
        cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
        if (
            "Please visit the following URL to authorize the application" in cleaned
            or "Enter the authorization code:" in cleaned
        ):
            raise RuntimeError(
                "gemini returned OAuth prompt in headless mode; credentials are not usable for non-interactive execution"
            )
    return output


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("missing stdin payload")

    payload = json.loads(raw)
    provider = str(payload.get("provider", "")).strip().lower()
    text = str(payload.get("text", "")).strip()
    session_id = str(payload.get("session_id", "")).strip()
    user_id = str(payload.get("user_id", "")).strip()
    conversation_id = user_id or session_id or "default"

    if provider not in SUPPORTED_PROVIDERS:
        raise SystemExit(f"unsupported provider: {provider}")
    if not text:
        raise SystemExit("missing text")

    conv_path = conversation_file(conversation_id)
    system_prompt = read_system_prompt()
    recent = load_recent_messages(conv_path)
    full_prompt = build_prompt(system_prompt, recent, text, conversation_id)

    reply = run_provider(provider, full_prompt)
    append_message(conv_path, "user", text)
    append_message(conv_path, "assistant", reply)
    print(reply)


if __name__ == "__main__":
    main()
