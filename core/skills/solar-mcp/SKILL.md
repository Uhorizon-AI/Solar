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

## What this does not close yet

The gate can be walked around: credentials still live in the workspace, so
anything able to read them can act without ever talking to this server. Closing
that path is the next corte. Until then, do not claim there is no other route.
