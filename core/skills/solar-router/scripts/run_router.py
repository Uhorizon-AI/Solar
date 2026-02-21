#!/usr/bin/env python3
"""
solar-router v3 — single source of truth for AI execution and routing policy.

Input  (stdin): JSON matching RouterRequest contract v3
Output (stdout): JSON matching RouterResponse contract v3
"""
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional


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

_raw_runtime_dir = (
    os.getenv("SOLAR_ROUTER_RUNTIME_DIR")
    or os.getenv("SOLAR_RUNTIME_DIR")
    or "sun/runtime/router"
)
_runtime_path = pathlib.Path(_raw_runtime_dir)
RUNTIME_ROOT = _runtime_path if _runtime_path.is_absolute() else REPO_ROOT / _runtime_path

_raw_system_prompt_file = (
    os.getenv("SOLAR_ROUTER_SYSTEM_PROMPT_FILE")
    or os.getenv("SOLAR_SYSTEM_PROMPT_FILE")
    or "core/skills/solar-router/assets/system_prompt.md"
)
_system_prompt_path = pathlib.Path(_raw_system_prompt_file)
SYSTEM_PROMPT_FILE = (
    _system_prompt_path if _system_prompt_path.is_absolute() else REPO_ROOT / _system_prompt_path
)

ASYNC_TASKS_CREATE_SCRIPT = REPO_ROOT / "core/skills/solar-async-tasks/scripts/create.sh"

VALID_MODES = {"auto", "direct_only", "async_only"}
VALID_CHANNELS = {"telegram", "n8n", "async-task", "other"}
VALID_DECISION_KINDS = {
    "direct_reply",
    "async_draft_proposal",
    "async_draft_created",
    "async_activation_needed",
}


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def _solar_features() -> List[str]:
    raw = os.getenv("SOLAR_SYSTEM_FEATURES", "")
    return [f.strip().lower() for f in raw.split(",") if f.strip()]


def async_tasks_enabled() -> bool:
    return "async-tasks" in _solar_features()


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_prompt(
    system_prompt: str,
    recent: List[Dict[str, str]],
    user_text: str,
    conversation_id: str,
    mode: str,
    channel: str,
) -> str:
    lines: List[str] = []
    lines.append(system_prompt)
    lines.append("")
    lines.append("Conversation context")
    lines.append(f"- conversation_id: {conversation_id}")
    lines.append(f"- channel: {channel}")
    lines.append(f"- mode: {mode}")
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
    if mode == "auto":
        lines.append(
            "IMPORTANT: You must respond with a JSON object as your first output block. "
            "The JSON must contain at minimum:\n"
            '  {"decision": {"kind": "<direct_reply|async_draft_created|async_activation_needed>"}, '
            '"reply_text": "<your response here>"}\n'
            "Use direct_reply for requests answerable immediately. "
            "Use async_draft_created only for long-running, complex, or deferred tasks. "
            "Do NOT wrap the JSON in markdown code fences."
        )
    else:
        lines.append("Respond directly to the current user message.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider execution
# ---------------------------------------------------------------------------

def get_cmd(provider: str) -> List[str]:
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
            f"client binary not found: {cmd[0]} "
            f"(provider={provider}, env={new_key}, PATH={os.getenv('PATH', '')})"
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
        env.setdefault("GEMINI_CLI_HOME", str(pathlib.Path.home()))
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
        cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
        if (
            "Please visit the following URL to authorize the application" in cleaned
            or "Enter the authorization code:" in cleaned
        ):
            raise RuntimeError(
                "gemini returned OAuth prompt in headless mode; "
                "credentials are not usable for non-interactive execution"
            )
    return output


# ---------------------------------------------------------------------------
# Provider selection with fallback
# ---------------------------------------------------------------------------

def _provider_priority() -> List[str]:
    raw = (
        os.getenv("SOLAR_ROUTER_PROVIDER_PRIORITY")
        or os.getenv("SOLAR_AI_PROVIDER_PRIORITY")
        or "codex,claude,gemini"
    )
    seen: set = set()
    result: List[str] = []
    for p in raw.split(","):
        p = p.strip().lower()
        if p in SUPPORTED_PROVIDERS and p not in seen:
            seen.add(p)
            result.append(p)
    return result if result else list(SUPPORTED_PROVIDERS)


def run_with_fallback(prompt: str) -> tuple[str, str]:
    """Run prompt through providers in priority order. Returns (output, provider_used)."""
    providers = _provider_priority()
    last_error: Optional[Exception] = None
    for provider in providers:
        try:
            output = run_provider(provider, prompt)
            return output, provider
        except Exception as exc:
            last_error = exc
            print(f"[solar-router] provider {provider} failed: {exc}", file=sys.stderr)
    raise RuntimeError(
        f"all providers failed. last error: {last_error}"
    )


def run_strict_provider(provider: str, prompt: str) -> tuple[str, str]:
    """Run prompt with a specific provider, no fallback. Returns (output, provider_used)."""
    output = run_provider(provider, prompt)
    return output, provider


# ---------------------------------------------------------------------------
# Async draft creation
# ---------------------------------------------------------------------------

def create_async_draft(title: str, description: str) -> Optional[str]:
    """Invoke solar-async-tasks create.sh and return task_id or None on failure."""
    if not ASYNC_TASKS_CREATE_SCRIPT.exists():
        raise RuntimeError(
            f"async-tasks create script not found: {ASYNC_TASKS_CREATE_SCRIPT}"
        )
    proc = subprocess.run(
        ["bash", str(ASYNC_TASKS_CREATE_SCRIPT), title, description],
        text=True,
        capture_output=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"create.sh failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    # Extract task_id from output (create.sh prints "task_id: <id>" or similar)
    output = proc.stdout.strip()
    for line in output.splitlines():
        if "task_id" in line.lower():
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    # Fallback: return last non-empty line as task_id
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    return lines[-1] if lines else None


# ---------------------------------------------------------------------------
# Output parsing for mode=auto
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences if present."""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def parse_ai_decision_output(raw_output: str) -> Dict[str, Any]:
    """
    Parse AI output for mode=auto. Expects JSON with decision.kind and reply_text.
    Returns parsed dict. Raises ValueError if unparseable with no useful reply_text.
    """
    # Try to find a JSON block in the output
    text = raw_output.strip()

    # Attempt 1: entire output is JSON
    try:
        parsed = json.loads(_strip_code_fences(text))
        if isinstance(parsed, dict) and "decision" in parsed:
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: find first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and "decision" in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    # Degradation: no parseable JSON with decision.kind — use reply_text as direct_reply
    # Per plan: degrade to direct_reply only when there IS useful output
    if text:
        return {
            "decision": {"kind": "direct_reply"},
            "reply_text": text,
            "_degraded": True,
        }

    raise ValueError("AI output is empty and unparseable")


# ---------------------------------------------------------------------------
# DecisionEngine
# ---------------------------------------------------------------------------

def decision_engine(
    mode: str,
    channel: str,
    ai_output: Optional[str],
    request_id: str,
    user_text: str,
) -> Dict[str, Any]:
    """
    Apply routing policy and return decision dict with kind, task_id, priority_suggested.
    """
    # Rule 1: direct_only always returns direct_reply
    if mode == "direct_only":
        return {
            "kind": "direct_reply",
            "task_id": None,
            "priority_suggested": None,
        }

    # Rule 2: async_only — handled before AI execution in main(); should not reach here.
    # Kept as defensive guard only.
    if mode == "async_only":
        return {
            "kind": "async_draft_created",
            "task_id": None,
            "priority_suggested": "normal",
        }

    # Rule 3: auto
    if mode == "auto":
        # channel=async-task always direct_reply
        if channel == "async-task":
            return {
                "kind": "direct_reply",
                "task_id": None,
                "priority_suggested": None,
            }
        # For telegram/n8n/other: AI decides semantically
        if ai_output is None:
            raise ValueError("ai_output required for mode=auto with channel != async-task")
        parsed = parse_ai_decision_output(ai_output)
        kind = parsed.get("decision", {}).get("kind", "direct_reply")
        if kind not in VALID_DECISION_KINDS:
            kind = "direct_reply"
        return {
            "kind": kind,
            "task_id": parsed.get("decision", {}).get("task_id"),
            "priority_suggested": parsed.get("decision", {}).get("priority_suggested"),
            "_parsed": parsed,
        }

    raise ValueError(f"unknown mode: {mode}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def emit(response: Dict[str, Any]) -> None:
    print(json.dumps(response, ensure_ascii=False))


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        emit({
            "status": "failed",
            "request_id": "unknown",
            "provider_used": None,
            "reply_text": "",
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "missing_input",
            "error": "missing stdin payload",
        })
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit({
            "status": "failed",
            "request_id": "unknown",
            "provider_used": None,
            "reply_text": "",
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "invalid_json",
            "error": f"invalid JSON input: {exc}",
        })
        sys.exit(1)

    request_id = str(payload.get("request_id", "unknown")).strip()
    session_id = str(payload.get("session_id", "")).strip()
    user_id = str(payload.get("user_id", "")).strip()
    text = str(payload.get("text", "")).strip()
    channel = str(payload.get("channel", "other")).strip().lower()
    mode = str(payload.get("mode", "auto")).strip().lower()
    provider_override = str(payload.get("provider") or "").strip().lower()

    # Validate required fields
    if not text:
        emit({
            "status": "failed",
            "request_id": request_id,
            "provider_used": None,
            "reply_text": "",
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "missing_text",
            "error": "missing text field",
        })
        sys.exit(1)

    if mode not in VALID_MODES:
        emit({
            "status": "failed",
            "request_id": request_id,
            "provider_used": None,
            "reply_text": "",
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "invalid_mode",
            "error": f"unsupported mode: {mode}. valid: {sorted(VALID_MODES)}",
        })
        sys.exit(1)

    if provider_override and provider_override not in SUPPORTED_PROVIDERS:
        emit({
            "status": "failed",
            "request_id": request_id,
            "provider_used": None,
            "reply_text": "",
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "unsupported_provider",
            "error": f"unsupported provider: {provider_override}",
        })
        sys.exit(1)

    # Normalize channel
    if channel not in VALID_CHANNELS:
        channel = "other"

    conversation_id = user_id or session_id or "default"
    conv_path = conversation_file(conversation_id)

    # --- Fix: async_only bypasses AI execution entirely — policy-driven, no provider needed ---
    if mode == "async_only":
        if not async_tasks_enabled():
            emit({
                "status": "failed",
                "request_id": request_id,
                "provider_used": None,
                "reply_text": "",
                "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
                "error_code": "async_tasks_disabled",
                "error": "mode=async_only requested but async-tasks feature is not enabled in SOLAR_SYSTEM_FEATURES",
            })
            sys.exit(1)
        # Create draft directly from user text — no AI call required
        task_id: Optional[str] = None
        reply_text = f"Creando tarea asíncrona: {text[:80].strip()}"
        try:
            title = text[:80].strip()
            task_id = create_async_draft(title, text)
        except Exception as exc:
            emit({
                "status": "failed",
                "request_id": request_id,
                "provider_used": None,
                "reply_text": "",
                "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
                "error_code": "async_draft_failed",
                "error": str(exc),
            })
            sys.exit(1)
        append_message(conv_path, "user", text)
        append_message(conv_path, "assistant", reply_text)
        emit({
            "status": "success",
            "request_id": request_id,
            "provider_used": None,
            "reply_text": reply_text,
            "decision": {
                "kind": "async_draft_created",
                "task_id": task_id,
                "priority_suggested": "normal",
            },
            "error_code": None,
            "error": None,
        })
        return

    system_prompt = read_system_prompt()
    recent = load_recent_messages(conv_path)
    full_prompt = build_prompt(system_prompt, recent, text, conversation_id, mode, channel)

    # --- Execute AI ---
    try:
        if provider_override:
            # Strict mode: no fallback
            try:
                ai_output, provider_used = run_strict_provider(provider_override, full_prompt)
            except Exception as exc:
                emit({
                    "status": "failed",
                    "request_id": request_id,
                    "provider_used": provider_override,
                    "reply_text": "",
                    "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
                    "error_code": "provider_locked_failed",
                    "error": str(exc),
                })
                sys.exit(1)
        else:
            # Priority fallback mode
            ai_output, provider_used = run_with_fallback(full_prompt)
    except Exception as exc:
        emit({
            "status": "failed",
            "request_id": request_id,
            "provider_used": None,
            "reply_text": "",
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "all_providers_failed",
            "error": str(exc),
        })
        sys.exit(1)

    # --- DecisionEngine ---
    try:
        # For mode=auto with non-async-task channels, pass ai_output for semantic decision
        ai_output_for_decision = (
            ai_output
            if mode == "auto" and channel != "async-task"
            else None
        )
        decision = decision_engine(mode, channel, ai_output_for_decision, request_id, text)
    except ValueError as exc:
        emit({
            "status": "failed",
            "request_id": request_id,
            "provider_used": provider_used,
            "reply_text": ai_output,
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "decision_engine_failed",
            "error": str(exc),
        })
        sys.exit(1)

    # --- Extract reply_text ---
    reply_text = ai_output
    if mode == "auto" and channel != "async-task":
        parsed_output = decision.pop("_parsed", None)
        if parsed_output and "reply_text" in parsed_output:
            reply_text = str(parsed_output["reply_text"])

    # --- Handle async draft creation ---
    task_id = decision.get("task_id")
    if decision["kind"] == "async_draft_created" and task_id is None:
        if async_tasks_enabled():
            try:
                # Use reply_text as description; derive title from first 80 chars of user text
                title = text[:80].strip()
                task_id = create_async_draft(title, reply_text or text)
                decision["task_id"] = task_id
            except Exception as exc:
                # Draft creation failed — degrade to direct_reply with warning
                reply_text = (
                    f"{reply_text}\n\n[Warning: async draft creation failed: {exc}]"
                )
                decision["kind"] = "direct_reply"
                decision["task_id"] = None
        else:
            # async-tasks not enabled, degrade gracefully
            decision["kind"] = "direct_reply"
            decision["task_id"] = None

    # --- Persist conversation ---
    append_message(conv_path, "user", text)
    append_message(conv_path, "assistant", reply_text)

    # --- Emit response ---
    emit({
        "status": "success",
        "request_id": request_id,
        "provider_used": provider_used,
        "reply_text": reply_text,
        "decision": {
            "kind": decision["kind"],
            "task_id": decision.get("task_id"),
            "priority_suggested": decision.get("priority_suggested"),
        },
        "error_code": None,
        "error": None,
    })


if __name__ == "__main__":
    main()
