"""
solar-router core — provider-agnostic routing logic.

Exposes route(raw: str) -> dict and route_stream(raw: str) -> generator.
The thin run_router.py entrypoint handles stdin/stdout/exit.

Architecture: thin dispatcher + decision extraction.
- Each CLI loads repo context from cwd=REPO_ROOT (CLAUDE.md, profile.md, MEMORY.md).
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
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from providers import PROVIDERS  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_PROVIDERS = set(PROVIDERS.keys())
VALID_MODES = {"auto", "direct_only", "async_only"}
VALID_CHANNELS = {"telegram", "n8n", "async-task", "other"}

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

_raw_runtime_dir = (
    os.getenv("SOLAR_ROUTER_RUNTIME_DIR")
    or os.getenv("SOLAR_RUNTIME_DIR")
    or "sun/runtime/router"
)
_runtime_path = pathlib.Path(_raw_runtime_dir)
RUNTIME_ROOT = _runtime_path if _runtime_path.is_absolute() else REPO_ROOT / _runtime_path

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
    script = REPO_ROOT / "core/skills/solar-async-tasks/scripts/create.sh"
    if not script.is_file():
        return None
    title = (user_text.strip() or "async task")[:120]
    desc = (strip_solar_metadata(ai_output) or ai_output).strip()[:8000]
    try:
        proc = subprocess.run(
            ["bash", str(script), title, desc],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
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
# Prompt building — minimal + routing hints for tag contract
# ---------------------------------------------------------------------------

def build_prompt(
    text: str,
    conv_path: pathlib.Path,
    mode: str = "auto",
    channel: str = "other",
) -> str:
    """Minimal prompt: history pointer (if exists) + routing hints + user message."""
    lines: List[str] = []
    if conv_path.exists():
        rel_path = conv_path.relative_to(REPO_ROOT)
        lines.append(
            f"Before responding, read {rel_path} for conversation history. "
            f"Then respond to the user message below."
        )
        lines.append("")

    mode_l = mode.strip().lower()
    channel_l = channel.strip().lower()

    if mode_l == "auto" and channel_l in ("telegram", "n8n"):
        lines.append(
            f"[Solar routing] channel={channel_l}, mode=auto. After your main answer, append "
            "exactly one line: <solar_decision>direct_reply</solar_decision> if the request is quick, "
            "or <solar_decision>async_draft_created</solar_decision> if it needs substantial async work "
            "(then explain you need more time, propose an async draft, and ask for confirmation per your instructions). "
            "Then append <solar_summary>...</solar_summary> as usual."
        )
        lines.append("")
    elif mode_l == "auto" and channel_l != "async-task":
        lines.append(
            "[Solar routing] mode=auto. Append <solar_decision>direct_reply</solar_decision> or "
            "<solar_decision>async_draft_created</solar_decision> before <solar_summary>."
        )
        lines.append("")
    elif mode_l == "direct_only":
        lines.append(
            "[Solar routing] mode=direct_only. Respond directly; include <solar_summary> but do not "
            "use <solar_decision> for async routing."
        )
        lines.append("")

    lines.append(text)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def _provider_priority() -> List[str]:
    raw = (
        os.getenv("SOLAR_ROUTER_PROVIDER_PRIORITY")
        or os.getenv("SOLAR_AI_PROVIDER_PRIORITY")
        or "claude,gemini,agent"
    )
    seen: set = set()
    result: List[str] = []
    for p in raw.split(","):
        p = p.strip().lower()
        if p in SUPPORTED_PROVIDERS and p not in seen:
            seen.add(p)
            result.append(p)
    return result if result else list(SUPPORTED_PROVIDERS)


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
    prompt = build_prompt(text, conv_path, mode=mode, channel=channel)

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
    audit_log(router_id, "start", request_id=request_id, user_id=user_id, channel=channel, mode=mode)

    if mode == "async_only" and not async_tasks_enabled():
        return _failed(request_id, "async_tasks_disabled", "async-tasks feature not enabled in SOLAR_SYSTEM_FEATURES")

    prompt = build_prompt(text, conv_path, mode=mode, channel=channel)

    provider_used: Optional[str] = None
    try:
        if provider_override:
            ai_output, provider_used = run_strict_provider(provider_override, prompt)
        else:
            ai_output, provider_used = run_with_fallback(prompt)
    except Exception as exc:
        if provider_override:
            return _failed(request_id, "provider_locked_failed", str(exc))
        return _failed(request_id, "all_providers_failed", str(exc))

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
