---
name: solar-router
description: >
  Shared router that runs AI providers (Codex, Claude, Gemini) with Solar repo context.
  Use when transport-gateway, async-tasks, or other runtimes need to invoke an AI with
  cwd = repo root and paths resolved against REPO_ROOT.
---

# Solar Router

## Purpose

Provide a single entrypoint to run any supported AI provider (Codex, Claude, Gemini) with the same context as the Solar repo: working directory = repo root, relative paths resolved against `REPO_ROOT`. Used by solar-transport-gateway (WebSocket/bridge) and solar-async-tasks (task execution).

## Scope

- Accept JSON payload (provider, text, session_id, user_id) on stdin; output reply on stdout.
- Run the selected provider with `cwd=REPO_ROOT` so all providers see `sun/`, `planets/`, `core/`, `AGENTS.md`.
- Resolve `SOLAR_ROUTER_SYSTEM_PROMPT_FILE` and `SOLAR_ROUTER_RUNTIME_DIR` against `REPO_ROOT` when relative.
- Codex default command includes `-C <repo-root>` and `--add-dir ~/.codex`.
- Persist conversation turns in runtime dir (JSONL) for continuity.

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

# Preflight providers (native helper in this skill)
bash core/skills/solar-router/scripts/check_providers.sh --dry-run
bash core/skills/solar-router/scripts/check_providers.sh
```

## Consumers

- **solar-transport-gateway:** `run_websocket_bridge.py` and HTTP webhook bridge call the router script.
- **solar-async-tasks:** `execute_active.sh` calls the router to run active tasks with provider fallback.

## References

- `references/routing-policy.md` — provider priority, env keys, repo-context policy.
