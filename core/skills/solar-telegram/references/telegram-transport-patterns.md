# Telegram Transport Patterns

## Modes

### 1) Bridge mode (Telegram -> local -> Telegram)

Use this when you want Sun responses from local runtime:

1. Telegram inbound message arrives to orchestrator (for example n8n webhook).
2. Orchestrator forwards message payload to local Solar entrypoint.
3. Local Solar computes response from local `sun/` + `planets/` context.
4. Orchestrator sends response back to Telegram chat.

Notes:
- Keep `sun/` and `planets/` local-only.
- Use correlation id per message for traceability.
- Telegram inbound is forwarded to WS bridge with `channel=telegram`, `mode=auto`.
- Routing policy (direct vs async) is decided by `solar-router` DecisionEngine — not by the bridge.
- `decision.kind` from router v3 controls the response flow:
  - `direct_reply`: send `reply_text` directly to Telegram chat.
  - `async_draft_created` / `async_draft_proposal`: send control message (draft created, ask for activation confirmation).
  - Activation (`plan.sh` + `approve.sh`) requires a second explicit confirmation from the user — never auto-queued.

### 2) Alert mode (local -> Telegram)

Use this for proactive notifications:

1. Local event triggers notification.
2. Run `scripts/send_telegram.sh` with message text.
3. Telegram receives alert in default `TELEGRAM_CHAT_ID`.

## Environment contract

Required:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional:
- `TELEGRAM_PARSE_MODE`
- `TELEGRAM_DISABLE_PREVIEW`

Keep values in root `.env` (gitignored).
