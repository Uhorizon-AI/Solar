---
name: solar-transport-gateway
description: >
  Build and run a local bidirectional transport for Solar runtime with WebSocket core
  and Telegram webhook bridge operations. Use when a user needs a channel-agnostic runtime
  transport plus internal scripts to manage tunnel, webhook registration, and inbound/outbound loop.
---

# Solar Transport Gateway

## Purpose

Provide a reusable local transport layer for Solar:
- receive inbound messages over WebSocket,
- process request/response loop in one place,
- keep channel adapters decoupled from runtime transport,
- manage Telegram webhook operations from this same skill.

## Scope

- Run local WebSocket server for bidirectional messaging.
- Run local HTTP webhook bridge with provider routes (`/webhook/<provider>`).
- Define stable message contract for channel adapters.
- Keep implementation lightweight and deterministic.

## Required MCP

None

## Dependencies

- **solar-router:** This skill depends on `solar-router` for AI provider execution. Ensure `solar-router` is configured first:
  ```bash
  bash core/skills/solar-router/scripts/onboard_router_env.sh
  bash core/skills/solar-router/scripts/check_providers.sh
  ```

## Validation commands

```bash
# One-command setup (recommended)
bash core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh

# Validate skill quality and structure
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-transport-gateway /tmp

# Install runtime dependencies
poetry -C core/skills/solar-transport-gateway install

# Bootstrap .env block for this skill
bash core/skills/solar-transport-gateway/scripts/onboard_websocket_env.sh

# Validate runtime prerequisites
bash core/skills/solar-transport-gateway/scripts/validate_websocket_bridge.sh

# Preflight AI providers
bash core/skills/solar-router/scripts/check_providers.sh --dry-run
bash core/skills/solar-router/scripts/check_providers.sh

# Check runtime health (local + public)
bash core/skills/solar-transport-gateway/scripts/check_transport_gateway.sh

# Register and verify Telegram webhook
bash core/skills/solar-transport-gateway/scripts/set_telegram_webhook.sh
bash core/skills/solar-transport-gateway/scripts/verify_telegram_webhook.sh

# Configure stable named tunnel (recommended for production)
bash core/skills/solar-transport-gateway/scripts/configure_named_tunnel.sh

# Sync core changes to local clients
bash core/scripts/sync-clients.sh
```

## Runtime requirements

- `poetry`
- Python dependency managed by Poetry: `websockets`
- At least one AI client CLI in `PATH`:
  - `codex`, `claude`, or `gemini`
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

1. Run `setup_transport_gateway.sh` as default end-to-end flow.
2. If needed, run `setup_transport_gateway.sh --prepare-only` to stop before long-running services.
3. For stable DNS, configure named tunnel with `configure_named_tunnel.sh` and set `SOLAR_TUNNEL_MODE=named`.
4. Route provider calls via **solar-router** (`core/skills/solar-router/scripts/run_router.py`), configured by `SOLAR_ROUTER_PROVIDER_PRIORITY`.
5. Use individual scripts only for troubleshooting or partial reconfiguration.

## Conversation continuity

- The **solar-router** script (see skill `solar-router`) stores conversation turns in local runtime memory (JSONL) by conversation id.
- Conversation id priority:
  1. `user_id`
  2. `session_id`
- Default system prompt file:
  - `core/skills/solar-router/assets/system_prompt.md`
- Override keys:
  - `SOLAR_ROUTER_RUNTIME_DIR`
  - `SOLAR_ROUTER_SYSTEM_PROMPT_FILE`
  - `SOLAR_ROUTER_CONTEXT_TURNS`

## Message contract (v1)

Inbound `request`:
- `type`: `request`
- `request_id`: unique id
- `session_id`: conversation session id
- `user_id`: user identifier
- `text`: user message

Outbound `response`:
- `type`: `response`
- `request_id`: mirrors inbound id
- `status`: `success` | `failed`
- `reply_text`: generated reply text

## References

- `references/message-contract.md`
- Routing policy: `core/skills/solar-router/references/routing-policy.md`
- `references/telegram-webhook-flow.md`
