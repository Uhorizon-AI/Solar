"""
solar-router core — provider-agnostic routing logic.

Exposes route(raw: str) -> dict and route_stream(raw: str) -> generator.
The thin run_router.py entrypoint handles stdin/stdout/exit.

Architecture: dispatcher only.
- Each CLI (claude, gemini, agent) loads its own context automatically (CLAUDE.md, profile.md, MEMORY.md).
- The router passes only the user message + a pointer to the conversation file for history.
- No prompt building, no context injection, no rolling summary.
"""
import datetime
import json
import os
import pathlib
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

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
# Prompt building — minimal, just message + history pointer
# ---------------------------------------------------------------------------

def build_prompt(text: str, conv_path: pathlib.Path) -> str:
    """Build a minimal prompt: history pointer (if exists) + user message."""
    lines: List[str] = []
    if conv_path.exists():
        rel_path = conv_path.relative_to(REPO_ROOT)
        lines.append(
            f"Before responding, read {rel_path} for conversation history. "
            f"Then respond to the user message below."
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
    """Streaming variant. Yields JSONL lines:
      {"type": "chunk", "text": "..."}
      {"type": "done", ...}
    """
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
    provider_override = str(payload.get("provider") or "").strip().lower() or None

    if not text:
        yield json.dumps({"type": "done", "status": "failed", "error": "missing text", "provider": None, "request_id": request_id})
        return

    conversation_id = user_id or session_id or "default"
    conv_path = conversation_file(conversation_id)
    prompt = build_prompt(text, conv_path)

    provider_used: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    full_text_parts: list[str] = []

    try:
        for chunk, provider_used in stream_provider(prompt, provider_override):
            full_text_parts.append(chunk)
            yield json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
    except Exception as exc:
        yield json.dumps({"type": "done", "status": "failed", "error": str(exc), "provider": provider_used, "request_id": request_id})
        return

    reply_text = "".join(full_text_parts)

    if provider_used:
        provider_obj = PROVIDERS.get(provider_used)
        provider_usage = getattr(provider_obj, "last_usage", None)
        if isinstance(provider_usage, dict):
            usage = provider_usage

    append_message(conv_path, "user", text)
    append_message(conv_path, "assistant", reply_text)

    yield json.dumps({
        "type": "done",
        "status": "success",
        "provider": provider_used,
        "request_id": request_id,
        "usage": usage,
        "error": None,
        "prompt_chars": len(prompt),
    })


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

    prompt = build_prompt(text, conv_path)

    # Execute
    provider_used: Optional[str] = None
    try:
        if provider_override:
            ai_output, provider_used = run_strict_provider(provider_override, prompt)
        else:
            ai_output, provider_used = run_with_fallback(prompt)
    except Exception as exc:
        return _failed(request_id, "all_providers_failed", str(exc))

    reply_text = ai_output

    append_message(conv_path, "user", text)
    append_message(conv_path, "assistant", reply_text)

    audit_log(
        router_id, "end",
        status="success",
        provider=provider_used,
        duration_ms=int((time.monotonic() - t_start) * 1000),
        prompt_chars=len(prompt),
    )

    return {
        "status": "success",
        "request_id": request_id,
        "provider_used": provider_used,
        "reply_text": reply_text,
        "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        "error_code": None,
        "error": None,
    }
