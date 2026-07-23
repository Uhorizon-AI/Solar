---
name: solar-gateway
description: >
  HTTP webhook and WebSocket entry point for external integrations (n8n, Telegram).
  Delegates to solar-router. Not Solar App UI (`solar-app` on :9000).
---

# Solar Gateway

## Purpose

Provide a reusable local transport layer for Solar:
- receive inbound messages over WebSocket,
- process request/response loop in one place,
- keep channel adapters decoupled from runtime transport,
- manage Telegram webhook operations from this same skill.

## Scope

- Run local WebSocket server for bidirectional messaging.
- Run local HTTP webhook bridge with channel routes (`/webhook/<channel>`).
- Define stable message contract for channel adapters.
- Keep implementation lightweight and deterministic.

## Required MCP

None

## Dependencies

- **solar-router:** This skill depends on `solar-router` for AI provider execution. Ensure `solar-router` is configured first:
  ```bash
  bash core/skills/solar-router/scripts/onboard_router_env.sh
  bash core/skills/solar-router/scripts/diagnose_router.sh
  ```

## Validation commands

```bash
# One-command setup (recommended)
bash core/skills/solar-gateway/scripts/setup_transport_gateway.sh

# Restart after .env changes (stop owned runtime + start; runs preflight first)
bash core/skills/solar-gateway/scripts/setup_transport_gateway.sh --restart

# Dry-run stop (ownership report; no kill)
bash core/skills/solar-gateway/scripts/stop_transport_gateway.sh --dry-run

# Stop owned processes (--force kills foreign blockers; --tunnel-only skips bridges)
bash core/skills/solar-gateway/scripts/stop_transport_gateway.sh
bash core/skills/solar-gateway/scripts/stop_transport_gateway.sh --tunnel-only

# Validate skill quality and structure
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-gateway /tmp

# Bootstrap .env block for this skill
bash core/skills/solar-gateway/scripts/onboard_websocket_env.sh

# Validate runtime prerequisites
bash core/skills/solar-gateway/scripts/validate_websocket_bridge.sh

# Preflight AI providers
bash core/skills/solar-router/scripts/diagnose_router.sh --dry-run
bash core/skills/solar-router/scripts/diagnose_router.sh
bash core/skills/solar-router/scripts/list_supported_providers.sh

# Check runtime health (local + public) — exit 0/1/2; drift does not change check exits
bash core/skills/solar-gateway/scripts/check_transport_gateway.sh

# Ensure gateway is healthy, recover if not (used by solar-system orchestrator)
# Drift-first: env stamp mismatch → preflight → setup --restart
# Partial without drift → tunnel-only; partial with drift → full restart
bash core/skills/solar-gateway/scripts/ensure_transport_gateway.sh

# Smoke: priority change → ensure → new process env (restores .env afterward)
bash core/tests/skills/solar-gateway/smoke_priority_ensure.sh

# Register and verify Telegram webhook
bash core/skills/solar-gateway/scripts/set_telegram_webhook.sh
bash core/skills/solar-gateway/scripts/verify_telegram_webhook.sh

# Configure stable named tunnel (recommended for production)
bash core/skills/solar-gateway/scripts/configure_named_tunnel.sh

# Direct runtime check without local .venv
uv run --with websockets==12.0 python3 -c "import websockets; print(websockets.__version__)"

# Sync core changes to local clients
solar client sync
```

## Lifecycle (stop / setup / ensure)

- **No listener reuse:** setup fails if WS/HTTP ports are busy unless `--restart`.
- **Stop** is the only kill path: ownership via bridge cmdline signatures + port/pid file; tunnel via `cloudflared.pid` + cmdline (no global cloudflared scan).
- **Env stamp** lives at `$SOLAR_WORKSPACE/sun/runtime/gateway/env.stamp` (fingerprint of an allowlisted key set — not `.env` mtime). Missing stamp with live Solar bridges counts as drift.
- **Drift / restart** runs a **non-destructive preflight** before stopping a healthy runtime. Preflight failure writes `env.fail` and leaves processes running. Provider tokens are validated against solar-router `PROVIDERS` (via `list_supported_providers.sh`), not a duplicated list.
- **Backoff:** repeated failures with the same fingerprint are throttled via `env.fail` (exponential, capped). After `GATEWAY_FAIL_ATTEMPTS_CAP` (default 5) failures with the same fingerprint, ensure **stops retrying** until the fingerprint changes (fix `.env` or remove `env.fail`). A fingerprint change resets backoff.
- **mkdir-lock** (portable, no `flock`) at `sun/runtime/gateway/lock/` serializes ensure/setup/stamp writes. Distinct from the solar-system orchestrator lock. Dead or recycled lock PIDs are reclaimed.

## Runtime requirements

- `uv`
- Python dependency resolved at runtime by `uv`: `websockets==12.0`
- At least one AI client CLI in `PATH`:
  - `codex`, `claude`, `agy`, or `agent`
- Local runtime write access for conversation memory (default: `sun/runtime/router/`)

## System activation (via solar-system)

For host-level orchestration through one LaunchAgent, enable this feature in:

```dotenv
# [solar-system] required environment
SOLAR_SYSTEM_FEATURES=transport-gateway
```

Or combined with async tasks:

```dotenv
SOLAR_SYSTEM_FEATURES=async-tasks,transport-gateway
```

Then install/update Solar LaunchAgent:

```bash
bash core/skills/solar-system/scripts/install_launchagent_macos.sh
```

## Laptop runtime note (optional)

- This skill can expose long-running local runtime endpoints (webhook/bridge/server/tunnel).
- If the active host is a laptop, host sleep can stop the runtime and break reachability.
- This is a host operations concern, not a mandatory dependency of the skill.
- If multiple laptops are used, only one active host should serve the same public webhook route at a time.

## Workflow

1. Run `setup_transport_gateway.sh` as default end-to-end flow (writes `env.stamp` on success).
2. After editing watched `.env` keys, either wait for the next `ensure_transport_gateway.sh` tick or run `setup_transport_gateway.sh --restart`.
3. Preview stop candidates with `stop_transport_gateway.sh --dry-run` before a manual restart.
4. If needed, run `setup_transport_gateway.sh --prepare-only` to stop before long-running services.
5. For stable DNS, configure named tunnel with `configure_named_tunnel.sh` and set `SOLAR_TUNNEL_MODE=named`.
6. All AI execution and routing policy is delegated to **solar-router** (`core/skills/solar-router/scripts/run_router.py`). This skill does not select providers or implement fallback.
7. Use individual scripts only for troubleshooting or partial reconfiguration.

## Dependency policy

- This skill must not create or rely on an in-repo `.venv`.
- Runtime Python dependencies are executed directly with `uv run --with ...`.
- Install `uv` once on the host, for example `brew install uv`.

## Conversation continuity

Managed entirely by `solar-router`. See skill `solar-router` for details.

## Message contract (v3)

This skill is a **pure delegate** to `solar-router`. No provider selection, no fallback, no async policy here.

Inbound `request` (WS bridge):
- `type`: `request`
- `request_id`: unique id
- `session_id`: conversation session id
- `user_id`: user identifier
- `text`: user message
- `channel`: `telegram|n8n|async-task|other` (set by HTTP bridge before forwarding)
- `mode`: `auto|direct_only|async_only` (set by HTTP bridge based on caller)
- `provider`: optional — if set, strict mode in router (no fallback)

Outbound `response` (WS bridge — router v3 JSON + envelope):
- `type`: `response`
- `request_id`: mirrors inbound id
- `status`: `success|failed`
- `provider_used`: provider that responded
- `reply_text`: generated reply text
- `decision.kind`: `direct_reply|async_draft_created|async_activation_needed|async_draft_proposal`
- `decision.task_id`: task id if async draft was created
- `error_code`: optional, for consumer routing
- `error`: human-readable error detail

HTTP bridge channel mapping:
- Telegram inbound → `channel=telegram`, `mode=auto`
- n8n inbound → `channel=n8n`, `mode=auto`
- n8n response: router v3 JSON exposed directly (no legacy double-wrapper)

## References

- `references/message-contract.md`
- Routing policy: `core/skills/solar-router/references/routing-policy.md`
- `references/telegram-webhook-flow.md`
