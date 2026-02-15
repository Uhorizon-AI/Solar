# AI Routing Policy (v2)

## Objective

Select which AI provider processes each inbound request in a deterministic way. All providers (Codex, Claude, Gemini) run with the same repo context: working directory = Solar repo root, so they see `sun/`, `planets/`, `core/`, and `AGENTS.md` as when using the repo directly.

## Environment key

- `SOLAR_ROUTER_PROVIDER_PRIORITY`

## Recommended defaults

```env
SOLAR_ROUTER_PROVIDER_PRIORITY=codex,claude,gemini
```

## Behavior

- The first provider is the primary one.
- Remaining providers are fallback order if the previous provider fails.
- Supported providers are enforced by the skill implementation, not by `.env`.
- Provider execution is handled by `core/skills/solar-router/scripts/run_router.py`.
- **Repo context (all providers):** The router runs each provider with `cwd` = repo root. Relative paths (`SOLAR_ROUTER_SYSTEM_PROMPT_FILE`, `SOLAR_ROUTER_RUNTIME_DIR`) are resolved against the repo root. Codex additionally receives `-C <repo-root>` and `--add-dir ~/.codex` in its command.
- You can override provider command templates with:
  - `SOLAR_ROUTER_CODEX_CMD`
  - `SOLAR_ROUTER_CLAUDE_CMD`
  - `SOLAR_ROUTER_GEMINI_CMD`
- Default Codex command is repo-anchored: `codex exec --skip-git-repo-check --full-auto -C <repo-root> --add-dir ~/.codex --`
- Router timeout keys:
  - `SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC` (per provider call, default: `300`)
  - `SOLAR_ROUTER_TIMEOUT_SEC` (router-level timeout, default: `310`)
- Conversation continuity keys:
  - `SOLAR_ROUTER_RUNTIME_DIR` (default: `sun/runtime/router`), resolved against repo root if relative
  - `SOLAR_ROUTER_SYSTEM_PROMPT_FILE` (default: `core/skills/solar-router/assets/system_prompt.md`), resolved against repo root if relative
  - `SOLAR_ROUTER_CONTEXT_TURNS` (default: `12`)

## Notes

- The router executes a single provider per invocation. **Provider fallback logic is implemented by consumers** (transport-gateway, async-tasks) that retry subsequent providers from `SOLAR_ROUTER_PROVIDER_PRIORITY` if the first fails.
- Router keeps local conversation history and injects recent turns into each provider prompt.

## Migration from v1

Legacy variable names are supported with automatic fallback:
- `SOLAR_AI_PROVIDER_PRIORITY` → `SOLAR_ROUTER_PROVIDER_PRIORITY`
- `SOLAR_RUNTIME_DIR` → `SOLAR_ROUTER_RUNTIME_DIR`
- `SOLAR_SYSTEM_PROMPT_FILE` → `SOLAR_ROUTER_SYSTEM_PROMPT_FILE`
- `SOLAR_CONTEXT_TURNS` → `SOLAR_ROUTER_CONTEXT_TURNS`
- `SOLAR_AI_PROVIDER_TIMEOUT_SEC` → `SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC`
- `SOLAR_AI_ROUTER_TIMEOUT_SEC` → `SOLAR_ROUTER_TIMEOUT_SEC`
- `SOLAR_AI_{PROVIDER}_CMD` → `SOLAR_ROUTER_{PROVIDER}_CMD`

Run `bash core/skills/solar-router/scripts/onboard_router_env.sh` to migrate automatically.
