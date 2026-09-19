# Solar WebSocket Message Contract

## Endpoint

- URL: `ws://127.0.0.1:8765/ws`

## Request payload

```json
{
  "type": "request",
  "request_id": "telegram:456:123",
  "session_id": "telegram:456",
  "user_id": "user_001",
  "text": "Hello Solar",
  "channel": "n8n",
  "mode": "auto",
  "metadata": {
    "origin_channel": "telegram",
    "origin_chat_id": "456",
    "origin_request_id": "telegram:456:123"
  }
}
```

`channel` is set by the HTTP bridge (`telegram|n8n|async-task|other`) and names the entry point, not the platform. The router keys conversation continuity by `session_id`, falling back to `user_id` only when `session_id` is empty.

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

### Message identity

Solar is platform-agnostic. n8n sends the parts; the gateway composes the ids and never splits a composed id back.

| Field | Meaning | Set by |
|---|---|---|
| `channel` | Platform the message comes from (`telegram`, `whatsapp`…), not the transport. Lowercased; must match `^[a-z0-9_-]+$` | n8n |
| `conversation_id` | Native conversation address, where replies go (Telegram `chat.id`) | n8n |
| `message_id` | Native message id; in Telegram unique only inside its chat | n8n |
| `user_id` | Sender | n8n |
| `session_id` | Continuity key: `channel:conversation_id` | gateway |
| `request_id` | Idempotency key: `channel:conversation_id:message_id` | gateway |

Example POST body from n8n:

```json
{
  "type": "request",
  "channel": "telegram",
  "conversation_id": "456",
  "message_id": "123",
  "user_id": "789",
  "text": "Hello"
}
```

- Before composing, `%` and `:` inside `conversation_id` and `message_id` are escaped as `%25` and `%3A`, so different parts never compose the same id (`a:b` + `c` → `custom:a%3Ab:c`; `a` + `b:c` → `custom:a:b%3Ac`). Numeric Telegram ids are unchanged.
- `channel` and `conversation_id` are required together. Any part without both → `identity_incomplete`; a malformed `channel` → `invalid_channel`.
- If `session_id` is also sent, it must equal `channel:conversation_id` exactly (or be omitted) → otherwise `session_chat_mismatch`.
- Identity errors are answered with HTTP `200`, `status: failed`, before the idempotency ledger: they never replay another request's response and are never stored, so a corrected body with the same `request_id` still runs.
- For `channel = telegram`, `conversation_id` is the origin chat for the completion notify (subject to the allowlist above). Other platforms get a session but no notify.
- The router still receives `channel: n8n` (the entry point, which drives `SOLAR_N8N_AUTO_QUEUE`); the platform travels in `metadata.origin_channel`.

Legacy body, still accepted when no parts are sent, with or without `type: request` (used as sent; `chat_id` optional and must match `session_id`, otherwise `session_chat_mismatch` before the ledger). A missing `session_id` stays empty, so the router keys continuity by `user_id`:

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
