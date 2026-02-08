# Telegram-First n8n Workflow Reference

## Goal

Provide a baseline workflow to receive Telegram messages, route intent, and return a response safely.

## Minimal Node Chain

1. Telegram Trigger
2. Normalize Input (Function/Set node)
3. Intent Router (Switch node)
4. Action Branch (tool call / webhook / static response)
5. Telegram Reply
6. Error Branch (fallback message)

## Input Contract

- `chat_id`
- `user_id`
- `message_text`
- `timestamp`

## Output Contract

- `status`: success | partial | failed
- `reply_text`
- `next_action` (optional)

## Reliability Defaults

- Add timeout guard for external calls.
- Add one retry for transient network failure.
- Always provide a user-facing fallback reply on error.

## Security Notes

- Never hardcode bot tokens in workflow steps.
- Store credentials in n8n credential manager.
- Log only operational metadata, not sensitive message contents unless required.

## Validation Checklist

- Telegram trigger receives message.
- Router selects expected branch.
- Reply node returns message to same chat.
- Error branch returns graceful fallback.
