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

## Native form correlation

Solar forwards only a string or integer `params._meta.progressToken` from the
originating tool call into the pending `elicitation/create` request's `_meta`.
Booleans and other types are ignored; calls without a valid token retain the
existing form request. No other metadata is copied, and deferred calls retain
their own token rather than inheriting one from a previous call.

This is routing compatibility, not consent: the token never replaces the
server-generated elicitation ID, explicit `accept` with `approve: true`, scoped
approval, expiry, cancellation or single-use checks. Tool arguments cannot set it.
The MCP specification defines progress tokens for optional progress reporting;
using the originating token to route a form is a host compatibility requirement,
not a universal elicitation requirement.

An isolated desktop probe on Antigravity 2.24.0 advertised form support but
immediately returned `cancel` without a visible form when the token was omitted.
Forwarding the originating token displayed the native form and returned explicit
acceptance. Codex and Cursor also completed isolated native-form probes without
this correlation requirement. These probes do not establish a full Solar task
execution or validate all cancellation paths in those applications. Claude's
MCP form path remains unverified in this round.

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
and requeue are collapsed to one line, escapes included, and cut at 400 displayed
characters, followed by the original length; edit diffs list changed lines (removals and additions share the
quota) with the window starting at the first difference. `telegram.send` text is
never truncated or reflowed. If a renderer fails, a plain fallback lists the
operation name and its readable fields, without identifiers or row versions. The approval still binds the full
arguments, workspace, row version, expiry and single use.

Limits: Solar controls the text, not the client's modal size, scrolling or
buttons; the form is the one `approve` checkbox the protocol defines. Client
rendering of multi-line text is unverified here.

## Connection diagnostics and native question tools

The initialize result includes `_meta["solar/confirmation"]`. Each
`solar_execute` text payload also includes `confirmation`.

`confirmation` is reserved for server-generated diagnostics at the outer payload
level and replaces any same-named outer field. Handler results remain nested under
`result`, including any field they name `confirmation`. Unsupported content shapes
or text that is not a JSON object pass through unchanged, without diagnostics;
diagnostic enrichment must never turn a completed operation into a transport error.

Diagnostic fields:

- `client_form_advertised`: whether this connection declared legacy empty
  elicitation support or an object-valued `elicitation.form` capability.
- `transport`: `mcp-form` or `unavailable`; this is not a statement about all
  features of a product or every installed version.
- `attempted`: whether Solar actually requested confirmation for this call.
- `outcome`: `not_requested`, `accepted`, or `not_accepted` in returned tool
  results. `not_accepted` includes decline, malformed reply, disconnect and
  timeout; it does not guess which UI the client displayed. A cancelled
  originating request still produces no tool response.

An `approval_required` refusal on a connection without form support also gives
`reason=client_form_not_advertised` and recovery guidance. Do not retry unchanged
or ask an agent to manufacture approval. This diagnoses negotiation separately
from workspace resolution, operation validation, and visible client UI behavior.

Antigravity's native `ask_question` panel is separate from MCP elicitation.
A working question tool does not prove that a pending MCP form is routed correctly;
see [Native form correlation](#native-form-correlation) for the isolated desktop
probe and the originating progress token required by that installed client.

The [official hook contract](https://antigravity.google/docs/hooks#posttooluse)
documents `toolCall`, `stepIdx` and `error` for command-based `PostToolUse` hooks,
but not a structured question response. The separate Python SDK exposes
[`OnInteractionHook`](https://github.com/google-antigravity/antigravity-sdk-python/blob/main/google/antigravity/hooks/hooks.py)
and `QuestionHookResult`; an SDK callback is not evidence that the desktop app
loads that Python integration. Do not scrape a transcript or trust model-written
answers to bridge the two.

A future native host adapter must receive the actual UI result outside model
tool arguments, bind it to Solar's generated request, exact operation/arguments,
workspace and expiry, and enforce cancellation and single use before execution.
That adapter needs a real host integration and acceptance/decline/cancel/timeout
tests in the target client. Diagnostics and routing correlation do not install
that adapter or a macOS dialog fallback. No hook or client configuration is
installed automatically.

### All clients use their own native interaction surface

The integration target is vendor-neutral: the host renders its own supported
question/consent UI and Solar retains one approval contract. Do not add a separate
OS dialog for one client or make an agent forward its own account of an answer.

| Client | Native interaction evidence | Remaining verification |
|---|---|---|
| Codex | MCP form confirmation observed in the repository pilot. Native input tools are a separate surface. | Verify any proposed adapter against host permission rules; do not repurpose a clarification-only tool for permissions. |
| Claude | `AskUserQuestion` and SDK `canUseTool` are documented native interaction hooks. | A real callback binding to Solar and client UI lifecycle tests remain unverified here. |
| Cursor | Reported exact-call MCP confirmation created only a draft in the client test. | Verify any different question-tool adapter separately; do not infer it from MCP form success. |
| Antigravity | Isolated MCP form acceptance observed on desktop 2.24.0 when the originating progress token was forwarded. | Verify the complete Solar operation and remaining UI lifecycle outcomes. |

Tool names and availability must come from each active host, not from the review
provider name. In particular, Codex's `request_user_input` is subject to host
restrictions and must not be used as a permission workaround. See the
[official Codex host template](https://github.com/openai/codex/blob/main/codex-rs/collaboration-mode-templates/templates/default.md)
and [Claude SDK user-input contract](https://platform.claude.com/docs/en/agent-sdk/user-input).
An SDK feature is not automatically exposed by its desktop app. All four clients
must meet the same exact-scope, expiry, single-use and cancellation checks before
any new native question adapter can be declared verified.

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
