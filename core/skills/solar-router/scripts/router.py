"""
solar-router core — provider-agnostic routing logic.

Exposes route(raw: str) -> dict and route_stream(raw: str) -> generator.
The thin run_router.py entrypoint handles stdin/stdout/exit.

Architecture: thin dispatcher + decision extraction.
- Each CLI loads repo context from cwd=SOLAR_WORKSPACE (CLAUDE.md, profile.md, MEMORY.md).
- The router passes the user message + optional history pointer + routing hints.
- For mode=auto and channels telegram/n8n, the model emits <solar_decision> tags;
  the router parses them into decision.kind for transport consumers.
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
_CLIENT_SCRIPTS = _SCRIPTS_DIR.parent.parent / "solar-client" / "scripts"
if str(_CLIENT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CLIENT_SCRIPTS))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from providers import PROVIDERS  # noqa: E402
from solar_paths import resolve_solar_paths, resolve_under_home as _resolve_under_home  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_PROVIDERS = set(PROVIDERS.keys())
VALID_MODES = {"auto", "direct_only", "async_only"}
VALID_CHANNELS = {"telegram", "n8n", "async-task", "other"}

SOLAR_WORKSPACE, SOLAR_ROOT = resolve_solar_paths()


_raw_runtime_dir = (
    os.getenv("SOLAR_ROUTER_RUNTIME_DIR")
    or os.getenv("SOLAR_RUNTIME_DIR")
    or "sun/runtime/router"
)
_runtime_path = pathlib.Path(_raw_runtime_dir)
RUNTIME_ROOT = _runtime_path if _runtime_path.is_absolute() else SOLAR_WORKSPACE / _runtime_path

_raw_system_prompt_file = (
    os.getenv("SOLAR_ROUTER_SYSTEM_PROMPT_FILE")
    or os.getenv("SOLAR_SYSTEM_PROMPT_FILE")
    or "core/skills/solar-router/assets/system_prompt.md"
)
_system_prompt_path = pathlib.Path(_raw_system_prompt_file)
SYSTEM_PROMPT_FILE = (
    _system_prompt_path
    if _system_prompt_path.is_absolute()
    else _resolve_under_home(str(_system_prompt_path))
)

RE_SOLAR_DECISION = re.compile(
    r"<solar_decision>\s*([a-z_]+)\s*</solar_decision>",
    re.IGNORECASE | re.DOTALL,
)
RE_SOLAR_SUMMARY = re.compile(
    r"<solar_summary>.*?</solar_summary>",
    re.IGNORECASE | re.DOTALL,
)


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


def append_message(path: pathlib.Path, role: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"role": role, "text": text}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")


def audit_log(router_id: str, event: str, **kwargs: Any) -> None:
    audit_path = RUNTIME_ROOT / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": event,
        "router_id": router_id,
        **kwargs,
    }
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")


# ---------------------------------------------------------------------------
# Tags (decision extraction)
# ---------------------------------------------------------------------------

def strip_solar_metadata(ai_output: str) -> str:
    """Remove <solar_decision> and <solar_summary> blocks for user-facing reply_text."""
    text = RE_SOLAR_DECISION.sub("", ai_output)
    text = RE_SOLAR_SUMMARY.sub("", text)
    return text.strip()


def extract_tag_decision_kind(ai_output: str) -> Optional[str]:
    m = RE_SOLAR_DECISION.search(ai_output)
    if not m:
        return None
    return m.group(1).lower()


def async_tasks_enabled() -> bool:
    raw = os.getenv("SOLAR_SYSTEM_FEATURES", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return "async-tasks" in parts


def create_async_draft(user_text: str, ai_output: str, request_id: str) -> Optional[str]:
    """Create a draft via solar-async-tasks create.sh; return task id or None."""
    _ = request_id  # reserved for future correlation
    script = _resolve_under_home("core/skills/solar-async-tasks/scripts/create.sh")
    if not script.is_file():
        return None
    title = (user_text.strip() or "async task")[:120]
    desc = (strip_solar_metadata(ai_output) or ai_output).strip()[:8000]
    try:
        proc = subprocess.run(
            ["bash", str(script), title, desc],
            capture_output=True,
            text=True,
            cwd=str(SOLAR_WORKSPACE),
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("ID:"):
            return line.split("ID:", 1)[1].strip()
    return None


# ---------------------------------------------------------------------------
# JIT Context Resolution
# ---------------------------------------------------------------------------

def resolve_jit_context(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve agent context for this call.

    - Agent file found  → return its repo-relative path; CLI reads it from SOLAR_WORKSPACE.
    - Agent not found   → generate role inline (JIT, ephemeral — no file written).
    Skills/commands are discovered naturally by the CLI from SOLAR_WORKSPACE.
    """
    agent_name = metadata.get("agent")
    planet = metadata.get("planet")

    if not agent_name:
        return {"agent_name": None, "planet": planet, "jit_generated": False, "agent_path": None, "agent_content": None}

    candidates: List[pathlib.Path] = []
    if planet:
        candidates.append(SOLAR_WORKSPACE / f"planets/{planet}/agents/{agent_name}.md")
    candidates.append(_resolve_under_home(f"core/agents/{agent_name}.md"))

    for path in candidates:
        if path.exists():
            return {
                "agent_name": agent_name,
                "planet": planet,
                "jit_generated": False,
                "agent_path": str(path.relative_to(SOLAR_WORKSPACE)),
                "agent_content": None,
            }

    # Not found → JIT inline (ephemeral, not persisted)
    jit_content = (
        f"# Role: {agent_name}\n"
        f"You are a specialized agent for tasks related to {agent_name}. "
        f"Apply domain expertise for the task requested. "
        f"Discover available skills and commands from the Solar repository."
    )
    return {
        "agent_name": agent_name,
        "planet": planet,
        "jit_generated": True,
        "agent_path": None,
        "agent_content": jit_content,
    }


def resolve_decision(
    mode: str,
    channel: str,
    ai_output: str,
    user_text: str,
    request_id: str,
) -> Tuple[Dict[str, Any], str]:
    """
    Compute v3 decision dict and user-facing reply_text (tags stripped).
    """
    mode_l = mode.strip().lower()
    channel_l = channel.strip().lower()
    stripped = strip_solar_metadata(ai_output)
    fallback_reply = stripped if stripped else ai_output.strip()

    if mode_l == "direct_only":
        return (
            {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            fallback_reply,
        )

    if mode_l == "async_only":
        if not async_tasks_enabled():
            return (
                {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
                fallback_reply,
            )
        task_id = create_async_draft(user_text, ai_output, request_id)
        return (
            {"kind": "async_draft_created", "task_id": task_id, "priority_suggested": None},
            fallback_reply,
        )

    if mode_l == "auto" and channel_l == "async-task":
        return (
            {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            fallback_reply,
        )

    # mode == auto, channels: telegram, n8n, other
    tag_kind = extract_tag_decision_kind(ai_output)
    if tag_kind == "async_draft_created":
        return (
            {"kind": "async_draft_created", "task_id": None, "priority_suggested": None},
            fallback_reply,
        )
    if tag_kind == "direct_reply":
        return (
            {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            fallback_reply,
        )

    return (
        {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        fallback_reply,
    )


def decision_engine(
    mode: str,
    channel: str,
    ai_output: Optional[str],
    request_id: str,
    user_text: str,
) -> Dict[str, Any]:
    """Backward-compat helper for tests and tooling."""
    mode_l = mode.strip().lower()
    channel_l = channel.strip().lower()
    if mode_l not in VALID_MODES:
        raise ValueError(f"unsupported mode: {mode}")
    if mode_l == "auto" and channel_l not in ("async-task",) and ai_output is None:
        raise ValueError("auto mode requires ai_output for non-async-task channels")
    d, _ = resolve_decision(mode, channel, ai_output or "", user_text, request_id)
    return d


def parse_ai_decision_output(ai_output: str) -> Dict[str, Any]:
    """
    Normalize provider output to {decision, reply_text, _degraded?}.
    Uses <solar_decision> tags when present; otherwise plain text → direct_reply + _degraded.
    """
    if not ai_output or not str(ai_output).strip():
        raise ValueError("empty ai output")
    s = ai_output.strip()
    tag = extract_tag_decision_kind(s)
    stripped = strip_solar_metadata(s)
    if tag in ("direct_reply", "async_draft_created"):
        return {
            "decision": {"kind": tag, "task_id": None, "priority_suggested": None},
            "reply_text": stripped or s,
            "_degraded": False,
        }
    return {
        "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        "reply_text": s,
        "_degraded": True,
    }


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_prompt(
    system_prompt: str,
    user_text: str,
    conversation_id: str,
    mode: str,
    channel: str,
    jit_context: Optional[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = []
    lines.append(system_prompt)

    if jit_context:
        if jit_context.get("agent_content"):
            # JIT inline: agent file didn't exist, inject ephemeral role
            lines.append("")
            lines.append("## Agent Role (JIT)")
            lines.append(jit_context["agent_content"])
        elif jit_context.get("agent_path"):
            # Agent file exists: reference it — CLI reads from SOLAR_WORKSPACE
            lines.append("")
            lines.append(f"## Agent Role")
            lines.append(f"Read {jit_context['agent_path']} for your role definition before responding.")

    lines.append("")
    lines.append("Conversation context")
    lines.append(f"- conversation_id: {conversation_id}")
    lines.append(f"- channel: {channel}")
    lines.append(f"- mode: {mode}")
    if jit_context and jit_context.get("planet"):
        lines.append(f"- planet: {jit_context['planet']}")
    if jit_context and jit_context.get("jit_generated"):
        lines.append("- agent: jit (generated for this task)")
    lines.append("")
    lines.append("Current user message:")
    lines.append(user_text)
    lines.append("")
    mode_l = mode.strip().lower()
    channel_l = channel.strip().lower()
    if mode_l == "auto" and channel_l in ("telegram", "n8n"):
        lines.append(
            f"[Solar routing] channel={channel_l}, mode=auto. After your main answer, append "
            "exactly one line: <solar_decision>direct_reply</solar_decision> if the request is quick, "
            "or <solar_decision>async_draft_created</solar_decision> if it needs substantial async work. "
            "Then append <solar_summary>...</solar_summary> as usual."
        )
    elif mode_l == "auto" and channel_l != "async-task":
        lines.append(
            "[Solar routing] mode=auto. Append <solar_decision>direct_reply</solar_decision> or "
            "<solar_decision>async_draft_created</solar_decision> before <solar_summary>."
        )
    elif mode_l == "direct_only":
        lines.append(
            "[Solar routing] mode=direct_only. Respond directly; include <solar_summary> but do not "
            "use <solar_decision> for async routing."
        )
        if channel_l == "async-task":
            lines.append(
                "[Solar async-task consent] This active task has already been approved to execute its "
                "task body and write declared artifacts/output paths. Ask for explicit approval only for "
                "external sends, deletions, credentials, irreversible actions, or changes outside the "
                "declared task scope."
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER_PRIORITY = "codex,claude,agy,agent"


class UnsupportedProviderPriorityError(RuntimeError):
    """SOLAR_ROUTER_PROVIDER_PRIORITY is empty or contains unsupported tokens."""


_ENV_AGY_MIGRATION_ATTEMPTED = False


def _maybe_migrate_workspace_env_agy() -> None:
    """Run the one-time atomic .env bridge for a legacy updater transition.

    Old client updaters cannot execute migration code introduced by the target
    release. The first router selection in the new release therefore migrates
    an active legacy priority before provider selection. Failure is explicit and
    no provider is invoked.
    """
    global _ENV_AGY_MIGRATION_ATTEMPTED
    if _ENV_AGY_MIGRATION_ATTEMPTED:
        return

    env_path = SOLAR_WORKSPACE / ".env"
    if not env_path.is_file():
        _ENV_AGY_MIGRATION_ATTEMPTED = True
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    legacy_priority = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key in ("SOLAR_ROUTER_PROVIDER_PRIORITY", "SOLAR_AI_PROVIDER_PRIORITY"):
            tokens = {part.strip().casefold() for part in value.split(",")}
            if "gemini" in tokens:
                legacy_priority = True
                break
    if not legacy_priority:
        _ENV_AGY_MIGRATION_ATTEMPTED = True
        return
    migrator = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "solar-client"
        / "scripts"
        / "migrate_workspace_env_agy.py"
    )
    if not migrator.is_file():
        raise UnsupportedProviderPriorityError(
            "legacy provider priority contains 'gemini', but the agy migration "
            "helper is missing; replace 'gemini' with 'agy' in workspace .env"
        )
    try:
        proc = subprocess.run(
            [sys.executable, str(migrator), str(env_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise UnsupportedProviderPriorityError(
                "could not migrate legacy provider priority gemini→agy"
                + (f": {detail}" if detail else "")
            )
        text = env_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UnsupportedProviderPriorityError(
            f"could not migrate legacy provider priority gemini→agy: {exc}"
        ) from exc
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        if key in ("SOLAR_ROUTER_PROVIDER_PRIORITY", "SOLAR_AI_PROVIDER_PRIORITY"):
            os.environ[key] = val
    _ENV_AGY_MIGRATION_ATTEMPTED = True


def _provider_priority() -> List[str]:
    """Return configured provider order. Never silently expands to all providers.

    Unknown tokens (including retired ``gemini``) raise with a clear error so
    misconfiguration cannot fall through to a different primary provider.
    """
    _maybe_migrate_workspace_env_agy()
    raw = (
        os.getenv("SOLAR_ROUTER_PROVIDER_PRIORITY")
        or os.getenv("SOLAR_AI_PROVIDER_PRIORITY")
        or DEFAULT_PROVIDER_PRIORITY
    )
    seen: set = set()
    result: List[str] = []
    unknown: List[str] = []
    for p in raw.split(","):
        p = p.strip().lower()
        if not p:
            continue
        if p in PROVIDERS:
            if p not in seen:
                seen.add(p)
                result.append(p)
        else:
            unknown.append(p)
    if unknown:
        hint = ""
        if "gemini" in unknown:
            hint = " Gemini CLI was retired; replace 'gemini' with 'agy' (Antigravity)."
        raise UnsupportedProviderPriorityError(
            "unsupported provider(s) in SOLAR_ROUTER_PROVIDER_PRIORITY: "
            f"{', '.join(unknown)}. "
            f"supported: {', '.join(sorted(PROVIDERS))}.{hint}"
        )
    if not result:
        raise UnsupportedProviderPriorityError(
            "SOLAR_ROUTER_PROVIDER_PRIORITY has no supported providers "
            f"(raw={raw!r}). supported: {', '.join(sorted(PROVIDERS))}."
        )
    return result


def run_with_fallback(prompt: str) -> tuple:
    providers = _provider_priority()
    last_error: Optional[Exception] = None
    for name in providers:
        try:
            output = PROVIDERS[name].run(prompt)
            return output, name
        except Exception as exc:
            last_error = exc
            print(f"[solar-router] provider {name} failed: {exc}", file=sys.stderr)
    raise RuntimeError(f"all providers failed. last error: {last_error}")


def run_strict_provider(provider: str, prompt: str) -> tuple:
    output = PROVIDERS[provider].run(prompt)
    return output, provider


def stream_provider(prompt: str, provider_override: Optional[str] = None):
    if provider_override and provider_override in PROVIDERS:
        name = provider_override
    else:
        providers = _provider_priority()
        name = providers[0] if providers else next(iter(PROVIDERS))
    for chunk in PROVIDERS[name].stream(prompt):
        yield chunk, name


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def parse_request_payload(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as strict_exc:
        payload = json.loads(raw, strict=False)
        print(f"[solar-router] non-strict JSON parse: {strict_exc}", file=sys.stderr)
        return payload


def _failed(request_id: str, error_code: str, error: str, provider_used: Any = None) -> Dict[str, Any]:
    return {
        "status": "failed",
        "request_id": request_id,
        "provider_used": provider_used,
        "reply_text": "",
        "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        "error_code": error_code,
        "error": error,
    }


def _failed_after_audit(
    router_id: str,
    t_start: float,
    request_id: str,
    error_code: str,
    error: str,
    provider_used: Any = None,
    prompt_chars: int = 0,
) -> Dict[str, Any]:
    audit_log(
        router_id,
        "end",
        status="failed",
        error_code=error_code,
        error=error,
        provider=provider_used,
        duration_ms=int((time.monotonic() - t_start) * 1000),
        prompt_chars=prompt_chars,
    )
    return _failed(request_id, error_code, error, provider_used)


# ---------------------------------------------------------------------------
# Core routing — streaming
# ---------------------------------------------------------------------------

def route_stream(raw: str):
    """Streaming variant. Yields JSONL lines; final done includes decision + reply_text."""
    if not raw:
        yield json.dumps({"type": "done", "status": "failed", "error": "missing input", "provider": None, "request_id": "unknown"})
        return

    try:
        payload = parse_request_payload(raw)
    except json.JSONDecodeError as exc:
        yield json.dumps({"type": "done", "status": "failed", "error": str(exc), "provider": None, "request_id": "unknown"})
        return

    request_id = str(payload.get("request_id", "")).strip() or "unknown"
    user_id = str(payload.get("user_id", "")).strip()
    session_id = str(payload.get("session_id", "")).strip()
    text = str(payload.get("text", "")).strip()
    channel = str(payload.get("channel", "other")).strip().lower()
    mode = str(payload.get("mode", "auto")).strip().lower()
    provider_override = str(payload.get("provider") or "").strip().lower() or None

    if channel not in VALID_CHANNELS:
        channel = "other"
    if mode not in VALID_MODES:
        yield json.dumps({"type": "done", "status": "failed", "error": f"invalid mode: {mode}", "provider": None, "request_id": request_id})
        return

    if not text:
        yield json.dumps({"type": "done", "status": "failed", "error": "missing text", "provider": None, "request_id": request_id})
        return

    if mode == "async_only" and not async_tasks_enabled():
        yield json.dumps({"type": "done", "status": "failed", "error": "async_tasks_disabled", "provider": None, "request_id": request_id, "error_code": "async_tasks_disabled"})
        return

    conversation_id = user_id or session_id or "default"
    conv_path = conversation_file(conversation_id)
    metadata = payload.get("metadata") or {}
    jit_context = resolve_jit_context(metadata) if metadata else None
    system_prompt = read_system_prompt()
    prompt = build_prompt(system_prompt, text, conversation_id, mode, channel, jit_context)

    provider_used: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    full_text_parts: list[str] = []

    try:
        if provider_override:
            for chunk, provider_used in stream_provider(prompt, provider_override):
                full_text_parts.append(chunk)
                yield json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
        else:
            for chunk, provider_used in stream_provider(prompt, None):
                full_text_parts.append(chunk)
                yield json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
    except UnsupportedProviderPriorityError as exc:
        yield json.dumps(
            {
                "type": "done",
                "status": "failed",
                "error": str(exc),
                "provider": provider_used,
                "request_id": request_id,
                "error_code": "invalid_provider_priority",
            }
        )
        return
    except Exception as exc:
        yield json.dumps({"type": "done", "status": "failed", "error": str(exc), "provider": provider_used, "request_id": request_id})
        return

    ai_output = "".join(full_text_parts)

    if provider_used:
        provider_obj = PROVIDERS.get(provider_used)
        provider_usage = getattr(provider_obj, "last_usage", None)
        if isinstance(provider_usage, dict):
            usage = provider_usage

    decision, reply_text = resolve_decision(mode, channel, ai_output, text, request_id)

    append_message(conv_path, "user", text)
    append_message(conv_path, "assistant", ai_output)

    yield json.dumps(
        {
            "type": "done",
            "status": "success",
            "provider": provider_used,
            "request_id": request_id,
            "usage": usage,
            "error": None,
            "prompt_chars": len(prompt),
            "reply_text": reply_text,
            "decision": decision,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Core routing — non-streaming
# ---------------------------------------------------------------------------

def route(raw: str) -> Dict[str, Any]:
    if not raw:
        return _failed("unknown", "missing_input", "missing stdin payload")

    try:
        payload = parse_request_payload(raw)
    except json.JSONDecodeError as exc:
        return _failed("unknown", "invalid_json", f"invalid JSON input: {exc}")

    request_id = str(payload.get("request_id", "")).strip() or "unknown"
    router_id = str(uuid.uuid4())
    session_id = str(payload.get("session_id", "")).strip()
    user_id = str(payload.get("user_id", "")).strip()
    text = str(payload.get("text", "")).strip()
    channel = str(payload.get("channel", "other")).strip().lower()
    mode = str(payload.get("mode", "auto")).strip().lower()
    provider_override = str(payload.get("provider") or "").strip().lower()

    if not text:
        return _failed(request_id, "missing_text", "missing text field")

    if mode not in VALID_MODES:
        return _failed(request_id, "invalid_mode", f"unsupported mode: {mode}. valid: {sorted(VALID_MODES)}")

    if provider_override and provider_override not in SUPPORTED_PROVIDERS:
        return _failed(request_id, "unsupported_provider", f"unsupported provider: {provider_override}")

    if channel not in VALID_CHANNELS:
        channel = "other"

    conversation_id = user_id or session_id or "default"
    conv_path = conversation_file(conversation_id)

    t_start = time.monotonic()
    metadata = payload.get("metadata") or {}
    audit_log(router_id, "start", request_id=request_id, user_id=user_id, channel=channel, mode=mode, metadata=metadata)

    if mode == "async_only" and not async_tasks_enabled():
        return _failed_after_audit(
            router_id,
            t_start,
            request_id,
            "async_tasks_disabled",
            "async-tasks feature not enabled in SOLAR_SYSTEM_FEATURES",
        )

    jit_context = resolve_jit_context(metadata) if metadata else None
    system_prompt = read_system_prompt()
    prompt = build_prompt(system_prompt, text, conversation_id, mode, channel, jit_context)

    provider_used: Optional[str] = None
    try:
        if provider_override:
            ai_output, provider_used = run_strict_provider(provider_override, prompt)
        else:
            ai_output, provider_used = run_with_fallback(prompt)
    except UnsupportedProviderPriorityError as exc:
        return _failed_after_audit(
            router_id,
            t_start,
            request_id,
            "invalid_provider_priority",
            str(exc),
            provider_used,
            prompt_chars=len(prompt),
        )
    except Exception as exc:
        if provider_override:
            return _failed_after_audit(
                router_id,
                t_start,
                request_id,
                "provider_locked_failed",
                str(exc),
                provider_used,
                prompt_chars=len(prompt),
            )
        return _failed_after_audit(
            router_id,
            t_start,
            request_id,
            "all_providers_failed",
            str(exc),
            provider_used,
            prompt_chars=len(prompt),
        )

    decision, reply_text = resolve_decision(mode, channel, ai_output, text, request_id)

    append_message(conv_path, "user", text)
    append_message(conv_path, "assistant", ai_output)

    audit_log(
        router_id,
        "end",
        status="success",
        provider=provider_used,
        duration_ms=int((time.monotonic() - t_start) * 1000),
        prompt_chars=len(prompt),
        decision_kind=decision.get("kind"),
        jit_generated=bool(jit_context and jit_context.get("jit_generated")),
    )

    return {
        "status": "success",
        "request_id": request_id,
        "provider_used": provider_used,
        "reply_text": reply_text,
        "decision": decision,
        "error_code": None,
        "error": None,
    }
