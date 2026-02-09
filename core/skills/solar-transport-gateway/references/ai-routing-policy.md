# AI Routing Policy (v1)

## Objective

Select which AI provider processes each inbound request in a deterministic way.

## Environment key

- `SOLAR_AI_PROVIDER_PRIORITY`

## Recommended defaults

```env
SOLAR_AI_PROVIDER_PRIORITY=codex,claude,gemini
```

## Behavior

- The first provider is the primary one.
- Remaining providers are fallback order if the previous provider fails.
- Supported providers are enforced by the skill implementation, not by `.env`.
- Provider execution is handled by `scripts/run_ai_router.py`.
- You can override provider command templates with:
  - `SOLAR_AI_CODEX_CMD`
  - `SOLAR_AI_CLAUDE_CMD`
  - `SOLAR_AI_GEMINI_CMD`
- Router timeout keys:
  - `SOLAR_AI_PROVIDER_TIMEOUT_SEC` (per provider call)
  - `SOLAR_AI_ROUTER_TIMEOUT_SEC` (bridge-level timeout)
- Conversation continuity keys:
  - `SOLAR_RUNTIME_DIR` (default: `sun/runtime/transport-gateway`)
  - `SOLAR_SYSTEM_PROMPT_FILE` (default skill asset prompt)
  - `SOLAR_CONTEXT_TURNS` (default: `12`)

## Notes

- If the first provider fails (auth/model access/error), the bridge retries next providers in
  `SOLAR_AI_PROVIDER_PRIORITY` order.
- Router keeps local conversation history and injects recent turns into each provider prompt.
