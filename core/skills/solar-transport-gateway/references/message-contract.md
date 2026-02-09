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
  "text": "Hello Solar"
}
```

## Response payload

```json
{
  "type": "response",
  "request_id": "req_123",
  "status": "success",
  "reply_text": "Hello Solar",
  "provider_used": "codex"
}
```

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

Channel adapters (Telegram, WhatsApp, webchat) must map channel payloads to this contract and map `reply_text` back to channel-specific reply calls.
