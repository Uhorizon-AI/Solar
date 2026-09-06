# Telegram Webhook Flow (via solar-gateway)

## Components

1. WebSocket core:
- `run_websocket_bridge.sh`
- endpoint: `ws://127.0.0.1:8765/ws`

2. HTTP webhook bridge:
- `run_http_webhook_bridge.sh`
- base endpoint pattern: `http://127.0.0.1:8787/webhook/<channel>`
- Telegram endpoint: `http://127.0.0.1:8787/webhook/telegram` (only if a bot token is set)
- n8n endpoint: `http://127.0.0.1:8787/webhook/n8n` (synchronous POST; no production poll)

3. Public tunnel:
- `start_cloudflared_tunnel.sh`
- quick tunnel URL example: `https://xxxx.trycloudflare.com` (ephemeral)
- recommended: named tunnel + domain (`https://webhook.yourdomain.com`)

4. Telegram Bot API claim (`SOLAR_GATEWAY_CLAIM_TELEGRAM=true` only):
- `set_telegram_webhook.sh` — `getWebhookInfo` first; absent/`false` omits `setWebhook` (exit 0); `true` + foreign URL exits 1
- `verify_telegram_webhook.sh` — compares `getWebhookInfo.result.url` to expected Solar URL
- webhook target: `https://${SOLAR_CLOUDFLARED_HOSTNAME}${SOLAR_HTTP_WEBHOOK_BASE}/telegram`

## HTTP channels vs claim

These are separate. Do not use `SOLAR_TELEGRAM_WEBHOOK` or `OWNER`.

- `http channels:` routes under `SOLAR_HTTP_WEBHOOK_BASE` (`n8n`, and `telegram` if `TELEGRAM_BOT_TOKEN` is set).
- `telegram claim:` `true` / `false` / `absent` — only whether Solar may call `setWebhook`.

## Claim (`SOLAR_GATEWAY_CLAIM_TELEGRAM`)

- Absent or `false` → do not claim. `getWebhookInfo` is observational. Outbound Bot API `sendMessage` remains allowed.
- `true`: register only when the live URL is empty or already Solar. Foreign URL: setup/ensure skip (no rollback). Manual `set_telegram_webhook.sh` exits 1.

## Canonical inbound (this host: claim absent or `false`)

```text
Telegram → n8n Telegram Trigger → POST /webhook/n8n (Authorization: Bearer)
         → HTTP 200 reply_text → n8n sends reply_text to Telegram
```

- Generate secret: `openssl rand -base64 32` → `SOLAR_N8N_WEBHOOK_SECRET`.
- Header: `Authorization: Bearer <secret>`. Unset secret → `401` fail-closed. Missing → `401`; wrong → `403` (constant-time compare).
- One synchronous POST. HTTP 202 / `GET /webhook/n8n/result` are not the production contract.
- Long work: Solar creates a **parent** in `solar-async-tasks` (see `task-with-subtasks.md`), returns a short ACK, and notifies the origin chat only when the parent completes.

## Rollback path (`SOLAR_GATEWAY_CLAIM_TELEGRAM=true` and Solar owns the hook)

1. Telegram sends update to HTTP webhook bridge `/webhook/telegram`.
2. HTTP bridge maps update to Solar request contract.
3. HTTP bridge forwards request to local WebSocket core.
4. WebSocket core returns `reply_text`.
5. HTTP bridge sends `reply_text` to Telegram chat with Bot API.

## Tunnel modes

- `SOLAR_TUNNEL_MODE=quick`:
  - fast setup for local testing
  - URL can expire and fail DNS resolution

- `SOLAR_TUNNEL_MODE=named`:
  - stable DNS via your own hostname
  - requires one-time setup with `configure_named_tunnel.sh`

## Ownership lookup failure and concurrent n8n requests

A failed, malformed, or unsuccessful `getWebhookInfo` response is unknown ownership,
never an empty webhook. The explicit registration command refuses to proceed;
setup/ensure skips registration and keeps the gateway running. The lookup has a
bounded network timeout. A foreign webhook is never overwritten.

For n8n, a per-request OS file lock covers lookup, router execution, and snapshot
persistence. Concurrent copies of the same request wait and replay the stored
response. Distinct request IDs remain independent. Lock files retain their inode
and the OS releases ownership when a process exits; do not unlink live lock files.
