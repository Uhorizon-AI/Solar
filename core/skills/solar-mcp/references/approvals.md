# Approval transport and recovery

## Trust boundary

The model proposes a tool call. The MCP server requests confirmation through
`elicitation/create` only if the client advertised form elicitation. The client
must present the request to the human. Only an `accept` response to that pending
server-generated request ID, with `content.approve` exactly `true`, grants consent.
Decline, cancel, disconnect, timeout, errors and unrelated responses do not grant.
While awaiting confirmation, ping requests are answered immediately and other
requests/notifications are queued for processing afterwards. Cancellation of
the originating request suppresses its response and prevents execution; expiry
also prevents execution. Unknown tool schema types are rejected, not coerced.
The server generates and consumes the approval internally; the user never handles
an ID. Reads and valid A3 mandates retain their existing paths.

The server trusts the MCP client to report human input honestly. This does not
protect against a malicious client or a process with the user's filesystem access.
It also cannot infer earlier conversational consent: no trusted original-turn
binding exists in this transport yet. A future host adapter must provide verified,
exact-scope authority before suppressing the local confirmation. Never treat an
agent-provided transcript, note or `approved` flag as that adapter.

Approvals bind the operation name, exact arguments (a task's `expected_row_version` included) and resolved workspace, expire, and are
reserved under a process-shared lock before side effects. A failed execution may
already have caused effects: it consumes the approval too. Inspect state before
retrying. Legacy approvals without the workspace-bound hash, and approvals that name a previous tool, must be reapproved.
The operator CLI grants only registered A2 operations with valid arguments; anything else exits with status 2.
Telegram confirmation requires an explicit destination (`chat_id` is required by the schema), so changing the default
chat cannot redirect a confirmed call.

## Confirmation text

`approval_text.py` writes the prompt from the validated arguments and the task as
stored at that moment; the schemas are closed, so no agent-supplied summary exists
to substitute for it. English unless `language` in `.solar/settings.json` is
Spanish. It shows action, object, concrete changes (edit: before → after; schedule:
days, time, zone, recurrence limits; send: recipient and the full text) and the
effect as implemented (approve authorizes execution; cancel of a queued task is
immediate, of an active one only a stop request). Identifiers, hashes, row versions,
JSON and empty fields stay out. Approving or requeuing a task also shows its declared
object, scope and effect and its recurrence limits. Characters that hide or reorder
text are shown escaped (`\u202e`, `\x07`). A stale or missing task is flagged in the
prompt, and the call is still refused at execution. Instructions in create, approve
and requeue are collapsed to one line and cut at 400 characters, followed by the
original length; edit diffs list changed lines (removals and additions share the
quota) with the window starting at the first difference. `telegram.send` text is
never truncated or reflowed. If a renderer fails, a plain fallback lists the
operation name and its readable fields, without identifiers or row versions. The approval still binds the full
arguments, workspace, row version, expiry and single use.

Limits: Solar controls the text, not the client's modal size, scrolling or
buttons; the form is the one `approve` checkbox the protocol defines. Client
rendering of multi-line text is unverified here.

## Operator recovery (not an agent self-approval route)

The trusted operator may still manage out-of-band approvals:

```bash
python3 core/skills/solar-mcp/scripts/mcp_approve.py grant task.create --args '{"title":"Review report","instructions":"..."}'
python3 core/skills/solar-mcp/scripts/mcp_approve.py list
python3 core/skills/solar-mcp/scripts/mcp_approve.py revoke APPROVAL_ID
```

Use the same `SOLAR_WORKSPACE` as the server. This CLI is an administrative escape
hatch under the user's OS authority, not proof of conversational consent. Agents
must not run `grant` merely because a tool returned `approval_required`. An
unsupported client needs a trusted operator or a host integration; report that
limitation instead of asking the user to copy identifiers as the normal workflow.

## Cancellation behavior

Cancellation of the originating request or timeout sends `notifications/cancelled`
for the pending server-generated elicitation ID. Cancelling that elicitation
itself denies approval immediately. Cancellations of other pending requests are
remembered before deferred dispatch; those requests produce neither a form nor
a response. Late responses cannot authorize a later call. Request IDs retain their
JSON types; numeric and string IDs are not silently conflated.

## Client UI verification status (2026-09-14)

Installed versions observed: Claude Code 2.1.236; Cursor 3.20.21.
Protocol regression tests pass, including decline, cancellation, timeout, late
acceptance and cancelled deferred calls. Real UI acceptance/rejection/dismissal/
120-second expiry remains unverified in both clients. An attempt to inspect Cursor
was blocked by Computer Use authorization ("Computer Use was not approved to use
Cursor"). No client settings were changed and no live approvals were granted.

When UI access is available, use an isolated workspace/runtime and verify all four
outcomes in each client: only acceptance may create an executed action and consumed
approval; cancel/dismiss/timeout must leave no action and close the pending form.
Record results per client version, including whether form elicitation is advertised.
