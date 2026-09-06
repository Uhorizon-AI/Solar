# Solar WebSocket Message Contract

## Endpoint

- URL: `ws://127.0.0.1:8765/ws`

## Request payload

```json
{
  "type": "request",
  "request_id": "req_123",
  "session_id": "session_abc",
  "user_id": "user_001",
  "text": "Hello Solar",
  "channel": "n8n",
  "mode": "auto",
  "metadata": {
    "origin_channel": "telegram",
    "origin_chat_id": "456",
    "origin_request_id": "tg:123"
  }
}
```

`channel` is set by the HTTP bridge (`telegram|n8n|async-task|other`).

## Response payload

```json
{
  "type": "response",
  "request_id": "req_123",
  "status": "success",
  "reply_text": "Hello Solar",
  "provider_used": "codex",
  "decision": { "kind": "direct_reply" }
}
```

## HTTP n8n channel

- Auth (required): `Authorization: Bearer <SOLAR_N8N_WEBHOOK_SECRET>` on `POST /webhook/n8n`. Unset secret → `401` fail-closed. Missing Bearer → `401`. Wrong token → `403` (constant-time compare). `X-Solar-N8n-Secret` is not part of the production contract.
- Production: one synchronous POST. `async=true`, `SOLAR_N8N_DEFAULT_ASYNC`, and `GET /webhook/n8n/result` return HTTP `200` with `status: failed` (no job, no poll).
- `chat_id` is accepted as origin only if it is in `TELEGRAM_ALLOWED_CHAT_IDS` (CSV) or, when that key is absent, `TELEGRAM_CHAT_ID`.
- Idempotency: `$SOLAR_GATEWAY_RUN_DIR/n8n-jobs/` keyed by SHA-256 of `request_id` (dir `0700`, files `0600`). Replay reemits the original `reply_text`.

Example POST body from n8n:

```json
{
  "request_id": "tg:123",
  "session_id": "telegram:456",
  "user_id": "789",
  "chat_id": "456",
  "text": "Hello"
}
```

Canonical long-task ACK `reply_text` is `Me pongo con ello. Te aviso por aquí cuando termine.` (`GATEWAY_ASYNC_ACK`).

## Error response

```json
{
  "type": "response",
  "request_id": "req_123",
  "status": "failed",
  "reply_text": "Invalid request payload."
}
```

## Adapter rule

Channel adapters (Telegram, WhatsApp, webchat, n8n) must map channel payloads to this contract and map `reply_text` back to channel-specific reply calls.
