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

**Where consent lives.** The client (Claude Code, Desktop, Codex, Cursor) holds the user's message and its own
tool permission; that is the consent for the task lifecycle (`task.create`, `update`, `schedule`, `approve`,
`return_to_draft`, `cancel`, `requeue`, `archive`). Solar asks no form for them. What Solar decides is the
**risk of running**, at the claim: a task whose execution is confined by a restricted profile with a verified
implementation for its provider, read-only, is low risk and runs. Any other task (no profile, writes, commands,
a provider without a verified profile) is high risk and waits as `awaiting_approval` until `task.authorize_run`
(native confirmation) authorizes that exact content. Sending outside the machine (`telegram.send`) and capacity
changes (`async_execution.*`) keep their form. Tasks approved before this existed, and by local scripts, keep
running as they did.

1. Prepare the exact operation, arguments and destination. For `telegram.send` include an
   explicit `chat_id` and final text; apply the relevant communication gate first. For an
   existing task, read it first and pass its `row_version`.
2. Task lifecycle operations: call `solar_execute` and nothing else; the client's tool permission is the
   consent. `queue: true` on `task.create` is for work that should run now. If the answer says
   `awaiting_approval`, the task is not confined to a verified read-only profile: tell the user and call
   `task.authorize_run` when they agree. The wait shows `waiting_since` and `waiting_expires_at` in the task list and
   the task; unauthorized, it ends on its own (a one-off task goes back to draft, a recurring one skips that run)
   and the configured chat is told when it begins and when it ends.
3. `task.authorize_run`, `async_execution.*` and `telegram.send`: call `solar_execute` without `approval_id`.
   On clients advertising MCP form elicitation, the runtime presents a compact summary of the exact
   operation for confirmation, creates the approval and executes internally. Do not ask the user to
   create or copy an identifier, and do not ask for conversational confirmation right before that prompt.
4. Never manufacture consent with `approved=true`, an agent-authored note or a shell grant. If the client
   lacks elicitation for step 3, report the integration limitation and use a trusted operator/host
   approval path. Never bypass the gate.
5. Report success only from the execution result. On uncertain failure, check the resulting state before
   requesting another execution.

Any MCP caller holds the client's permission, so subagents and gateways that reach this server are bound by
the same limit: nothing that runs unconfined starts without `task.authorize_run`, and sends and capacity changes
keep their form. Do not claim to verify conversational authority from caller-supplied fields. See
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
| `task.create` | A2 | The client's own tool permission (no form). Stores a **draft**, or queues it at once with `queue: true` (for work that should run now; same checks as `task.approve`). `access_policy` (`mode` read/write, absolute `scopes`, exclusive `resources`) declares what the task touches; a task that declares nothing runs alone (`task.update` takes it too, and changing it withdraws the approval). `revises_task_id` copies configuration, schedule, execution restrictions (`origin_channel`), notification destination and resource hooks from another task and leaves it untouched. Cannot queue without `queue: true`. `ask` (`folder`, `model`) turns the task into a question to the explicit `provider` (prompt in `instructions`): it runs without `task.authorize_run` while the folder and every declared path are the workspace or inside it; any other waits for it. A declared read with `provider` and `instructions` (no schedule, no exclusive resources) is the same question without `ask` |
| `task.update` | A2 | Client permission, no form. Edits a draft or planned task under `expected_row_version`. A planned task returns to draft. A queued task that is only renamed keeps id, place and approval; any other change returns it to draft and withdraws the approval in the same transaction (results of earlier runs and run counters stay). Refused for active (`task_active_immutable`) and finished (`task_not_editable`) tasks |
| `task.schedule` | A2 | Client permission, no form. Time, ISO weekdays, an explicit IANA zone and recurrence for a draft, planned or queued task (a queued task returns to draft, counters kept). Never queues. Refuses an interval that would skip a run after a clock change |
| `task.approve` | A2 | Client permission, no form. Queues: the exact stored task at `expected_row_version`. Refuses an A3 mandate and a revision whose source can still run. A task the executor does not confine waits (`awaiting_approval`) until `task.authorize_run` |
| `task.return_to_draft` | A2 | Client permission, no form, bound to `expected_row_version`. `queued` → `draft`: the approval is withdrawn (digest kept in the audit), the worker can no longer claim the task, id, body, schedule, counters and history stay. Needs `task.approve` to queue again |
| `task.cancel` | A2 | Client permission, no form, bound to `expected_row_version`. Cancels a queued task, or records the request for an active one |
| `task.requeue` | A2 | Client permission, no form, bound to `expected_row_version`. Moves an error task back to the queue and drops its `## Execution Error` section |
| `task.archive` | A2 | Client permission, no form. Archives keeping the row, body and events. A queued recurrence is cancelled first, in the same step. Refused while active, while another task waits on it, or while subtasks run |
| `task.wait` | A0 | Read-only wait: one call sleeps in short slices up to `timeout_seconds` (max 90, default 60) and answers with the final status plus the `result` view; a still-running task returns its status and a `next` hint, never an error, and a queued task still waiting for `task.authorize_run` answers at once with `awaiting_approval`. It never claims, transitions or writes |
| `task.authorize_run` | A2 | Native confirmation of this exact call (the one form left for tasks). Lets a queued task that is not confined to a verified read-only profile run, as stored now; an edit withdraws it. Refuses an A3 mandate |
| `async_execution.propose` | A2 | Same. Writes `<runtime>/async-tasks/config/async-execution.json` with the next revision (capacity 1 to 5, provider limits, exclusive wait, reader profiles; unnamed fields keep the applied values) and returns its digest. A proposal only: nothing changes until it is applied |
| `async_execution.apply` | A2 | Same, for one exact `revision` and `proposal_digest`. Applies that revision to the runtime's policy in one transaction if the file still holds exactly it and it validates; otherwise the applied policy stays. Every claim, manual or worker, reads the applied revision. A provider task never prepares or applies it |
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

For the task lifecycle operations the client's own tool permission is the consent (`client_consent`), so
a generic "allow this tool" card is what the user grants there. For `task.authorize_run`,
`async_execution.*` and `telegram.send` it does not approve the exact destination and content, and the
runtime uses [MCP form elicitation](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation)
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

## Repository review profile

`repository_readonly_v1` explores a private copy of an approved Git commit through
Router with a provider and, optionally, an exact model (omit it to use the one the client CLI has chosen). Native `task.create`/`task.update` prepare
`review` inputs or a bounded `review_batch`; approval and pool admission remain
separate. Claude, Codex, Cursor (`agent`) and Antigravity (`agy`) have guarded constructors;
unknown providers refuse.
The packet profile is unchanged and production profiles remain disabled. See
[repository review](../../docs/repository-readonly-review.md) for scope, host
policy checks, CLI restrictions, limitations and the opt-in inference-free probe.
