# AI Routing Policy (v3)

## Objective

`solar-router` is the **single source of truth** for all AI execution in Solar:
- Provider selection and fallback live only in the router.
- Async routing policy (`direct_reply` vs `async_draft_created`) lives only in the router.
- Consumers (transport-gateway, async-tasks) delegate 100% to the router and consume the structured v3 response.

All providers (Codex, Claude, Gemini) run with the same repo context: working directory = Solar repo root, so they see `sun/`, `planets/`, `core/`, and `AGENTS.md`.

## Environment keys

- `SOLAR_ROUTER_PROVIDER_PRIORITY` — Comma-separated provider list (e.g., `codex,claude,gemini`)
- `SOLAR_SYSTEM_FEATURES` — CSV of enabled features (e.g., `async-tasks,transport-gateway`). Router reads this to check if `async-tasks` is enabled.

## Recommended defaults

```env
SOLAR_ROUTER_PROVIDER_PRIORITY=codex,claude,gemini
SOLAR_SYSTEM_FEATURES=async-tasks,transport-gateway
```

## Provider selection behavior

- The first provider in `SOLAR_ROUTER_PROVIDER_PRIORITY` is primary.
- Remaining providers are fallback order if the previous provider fails.
- Supported providers are enforced by the router implementation.
- **Strict mode**: if `provider` field is set in the request, only that provider is used — no fallback. On failure → `error_code: provider_locked_failed`.
- **Priority mode**: if `provider` is not set, router tries providers in order until one succeeds.

## Repo context (all providers)

- The router runs each provider with `cwd` = repo root.
- Relative paths (`SOLAR_ROUTER_SYSTEM_PROMPT_FILE`, `SOLAR_ROUTER_RUNTIME_DIR`) are resolved against the repo root.
- Codex additionally receives `-C <repo-root>` and `--add-dir ~/.codex` in its command.

## Command overrides

- `SOLAR_ROUTER_CODEX_CMD`
- `SOLAR_ROUTER_CLAUDE_CMD`
- `SOLAR_ROUTER_GEMINI_CMD`

Default Codex command is repo-anchored: `codex exec --skip-git-repo-check --full-auto -C <repo-root> --add-dir ~/.codex --`

## Timeout keys

- `SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC` (per provider call, default: `300`)
- `SOLAR_ROUTER_TIMEOUT_SEC` (router-level timeout, default: `310`)

## Conversation continuity keys

- `SOLAR_ROUTER_RUNTIME_DIR` (default: `sun/runtime/router`), resolved against repo root if relative
- `SOLAR_ROUTER_SYSTEM_PROMPT_FILE` (default: `core/skills/solar-router/assets/system_prompt.md`), resolved against repo root if relative
- `SOLAR_ROUTER_CONTEXT_TURNS` (default: `12`)

## DecisionEngine — mode and channel rules

| mode          | channel      | decision.kind          | notes                                          |
|---------------|--------------|------------------------|------------------------------------------------|
| `direct_only` | any          | `direct_reply`         | Always direct, no AI decision needed           |
| `async_only`  | any          | `async_draft_created`  | Requires `async-tasks` in SOLAR_SYSTEM_FEATURES |
| `async_only`  | any          | `failed`               | If `async-tasks` not enabled                   |
| `auto`        | `async-task` | `direct_reply`         | Already in queue, never re-propose async       |
| `auto`        | other        | AI decides semantically | AI returns JSON with `decision.kind`           |

## Async draft creation rule

- Router calls `core/skills/solar-async-tasks/scripts/create.sh` directly via subprocess.
- No direct file writes from router.
- Draft creation only if `async-tasks` is in `SOLAR_SYSTEM_FEATURES`.
- Activation (`plan.sh` + `approve.sh`) requires explicit second confirmation from user — never auto-queued.

## Caller mapping (approved)

| Caller              | channel       | mode          |
|---------------------|---------------|---------------|
| Telegram inbound    | `telegram`    | `auto`        |
| n8n inbound         | `n8n`         | `auto`        |
| async-task execution| `async-task`  | `direct_only` |
| `async_only` flows  | any           | `async_only`  |

## Router contract v3 — input

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

## Router contract v3 — output

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

## n8n bridge output rule

- HTTP webhook bridge for n8n exposes the router v3 JSON directly.
- No legacy double-wrapper (`solar_status` / `solar_response`).
- Only minimal bridge metadata (`bridge`, `route`) is added.

## Migration from v1/v2 to v3

Legacy variable names are supported with automatic fallback:
- `SOLAR_AI_PROVIDER_PRIORITY` → `SOLAR_ROUTER_PROVIDER_PRIORITY`
- `SOLAR_RUNTIME_DIR` → `SOLAR_ROUTER_RUNTIME_DIR`
- `SOLAR_SYSTEM_PROMPT_FILE` → `SOLAR_ROUTER_SYSTEM_PROMPT_FILE`
- `SOLAR_CONTEXT_TURNS` → `SOLAR_ROUTER_CONTEXT_TURNS`
- `SOLAR_AI_PROVIDER_TIMEOUT_SEC` → `SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC`
- `SOLAR_AI_ROUTER_TIMEOUT_SEC` → `SOLAR_ROUTER_TIMEOUT_SEC`
- `SOLAR_AI_{PROVIDER}_CMD` → `SOLAR_ROUTER_{PROVIDER}_CMD`

Run `bash core/skills/solar-router/scripts/onboard_router_env.sh` to migrate automatically.

## Key invariants (enforced)

1. No provider selection or fallback outside `solar-router`.
2. No async routing policy outside `solar-router`.
3. `decision.kind` is the official flow control field for all consumers.
4. `provider` in request → strict mode, no fallback.
5. Async activation always requires second explicit user confirmation.
