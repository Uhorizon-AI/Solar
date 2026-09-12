---
name: solar-mcp
description: >
  Solar's own MCP server: read-only context as resources, verbs as tools behind
  a gate that validates authority and mandate in the handler and refuses on its
  own. Use it to connect any MCP client to Solar without opening the workspace.
---

# Solar MCP

A client connects from any folder, reads Solar's context as **resources**, and
calls **tools** that cannot execute until the handler says so. The refusal is
the point: it does not depend on the calling agent choosing to behave.

## Required MCP

None. This *is* the server.

## CLI

```bash
# serve on stdio (this is what an MCP client launches)
python3 core/skills/solar-mcp/scripts/mcp_server.py

# grant an approval for one exact call, then hand over the id
python3 core/skills/solar-mcp/scripts/mcp_approve.py grant solar_task_create \
  --args '{"title":"Revisar propuesta"}'

# the same for an outbound message: the text is part of what is approved
python3 core/skills/solar-mcp/scripts/mcp_approve.py grant solar_telegram_send \
  --args '{"text":"Listo el informe"}'

# exercise the server as a client would
python3 core/skills/solar-mcp/scripts/mcp_probe.py list
python3 core/skills/solar-mcp/scripts/mcp_probe.py call solar_task_status '{}'
```

## Resources (open)

| URI | What it serves |
|---|---|
| `solar://health` | Storage, gateway and continuity, as the console sees them |
| `solar://tasks` | Every task file by state, with its recurrence |
| `solar://index` | Counters of the SQLite projection and which sources went stale |
| `solar://delegations` | Written A3 mandates: mode and validity |
| `solar://gate` | What this server allowed and refused |

## Tools (gated)

| Tool | Authority | Passes when |
|---|---|---|
| `solar_task_status` | A0 | Always. Reading is not gated. |
| `solar_task_create` | A2 | An approval granted out of band matches this exact call |
| `solar_telegram_send` | A2 | Same, for one exact message text. Sending outside the machine is never implicit |
| `solar_action_run` | A3 | The skill and action are registered **and** the mandate is live |

Approvals are server-side records: they name one tool and one set of arguments,
expire, and burn on first use. A client cannot mint one — that is what makes
this a gate.

Action skills are opt-in, listed in `<runtime>/mcp/action-skills.json`:

```json
{"calendar-sync": {"actions": ["status"], "mandate": "calendar-busy-sync",
                   "command": ["bash", "planets/louis/skills/calendar-sync/scripts/calendar_sync.sh"]}}
```

**Instruction skills never become tools.** They stay native to the harness; only
action verbs pass through here.

## Sending Telegram

`solar_telegram_send` is the route an agent has to Telegram, and the reason the
`solar-telegram` skill is no longer published to any client. The bot token is an
installation secret held by the process
(`<app data>/Solar/secrets/installation.env`, 0600): the server reads it and
hands it to `send_telegram.sh`, which refuses to look it up on its own.

The approval covers the exact text. Change a word and the call is refused with
`approval_scope_mismatch`, because the hash covers the arguments, not the tool
name alone. The chat must be the configured one or listed in
`TELEGRAM_ALLOWED_CHAT_IDS`.

## Where the guarantee ends

Inside: the Solar runtime and this server, with installation secrets the process
custodies. The two keys Solar sends with are no longer in a file the IDE indexes.

Outside, and said plainly rather than disguised:

- a process running as the user can read the 0600 store; this closes the
  mediated route, not the machine;
- a browser session already authenticated is untouched — `zoho-mail`,
  `whatsapp`, `linkedin-messages` and `linkedin-analytics` remain declarative,
  not coercive, until their send becomes a gated tool;
- the `.env` of a planet is the planet's. Solar does not mediate it.
