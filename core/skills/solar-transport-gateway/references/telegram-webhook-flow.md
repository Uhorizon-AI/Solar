# Telegram Webhook Flow (via solar-transport-gateway)

## Components

1. WebSocket core:
- `run_websocket_bridge.sh`
- endpoint: `ws://127.0.0.1:8765/ws`

2. HTTP webhook bridge:
- `run_http_webhook_bridge.sh`
- base endpoint pattern: `http://127.0.0.1:8787/webhook/<channel>`
- Telegram endpoint: `http://127.0.0.1:8787/webhook/telegram`

3. Public tunnel:
- `start_cloudflared_tunnel.sh`
- quick tunnel URL example: `https://xxxx.trycloudflare.com` (ephemeral)
- recommended: named tunnel + domain (`https://webhook.yourdomain.com`)

4. Telegram webhook registration:
- `set_telegram_webhook.sh`
- webhook target: `https://${SOLAR_CLOUDFLARED_HOSTNAME}${SOLAR_HTTP_WEBHOOK_BASE}/telegram`

## Tunnel modes

- `SOLAR_TUNNEL_MODE=quick`:
  - fast setup for local testing
  - URL can expire and fail DNS resolution

- `SOLAR_TUNNEL_MODE=named`:
  - stable DNS via your own hostname
  - requires one-time setup with `configure_named_tunnel.sh`

## End-to-end loop

1. Telegram sends update to HTTP webhook bridge.
2. HTTP bridge maps update to Solar request contract.
3. HTTP bridge forwards request to local WebSocket core.
4. WebSocket core returns `reply_text`.
5. HTTP bridge sends `reply_text` to Telegram chat with Bot API.
