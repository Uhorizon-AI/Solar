---
name: solar-mcp
description: >
  Solar's own MCP server: three tools (search, docs, execute) over open resources
  and a registry of operations behind a gate that validates authority and mandate
  in the handler and refuses on its own. Use it to connect any MCP client to Solar
  without opening the workspace.
---

# Solar MCP

A client connects from any folder, reads Solar's context as **resources**, and
calls **three tools**. The third runs registered **operations** that cannot
execute until the handler says so. The refusal is the point: it does not depend
on the calling agent choosing to behave.

Runtime dependencies: `core/skills/solar-client/`, `core/skills/solar-app/`,
`core/skills/solar-router/`, `core/skills/solar-async-tasks/` and
`core/skills/solar-telegram/` (private sending implementation, not an agent tool).

## Required MCP

None. This *is* the server.

## CLI

Each client starts `solar mcp` as a stdio child; that child does not use a LaunchAgent.
Register once at user level; do not copy per-planet MCP configurations.
Python 3.11+ is required for registration; entries pin the interpreter for GUI launches.

```bash
solar mcp
solar mcp print --workspace /path/to/workspace
solar mcp install --workspace /path/to/workspace --dry-run
solar mcp install --workspace /path/to/workspace
solar mcp uninstall --dry-run
solar mcp uninstall
```

Client destinations, recovery and validation: [references/clients.md](references/clients.md).

## On-demand capabilities

When a native skill name is absent, call `solar_search` with `scope=capabilities`
and the user's objective or an exact `planet:skill` ID, then `solar_docs` with
that ID and revision. Read applicable workspace and planet governance
before using the instructions. Load listed references individually when needed;
`solar_docs` does not execute scripts, grant authority or verify dependencies.
Search spans eligible namespaces; a preferred namespace is a ranking hint.
Exclusions apply to both tools. Oversized units refuse without truncation.

Limits and lifecycle: [references/discovery.md](references/discovery.md).

## Approval workflow

1. Prepare the exact operation, arguments and destination. For `telegram.send` include an
   explicit `chat_id` and final text; apply the relevant communication gate first. For an
   existing task, read it first and pass its `row_version`.
2. Call `solar_execute` without `approval_id`. On clients advertising MCP form elicitation,
   the runtime presents a compact summary of the exact operation (action, task, changes and effect, from the
   validated arguments and the stored task) for confirmation, creates the approval and
   executes internally. Do not ask the user to create or copy an identifier.
3. Do not ask for conversational confirmation immediately before that native prompt.
   An existing valid approval may be passed internally and does not prompt again.
4. Never manufacture consent with `approved=true`, an agent-authored note or a shell
   grant. If the client lacks elicitation, report the integration limitation and use
   a trusted operator/host approval path. Never bypass the gate.
5. Report success only from the execution result. On uncertain failure, check the
   resulting state before requesting another execution.

An explicit local instruction can provide A2-implicit authority, but MCP does not
carry the original user turn. Until a trusted host binds that instruction to the
exact call, this server requires native confirmation. Do not claim to verify
conversational authority from caller-supplied fields. See
[references/approvals.md](references/approvals.md) for trust boundaries and operator recovery.

## Resources (open)

| URI | What it serves |
|---|---|
| `solar://health` | Storage, gateway and continuity, as the console sees them |
| `solar://tasks` | Tasks in `state.sqlite`, by state, with recurrence |
| `solar://index` | Counts from the views in `state.sqlite` |
| `solar://delegations` | Written A3 mandates: mode and validity |
| `solar://gate` | What this server allowed and refused |

## Tools

`tools/list` exposes exactly these three. A name that is not there is not this
server; the nine names of the previous catalog answer with a non-executing
`tool_renamed` error during the transition in
[mcp-tool-migration](../../docs/mcp-tool-migration.md).

| Tool | Authority | Use |
|---|---|---|
| `solar_search` | A0 | `scope=capabilities` skills; `docs` framework documents; `operations` what can run; `resources` the open resources (`uri` reads one); `tasks` list/filter, or one task with `task_id` and `view` = `detail` (identity, checkpoint, digest, schedule), `instructions` (`section` reads one), `config`, `status`, `result`, `error`, `history`. A recorded checkpoint is evidence, not retry authority |
| `solar_docs` | A0 | Skill instructions and registered references, `core-doc:<name>` framework documents, `operation:<name>` contracts. Outline first, then `section`; `full` only when needed |
| `solar_execute` | per operation | One registered operation with its own closed arguments. Unknown operations, extra keys, free paths, commands or queries are rejected before the gate |

Operations (each is gated on its own name, arguments and authority):

| Operation | Authority | Passes when / does |
|---|---|---|
| `task.create` | A2 | Native confirmation or an exact-call approval. Stores a **draft**. `revises_task_id` copies configuration, schedule, execution restrictions (`origin_channel`), notification destination and resource hooks from another task and leaves it untouched. Cannot queue |
| `task.update` | A2 | Same. Edits a draft or planned task under `expected_row_version`. A planned task returns to draft. A queued task that is only renamed keeps id, place and approval; any other change returns it to draft and withdraws the approval in the same transaction (results of earlier runs and run counters stay). Refused for active (`task_active_immutable`) and finished (`task_not_editable`) tasks |
| `task.schedule` | A2 | Same. Time, ISO weekdays, an explicit IANA zone and recurrence for a draft, planned or queued task (a queued task returns to draft, counters kept). Never queues. Refuses an interval that would skip a run after a clock change |
| `task.approve` | A2 | Same. The only operation that queues: the exact stored task at `expected_row_version`. Refuses an A3 mandate and a revision whose source can still run |
| `task.return_to_draft` | A2 | Same, bound to `expected_row_version`. `queued` → `draft`: the approval is withdrawn (digest kept in the audit), the worker can no longer claim the task, id, body, schedule, counters and history stay. Needs `task.approve` to queue again |
| `task.cancel` | A2 | Same, bound to `expected_row_version`. Cancels a queued task, or records the request for an active one |
| `task.requeue` | A2 | Same, bound to `expected_row_version`. Moves an error task back to the queue and drops its `## Execution Error` section |
| `task.archive` | A2 | Same. Archives keeping the row, body and events. A queued recurrence is cancelled first, in the same step. Refused while active, while another task waits on it, or while subtasks run |
| `telegram.send` | A2 | Same, for one exact text and an explicit `chat_id`. Sending outside the machine is never implicit |
| `action.run` | A3 | The skill and action are registered **and** the mandate registered for that skill is live. A skill registered without a mandate is refused; a caller-supplied mandate is only accepted if it equals the registered one |

Approvals are server-side records: they name one **operation** and one set of
arguments (a `row_version` included), expire, bind the workspace, and are reserved
before the first execution attempt. An approval for one operation never runs another.
Tool arguments cannot mint one. A trusted client confirmation response can; the MCP
client is part of the trust boundary.

Task content is approved as stored: editing, scheduling or revising a task never
activates it, a changed task invalidates any approval that named an earlier
version, and an approved or active task keeps its instructions. To change one,
create a revision and approve that. Every decision and its outcome is written to
the gate audit under one `trace_id`.

Action skills are opt-in, listed in `<runtime>/mcp/action-skills.json`:

```json
{"example-sync": {"actions": ["status"], "mandate": "example-sync-mandate",
                  "command": ["bash", "planets/<planet>/skills/example-sync/scripts/example_sync.sh"]}}
```

**Instruction skills never become operations.** They stay native to the harness; only
registered action verbs pass through here.

## Sending Telegram

`telegram.send` is the route an agent has to Telegram, and the reason the
`solar-telegram` skill is no longer published to any client. The bot token is an
installation secret held by the process
(`<app data>/Solar/secrets/installation.env`, 0600): the server reads it and
hands it to `send_telegram.sh`, which refuses to look it up on its own.

The approval covers the exact text. Change a word and the call is refused with
`approval_scope_mismatch`, because the hash covers the arguments, not the tool
name alone. The chat must be the configured one or listed in
`TELEGRAM_ALLOWED_CHAT_IDS`.

## Clients in front of the gate

Client tool allowlists and native Solar confirmation serve different purposes.
A generic "allow this tool" card does not approve its exact destination and content.
The runtime uses [MCP form elicitation](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation)
when supported. Clients must route that request to the human, never to the model.

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

## Runtime dependencies

Starting the stdio child does not start Solar services. Tools still depend on
Solar's configured workspace, runtime storage and (for sends) installation secrets.
Task operations write only through `solar-state` and refuse when the runtime format is not `sqlite`. The supervised
orchestrator processes queued tasks separately. Console and background services
have their own startup/LaunchAgent lifecycle. A connected MCP child is not evidence
that the queue worker, console or transport is running.
