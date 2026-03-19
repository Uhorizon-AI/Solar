"""
solar-router core — provider-agnostic routing logic.

Exposes route(raw: str) -> dict.
The thin run_router.py entrypoint handles stdin/stdout/exit.
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
from typing import Any, Dict, List, Optional

# Ensure scripts/ dir is in path so `providers` package resolves correctly
# whether this module is imported by run_router.py or directly in tests.
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
VALID_DECISION_KINDS = {
    "direct_reply",
    "async_draft_proposal",
    "async_draft_created",
    "async_activation_needed",
}

# router.py lives at core/skills/solar-router/scripts/ → 4 levels up to repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

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


def audit_log(router_id: str, event: str, **kwargs: Any) -> None:
    """Append one audit record to sun/runtime/router/audit.jsonl."""
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
# Skill metadata extraction
# ---------------------------------------------------------------------------

def _extract_skill_description(skill_path: pathlib.Path) -> Optional[str]:
    try:
        content = skill_path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return None
        frontmatter = match.group(1)
        desc_match = re.search(r"description:\s*[>|]?\s*\n?((?:[ \t]+.+\n?)+|.+)", frontmatter)
        if desc_match:
            raw = desc_match.group(1).strip()
            return " ".join(line.strip() for line in raw.splitlines() if line.strip())
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# JIT Context Resolution
# ---------------------------------------------------------------------------

def resolve_jit_context(metadata: Dict[str, Any]) -> Dict[str, Any]:
    agent_name = metadata.get("agent")
    raw_skills = metadata.get("skills") or []
    if isinstance(raw_skills, str):
        skill_names = [raw_skills]
    elif isinstance(raw_skills, list):
        skill_names = [str(s) for s in raw_skills if str(s).strip()]
    else:
        skill_names = []
    planet = metadata.get("planet")

    agent_content: Optional[str] = None
    skills_content: List[Dict[str, str]] = []
    jit_generated = False

    if agent_name:
        candidates = []
        if planet:
            candidates.append(REPO_ROOT / f"planets/{planet}/agents/{agent_name}.md")
        candidates.append(REPO_ROOT / f"core/agents/{agent_name}.md")
        for path in candidates:
            if path.exists():
                agent_content = path.read_text(encoding="utf-8").strip()
                break
        if not agent_content:
            jit_generated = True
            agent_content = (
                f"# Role: {agent_name}\n"
                f"You are a specialized agent for tasks related to {agent_name}. "
                f"Apply domain expertise for the task requested."
            )
    else:
        jit_generated = True

    for skill in skill_names:
        candidates = []
        if ":" in skill:
            skill_planet, skill_id = skill.split(":", 1)
            candidates.append(REPO_ROOT / f"planets/{skill_planet}/skills/{skill_id}/SKILL.md")
        else:
            if planet:
                candidates.append(REPO_ROOT / f"planets/{planet}/skills/{skill}/SKILL.md")
            candidates.append(REPO_ROOT / f"core/skills/{skill}/SKILL.md")

        for skill_path in candidates:
            if skill_path.exists():
                skill_description = _extract_skill_description(skill_path)
                if skill_description:
                    skills_content.append({"name": skill, "description": skill_description})
                    break
        else:
            print(f"[solar-router] skill not found: {skill}", file=sys.stderr)

    return {
        "agent_name": agent_name,
        "agent_content": agent_content,
        "skills_content": skills_content,
        "jit_generated": jit_generated,
        "planet": planet,
    }


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
    jit_context: Optional[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = []
    lines.append(system_prompt)

    if jit_context and jit_context.get("agent_content"):
        lines.append("")
        lines.append("## Agent Role")
        lines.append(jit_context["agent_content"])

    if jit_context and jit_context.get("skills_content"):
        lines.append("")
        lines.append("## Available Skills")
        lines.append("Invoke these skills by name when needed for the task:")
        for skill in jit_context["skills_content"]:
            lines.append(f"- {skill['name']}: {skill['description']}")

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
# Provider selection — delegates to adapters
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


def run_with_fallback(prompt: str) -> tuple:
    """Run prompt through providers in priority order. Returns (output, provider_used)."""
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
    """Run prompt with a specific provider, no fallback. Returns (output, provider_used)."""
    output = PROVIDERS[provider].run(prompt)
    return output, provider


# ---------------------------------------------------------------------------
# Async draft creation
# ---------------------------------------------------------------------------

def create_async_draft(title: str, description: str) -> Optional[str]:
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
    output = proc.stdout.strip()
    for line in output.splitlines():
        if "task_id" in line.lower():
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return lines[-1] if lines else None


# ---------------------------------------------------------------------------
# Output parsing for mode=auto
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def parse_ai_decision_output(raw_output: str) -> Dict[str, Any]:
    """
    Parse AI output for mode=auto. Expects JSON with decision.kind and reply_text.
    Degrades to direct_reply when JSON is not found but output is non-empty.
    """
    text = raw_output.strip()

    try:
        parsed = json.loads(_strip_code_fences(text))
        if isinstance(parsed, dict) and "decision" in parsed:
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and "decision" in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    if text:
        return {
            "decision": {"kind": "direct_reply"},
            "reply_text": text,
            "_degraded": True,
        }

    raise ValueError("AI output is empty and unparseable")


# ---------------------------------------------------------------------------
# Decision engine
# ---------------------------------------------------------------------------

def decision_engine(
    mode: str,
    channel: str,
    ai_output: Optional[str],
    request_id: str,
    user_text: str,
) -> Dict[str, Any]:
    if mode == "direct_only":
        return {"kind": "direct_reply", "task_id": None, "priority_suggested": None}

    if mode == "async_only":
        return {"kind": "async_draft_created", "task_id": None, "priority_suggested": "normal"}

    if mode == "auto":
        if channel == "async-task":
            return {"kind": "direct_reply", "task_id": None, "priority_suggested": None}
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
# Request parsing
# ---------------------------------------------------------------------------

def parse_request_payload(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as strict_exc:
        payload = json.loads(raw, strict=False)
        print(
            f"[solar-router] non-strict JSON parse accepted input: {strict_exc}",
            file=sys.stderr,
        )
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
# Core routing function
# ---------------------------------------------------------------------------

def route(raw: str) -> Dict[str, Any]:
    """Process a raw JSON request string. Returns a RouterResponse dict.

    status='success' → caller should exit 0.
    status='failed'  → caller should exit 1.
    """
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
        return _failed(
            request_id, "invalid_mode",
            f"unsupported mode: {mode}. valid: {sorted(VALID_MODES)}",
        )

    if provider_override and provider_override not in SUPPORTED_PROVIDERS:
        return _failed(
            request_id, "unsupported_provider",
            f"unsupported provider: {provider_override}",
        )

    if channel not in VALID_CHANNELS:
        channel = "other"

    conversation_id = user_id or session_id or "default"
    conv_path = conversation_file(conversation_id)

    # --- Audit: start ---
    t_start = time.monotonic()
    metadata = payload.get("metadata") or {}
    audit_log(
        router_id, "start",
        request_id=request_id,
        user_id=user_id,
        channel=channel,
        mode=mode,
        metadata=metadata,
    )

    # --- async_only: bypass AI, create draft directly ---
    if mode == "async_only":
        if not async_tasks_enabled():
            return _failed(
                request_id, "async_tasks_disabled",
                "mode=async_only requested but async-tasks feature is not enabled in SOLAR_SYSTEM_FEATURES",
            )
        reply_text = f"Creando tarea asíncrona: {text[:80].strip()}"
        try:
            task_id: Optional[str] = create_async_draft(text[:80].strip(), text)
        except Exception as exc:
            return _failed(request_id, "async_draft_failed", str(exc))
        append_message(conv_path, "user", text)
        append_message(conv_path, "assistant", reply_text)
        return {
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
        }

    # --- JIT Context Resolution ---
    jit_context = resolve_jit_context(metadata) if metadata else None

    system_prompt = read_system_prompt()
    recent = load_recent_messages(conv_path)
    full_prompt = build_prompt(system_prompt, recent, text, conversation_id, mode, channel, jit_context)

    # --- Execute AI ---
    provider_used: Optional[str] = None
    try:
        if provider_override:
            try:
                ai_output, provider_used = run_strict_provider(provider_override, full_prompt)
            except Exception as exc:
                return _failed(
                    request_id, "provider_locked_failed", str(exc),
                    provider_used=provider_override,
                )
        else:
            ai_output, provider_used = run_with_fallback(full_prompt)
    except Exception as exc:
        return _failed(request_id, "all_providers_failed", str(exc))

    # --- Decision engine ---
    try:
        ai_output_for_decision = (
            ai_output if mode == "auto" and channel != "async-task" else None
        )
        decision = decision_engine(mode, channel, ai_output_for_decision, request_id, text)
    except ValueError as exc:
        return {
            "status": "failed",
            "request_id": request_id,
            "provider_used": provider_used,
            "reply_text": ai_output,
            "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
            "error_code": "decision_engine_failed",
            "error": str(exc),
        }

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
                task_id = create_async_draft(text[:80].strip(), reply_text or text)
                decision["task_id"] = task_id
            except Exception as exc:
                reply_text = f"{reply_text}\n\n[Warning: async draft creation failed: {exc}]"
                decision["kind"] = "direct_reply"
                decision["task_id"] = None
        else:
            decision["kind"] = "direct_reply"
            decision["task_id"] = None

    # --- Persist conversation ---
    append_message(conv_path, "user", text)
    append_message(conv_path, "assistant", reply_text)

    # --- Audit: end ---
    audit_log(
        router_id, "end",
        status="success",
        provider=provider_used,
        jit_generated=bool(jit_context and jit_context.get("jit_generated")),
        duration_ms=int((time.monotonic() - t_start) * 1000),
    )

    return {
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
    }
