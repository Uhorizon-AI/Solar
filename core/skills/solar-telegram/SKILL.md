---
name: solar-telegram
description: >
  Build and operate Telegram transport for Solar with a local-first approach.
  Use when a user needs (1) Telegram -> local -> Telegram conversation routing,
  (2) outbound Telegram alerts, or (3) standardized Telegram environment setup
  based on `.env` and skill-owned scripts.
---

# Solar Telegram

## Purpose

Provide one reusable skill for Telegram transport in Solar:
- inbound/outbound conversation bridge (Telegram -> local -> Telegram),
- direct outbound alerts (local -> Telegram),
- simple `.env`-based setup and validation.

## Scope

- Keep transport logic reusable in `core/`.
- Keep secrets outside git in root `.env`.
- Keep deterministic operations inside this skill `scripts/`.

## Required MCP

None

## Validation commands

```bash
# Full setup runbook (recommended)
bash core/skills/solar-telegram/scripts/setup_telegram.sh --ping --test-message "Solar Telegram OK"

# Non-interactive setup check
bash core/skills/solar-telegram/scripts/setup_telegram.sh --non-interactive

# Sync core changes to local clients
bash core/scripts/sync-clients.sh
```

## Required environment variables

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` (default target chat for alerts)

Optional:
- `TELEGRAM_PARSE_MODE` (default: `Markdown`)
- `TELEGRAM_DISABLE_PREVIEW` (default: `true`)

## Laptop runtime note (optional, bridge mode)

- `alerts` mode does not require a long-running local endpoint.
- `bridge` mode may depend on long-running local runtime services.
- If bridge runtime is hosted on a laptop, host sleep can interrupt message flow.
- This is a host operations concern, not a mandatory dependency of this skill.

## Environment block format (required)

- Write Telegram variables in one compact skill-scoped block in root `.env`.
- Start block with header comment: `# [solar-telegram] required environment`.
- Keep block contiguous with no blank lines inside.
- Preserve existing values unless explicit overwrite is requested.

## Workflow

1. Confirm target mode: `bridge` or `alerts`.
2. Execute `setup_telegram.sh` as the default procedure from the agent (do not ask the user to run shell commands).
3. If values are missing, ask user for `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, then run setup with `--token` and `--chat-id`.
4. For bridge mode, use `references/telegram-transport-patterns.md` as the routing contract.
5. If skill files changed, run `bash core/scripts/sync-clients.sh`.

## Output format

- Selected mode (`bridge` or `alerts`)
- Required environment keys
- Commands executed
- Result and next action

## References

- `references/telegram-transport-patterns.md`
