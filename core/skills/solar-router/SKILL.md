---
name: solar-router
description: >
  Shared router that runs AI providers (Codex, Claude, Gemini) with Solar repo context.
  Single source of truth for provider selection, fallback, and async routing policy.
  Use when transport-gateway, async-tasks, or other runtimes need to invoke an AI with
  cwd = repo root and paths resolved against REPO_ROOT.
---

# Solar Router

## Purpose

Single source of truth for all AI execution in Solar:
- **Provider selection and fallback** live only here.
- **Async routing policy** (`direct_reply` vs `async_draft_created`) lives only here.
- Used by solar-transport-gateway (WebSocket/bridge) and solar-async-tasks (task execution).

## Scope

- Accept JSON payload (router contract v3) on stdin; output structured JSON on stdout.
- Run the selected provider with `cwd=REPO_ROOT` so all providers see `sun/`, `planets/`, `core/`, `AGENTS.md`.
- Resolve `SOLAR_ROUTER_SYSTEM_PROMPT_FILE` and `SOLAR_ROUTER_RUNTIME_DIR` against `REPO_ROOT` when relative.
- Codex default command includes `-C <repo-root>` and `--add-dir ~/.codex`.
- Persist conversation turns in runtime dir (JSONL) for continuity.
- Implement `DecisionEngine`: decide `decision.kind` based on `mode`, `channel`, and AI semantic output.

## Required MCP

None

## Setup

```bash
# Configure router environment variables (SOLAR_ROUTER_*, timeouts, etc.)
bash core/skills/solar-router/scripts/onboard_router_env.sh
```

**Key environment variables:**
- `SOLAR_ROUTER_PROVIDER_PRIORITY` — Comma-separated provider list (e.g., `codex,claude,gemini`)
- `SOLAR_ROUTER_RUNTIME_DIR` — Where conversation history is stored (default: `sun/runtime/router`)
- `SOLAR_ROUTER_SYSTEM_PROMPT_FILE` — System prompt file path (default: `core/skills/solar-router/assets/system_prompt.md`)
- `SOLAR_ROUTER_CONTEXT_TURNS` — Number of conversation turns to include (default: `12`)
- `SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC` — Per-provider timeout (default: `300`)
- `SOLAR_ROUTER_TIMEOUT_SEC` — Router-level timeout (default: `310`)

Optional command overrides:
- `SOLAR_ROUTER_CODEX_CMD`
- `SOLAR_ROUTER_CLAUDE_CMD`
- `SOLAR_ROUTER_GEMINI_CMD`

## Validation commands

```bash
# Validate skill structure
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-router /tmp

# Diagnose router / preflight providers (native helper in this skill)
bash core/skills/solar-router/scripts/diagnose_router.sh --dry-run
bash core/skills/solar-router/scripts/diagnose_router.sh

# Full error output when a provider fails (e.g. 401, binary not found)
bash core/skills/solar-router/scripts/diagnose_router.sh --verbose

# Smoke tests: validate router contract v3, bridge delegation, execute_active.py JSON parsing
bash core/skills/solar-router/scripts/check_router.sh
```

## Router contract v3

### Input (stdin JSON)

```json
{
  "request_id": "string",
  "session_id": "string",
  "user_id": "string",
  "text": "string",
  "channel": "telegram|n8n|async-task|other",
  "mode": "auto|direct_only|async_only",
  "provider": "codex|claude|gemini|null",
  "metadata": {}
}
```

- `provider`: optional. If set, strict mode — no fallback. If fails → `error_code: provider_locked_failed`.
- `mode`: defaults to `auto`. `direct_only` always returns `direct_reply`. `async_only` requires `async-tasks` feature enabled.
- `channel`: used by `DecisionEngine` for semantic routing in `mode=auto`.

### Output (stdout JSON)

```json
{
  "status": "success|failed",
  "request_id": "string",
  "provider_used": "codex|claude|gemini",
  "reply_text": "string",
  "decision": {
    "kind": "direct_reply|async_draft_proposal|async_draft_created|async_activation_needed",
    "task_id": "string|null",
    "priority_suggested": "high|normal|low|null"
  },
  "error_code": "string|null",
  "error": "string|null"
}
```

## DecisionEngine rules

1. `mode=direct_only` → `decision.kind=direct_reply` always.
2. `mode=async_only` + `async-tasks` enabled → `decision.kind=async_draft_created`.
3. `mode=async_only` + `async-tasks` disabled → `status=failed` + explicit error.
4. `mode=auto` + `channel=async-task` → `decision.kind=direct_reply` (already in queue).
5. `mode=auto` + `channel=telegram|n8n|other` → AI decides semantically via structured JSON output.

## Consumers

- **solar-transport-gateway:** `run_websocket_bridge.py` and HTTP webhook bridge call the router with full v3 contract.
- **solar-async-tasks:** `execute_active.py` (via `execute_active.sh`) calls the router with `channel=async-task`, `mode=direct_only`.

## References

- `references/routing-policy.md` — provider priority, env keys, repo-context policy, v3 contract rules.
