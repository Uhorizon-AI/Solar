---
review_pass: verificacion
design_frozen: false
last_review: none
---

# Design: identity and authority by channel, for Assistant and Orchestrator (design only, no code)

**Date:** 2026-11-08
**Status:** draft; the three open decisions were taken by the owner on 2026-11-08 (section 16); pass-0 feedback from Claude, Codex and Grok applied on 2026-11-09; pass 0 pending again on this text (launched by the owner)
**Base:** `abafe6e` (main)
**Issues:** #147 (builder authority by verified channel) and the design requirements of #130 (identity and authorization by channel). Platform dependency: #129 (Linux VPS). Related: PR #148 (waiting notice with short id and expiry, closes #146), #81 (closed as not planned).
**Strategy:** this is the design phase of priority 2 ("Orchestrator en VPS"): "first a design with no code for identity, permissions and builder authority; then the Linux platform".

Everything below was read in the code on `abafe6e` and in PR #148. Nothing was run and nothing was sent to Telegram. Statements about the Telegram Bot API are from its documentation and are not tested here.

## 1. Goal and scope

**Goal.** One identity and authority mechanism that serves both modalities, so that Orchestrator on a VPS does not require rebuilding what Assistant uses today:

- **Assistant:** one person (the builder), their channels, authorization of waiting tasks from a phone.
- **Orchestrator:** several people over channels, each with a profile that says what they may request and approve; revocation that blocks pending work.

**What this document designs (all of it):**

1. A registry of people with a profile, of which the builder is the first row (section 3).
2. The channel adapter contract and what "verified sender" means per channel (section 4).
3. Classification before content: an unverified sender never reaches a provider (section 5).
4. The permission shape and the requester recorded on tasks (section 6).
5. Authorization by channel: the one-time challenge bound to the task (section 7) and the decision about n8n (section 8).
6. Revocation in `task_claim`, including A3 mandates and approvals already given (section 9).
7. Privileged changes through a second bound channel (section 10).
8. The three channels (Telegram, email, Google Chat or Teams) as a contract with tests; only Telegram is meant to be built first (section 4.4).

**What it depends on and does not design:** the Linux VPS, service account, systemd and CLI login (#129). Where a control is only real on the VPS, the text says so.

**What stays out:** see section 15.

## 2. One model for both modalities

| | Assistant | Orchestrator |
|---|---|---|
| People in the registry | One: the builder | Several, each with a profile |
| Who writes the registry | The builder, from a terminal | An administrator, from a terminal on the operator account |
| Why the agent cannot write it | Mediated routes and each client's own sandbox deny writes outside the workspace. Not a guarantee: agent and user share one system account | The registry is owned by an operator account, readable but not writable by the service account that runs Solar and the agent. This is the control #130 asks to write as a requirement, and it needs #129 |
| Channels | Those the builder activates | Those each person binds with a one-time code |
| Who may approve a waiting task | The builder, always: tasks carry no permission scope until piece C2, so only the wildcard permission applies (6.3) | Persons whose profile allows it for the task's permission scope |
| Sender identity on Telegram | Via n8n: the sender is claimed, not proven; the second factor authorizes the task (section 8) | Not via n8n: own bot and own webhook, so the sender is proven (section 8) |
| Requester recorded on tasks | Not recorded in phase 1 (piece C is phase 2); the only person is implied | The verified person (6.2) |
| Revocation | Removing the channel or the switch | Same mechanism, per person, checked in `task_claim` |

What does not change between the two: the adapter contract, the one-time challenge, the audit events, the check in `task_claim`. Assistant is the registry with one row and a profile that allows everything the builder may do today.

## 3. Registry of people

### 3.1 Where it lives

```text
<app data>/Solar/identity/people.json      0600 (Assistant), directory 0700
```

Same rule as `installation.env` (`core/skills/solar-paths/scripts/solar_secrets.py`): outside every tree an IDE indexes, never in git, never synced. On a VPS it is owned by the operator account, group-readable by the service account (see section 2). Never inside `sun/` or `planets/`.

Proposed content (no secrets):

```json
{
  "version": 1,
  "people": [
    {"id": "louis", "display": "Louis", "enrolled_at": "…",
     "profile": "builder",
     "channels": [
       {"kind": "telegram", "user_id": "<numeric>", "chat_id": "<private chat id>",
        "bound_at": "…", "enabled": true}
     ],
     "permissions": [{"scope": "*", "may_request": true, "may_approve": true}]}
  ],
  "profiles": {
    "builder": {"admin": true}
  }
}
```

The profile `builder` is the only one Assistant needs. `admin` is the right to change this registry, and it is exercised only from the terminal.

Not in the file: each person's `status` (active or revoked) and the channel-authorization switch mode (`off`, `observe`, `active`; off by default). They live in solar-state and are written by the same terminal command through a state function, in one transaction, because the claim and the authorization read them inside their own transactions (7.1b and 9). The file holds identity and permissions; the database holds what must be decided atomically.

### 3.2 Who writes it

Only an operator command run in a terminal: `solar people enroll | add-channel | grant | revoke | status` (working names; the builder commands of Assistant are the same commands with one person). It is not an MCP operation and not in the operation registry. The server and the gateway read it fresh on each inbound message and each authorization; there is no cached copy.

### 3.3 Why the agent cannot edit it, and where that stops

What holds:

- The clients' sandboxes deny writes outside the workspace for the shell and the edit tools (measured table in `docs/tasks/2026-11-05-native-client-sandbox-133.md`); the file is in the app data folder.
- No MCP operation writes it.
- The gateway rereads it, so a stale copy cannot be poisoned.

What does not hold, and must be said (honesty rule): on the user's computer the agent and the user share one system account and reads are open, so an agent started outside the default sandbox flags, or with write paths added by user settings, could write it. This is the ceiling `solar-scope-and-enforcement.md` already states. The design does not rely on the file being secret, only on it not being writable through mediated routes, and it keeps the real secrets out of what a read can use (section 7.2). On a VPS with a separate service account the file is truly unwritable by the agent; that is the requirement, and it is verified there, not assumed.

### 3.4 Enrollment

Out of band, same steps for the builder and for any person:

1. The administrator runs `solar people enroll <id>` in a terminal. Solar prints a one-time code (random, 10 minutes, stored only as a hash).
2. The person sends that code to the bot from their private chat.
3. The gateway recognizes the code and hands the `user_id` and `chat_id` claimed in the message to the waiting command. Nothing is written yet.
4. Solar sends a second one-time code straight to that `chat_id` through the Bot API, not through n8n, and the terminal asks the administrator to type it. If an intermediary kept the right code and `user_id` but replaced the `chat_id`, the second code goes to the wrong chat, nobody can type it and enrollment fails.
5. Only when it matches does the terminal show the `user_id` and `chat_id` and ask for `y` to write the registry. In a private chat the chat id equals the user id, so proving control of the chat proves both without the person looking up a number; a group chat (negative chat id) is refused.

Steps 4 and 5 are the independent check an intermediary on the inbound path cannot reach. The first code never grants anything by itself.

## 4. Channel adapter contract

### 4.1 The contract

Each channel implements one function, and identity, permissions, approval, revocation and audit are shared and are not reimplemented per channel:

```text
resolve(inbound) -> {status: verified | claimed | unverified, person_id | None, channel_kind, conversation_id, reason}
deliver(person_id, text) -> sent | refused
```

`resolve` never trusts a name: it returns `verified` only if every channel rule in 4.2 holds, including a route that Solar itself authenticates. On the n8n route the best it can return is `claimed` (the sender the intermediary reports): enough to match a reply to an open challenge (section 7), never enough to classify (section 5). Anything else is `unverified` with no `person_id`. `deliver` only writes to an address bound in the registry.

### 4.2 Verified sender per channel

| Channel | Counts as verified | Never counts |
|---|---|---|
| Telegram | The numeric Bot API `from.id`, in a private chat whose `chat.id` equals the bound chat, arriving on a route whose authenticity is proven (section 8) | `@username`, display name, any group chat, a forwarded message |
| Google Chat / Teams | The platform-authenticated user identifier, restricted to the installation's tenant or domain | Display name, any other tenant |
| Email | The From address, only if the message passes DKIM/DMARC alignment (`Authentication-Results`) | An unauthenticated From, a reply-to |

Binding a channel to a person always goes through the one-time code of 3.4. Self-asserted identity never binds or elevates.

**Groups.** Every message from a group chat is rejected. People are told apart only in their private chats. This is narrower than the acceptance wording of #130 ("including in a group") and is recorded as a deliberate deviation: `from.id` inside a shared chat would need a rule that does not raise a person's rights because of the chat they share.

### 4.3 Today's gateway, as read

`run_http_webhook_bridge.py` takes `user_id` from the body (`payload.get("user_id", "n8n-user")` on the n8n path) and filters Telegram by chat only (`telegram_chat_allowed`, `TELEGRAM_ALLOWED_CHAT_IDS`). The console documents that it counts distinct `user_id` values and does not present them as people. That is the gap this section closes; the list of chats stays as a coarse filter and substitutes none of the rules above.

### 4.3b Two inbound routes, not one (found in review)

The bridge has two Telegram-shaped routes, and the document must say which one each piece protects:

- `POST /webhook/n8n`: protected by the shared secret (`check_n8n_secret`, constant-time compare); the sender is whatever n8n writes in the body.
- `POST /webhook/telegram` (exists whenever `TELEGRAM_BOT_TOKEN` is set): `check_n8n_secret` runs only for the n8n channel (`do_POST`), the Telegram branch checks no secret (`grep secret_token` finds nothing), and the chat filter `telegram_chat_allowed` is applied on the n8n path. On this route a forged POST that carries an allowed `chat_id` reaches the router today. Whether the route is reachable depends on whether Solar claimed the webhook (`SOLAR_GATEWAY_CLAIM_TELEGRAM`), which the gateway reference describes as absent or false on this host (not checked in `.env` here); that would make the route inactive in practice, not safe by construction.

Consequences: until piece K, `/webhook/telegram` rejects the whole body before parsing it, whether `SOLAR_GATEWAY_CLAIM_TELEGRAM` is true or false (the flag only decides whether Solar registers the webhook with Telegram; it adds no check on the request). The cost is that the documented rollback path with the claim on is off until K. Piece E in phase 1 therefore works only on `/webhook/n8n`; on the direct route its test is that a forged update never reaches the router. Piece K gives `/webhook/telegram` a verified `secret_token` and makes it the route of the bot that serves people.

### 4.3c Gateway tasks already skip the wait (found in review)

The router creates tasks `queued` from a gateway message (`router.py` around line 679) through `task_create` with `status="queued"` (`solar_state.py:2349-2354`), which records the approval with `_approval_fields` and without `approved_consent: client`, so `needs_run_authorization` is false for them: they never wait for `task.authorize_run` and never need `run_authorized_digest`. This design does not change that and does not claim to gate it. It matters in two places: `requester_person` (6.2) is written in that `task_create` path from the resolved person, and in Orchestrator the classification of section 5 and the `may_request` check of 6.4 decide whether a message may create such a task at all.

### 4.4 Channels to build

The contract and its tests are designed for the three channels. Telegram is built first because it already exists in the gateway. Email and Google Chat or Teams are built when a pilot client requires them (as #130 says); until then they have a contract, tests written against a fake channel, and no code.

## 5. Classify before content

Order on every inbound message, before anything reaches the router or a provider:

1. Resolve the sender (4.1).
2. Unverified sender: fixed reply or none; the body is dropped, not stored, not passed on. On email this is decided from headers before the body is fetched.
3. Verified person with no permissions: treated as an unknown sender (owner decision, section 16; there is no "public content only" mode).
4. Verified person with permissions: the message continues with `person_id` attached, and Solar writes it, not the caller, as the requester (section 6).

The audit records only sender, channel, subject or identifier, and the decision. Never the body, including for blocked attempts.

Limit: step 1 is only as strong as the route. Through n8n the sender is claimed, not proven (section 8), so classification is a control only on a route Solar authenticates itself. Phase 1 therefore does not classify and does not change how the builder converses with Solar through n8n: only the challenge-reply branch of 7.1 is added there.

## 6. Permissions and requester

### 6.1 Permission shape

A permission is `(person, scope, may_approve)`, plus `may_request`. Scopes are opaque identifiers to core; each planet declares its own vocabulary (projects, accounts, initiatives). Approval eligibility is separate from access level and can be bound to a scope, so a project owner approves inside the project without being an administrator.

Task-side: tasks need a permission scope tag, declared by the planet that creates them and recorded in the task (piece C2, phase 2). This is a new field. It must not be confused with the existing `scope` column (the free-text statement of object, scope and effect that the approval form shows).

### 6.2 Requester recorded on the task

Piece C, phase 2. Today tasks carry `origin_channel`, `origin_chat_id`, `origin_request_id` and the others, but no person (`solar_state.py`), and the console's requester column and screen are empty by design. Proposed fields on the task, written only by Solar and never taken from tool arguments:

- `requester_person`: the registered person id, or empty.
- `requester_basis`: `verified_channel` (the adapter resolved the person), `client_owner` (created through MCP on the installation's client permission; the only basis for an MCP-created task in Assistant once the field exists) or `unknown`.

`client_owner` is not a verified person: the authority model already says every MCP caller holds the client's permission and Solar cannot tell an interactive client from a subagent. In Orchestrator an MCP-created task without a verified channel stays `unknown` and an eligible approver must approve it. Historical records are never attributed: tasks created before this field exist stay `unknown`. The console reads these fields and fills its requester column; it stays read-only.

### 6.3 Who may authorize

Authorizing a task is allowed when the approver is a registered, active person with `may_approve` for the task's permission scope. A task without a permission scope (every task in phase 1, until piece C2) can be authorized only by a person whose permissions include the wildcard scope `*`; in phase 1 that is the builder, and enrolling a second person is refused until C2 exists. The approver is recorded with the authorization (`run_authorized_by`, withdrawn with the approval like `run_authorized_digest`).

### 6.4 Where `may_request` applies

Orchestrator only. Before the gateway creates or enqueues a task (the `task_create` path of 4.3c), the permission scope is resolved from trusted context, never from the message text: the intersection of the resolved person's `may_request` scopes and the scope the planet or route declares for the task. An absent, ambiguous or unauthorized scope is refused and recorded. A person who may only approve, or who may request in scope A, cannot enqueue a task of scope B (negative test 20).

## 7. Authorization by channel

### 7.1 Flow

1. A queued task needs `task.authorize_run` and starts waiting. The waiting notice goes out (section 11 describes the notice that PR #148 introduces).
2. If the switch mode is `active` (or `observe`, where nothing is ever authorized) and an eligible approver has an enabled channel, the notice also carries a challenge: a random code, generated at that moment, stored as `sha256(code)` with the task id, the approval digest, the row version, the title, the approver's person id, an expiry and `used_at = null`.
3. The approver replies in the private chat with the code and the short id (for example `ok 7Q2K-91XM a3f9c2e1`; the short id is an identifier, not a secret).
4. On the n8n route (phase 1) the gateway first checks whether the message is a reply to an open challenge. If it is, a dedicated branch handles it alone: it matches the claimed `user_id` and `chat_id` against the channel bound in the registry, calls a state function `task_authorize_run_by_channel`, replies, and the text never reaches the router or a provider. Any other message continues to the router exactly as today. The function is not an MCP operation and is not in the registry. On an authenticated route (piece K) the sender is resolved as `verified` (4.1) before the same call.
5. That function runs in one transaction. It must implement its own checks (7.4); it inherits none from the MCP route. They are: queued, valid content approval, current digest and row version, `approved_consent` equal to `client`, and authorization actually required (not already satisfied); plus: challenge unused and unexpired; digest, row version and title equal to those at issue; the replying person equals the challenge's approver and is eligible (6.3). It re-reads the switch mode in its own transaction and writes `run_authorized_digest` and `run_authorized_by` only in `active`, marks the challenge used and records the audit event.
6. Success and every refusal produce a short reply to the same private chat, with no instructions and no content.

### 7.1b Switch modes

- `off` (default): no challenge is issued and a reply is ignored.
- `observe`: challenges are issued and verified and the outcome is recorded as would-have-authorized, but `run_authorized_digest` is never written (piece I).
- `active`: the function writes the authorization (piece J).

The mode is read at consumption, not only at issue: a code issued before the switch went to `off`, or during `observe`, never writes `run_authorized_digest`. The mode is stored in solar-state (3.1).

### 7.2 Why the code is random

If the code were derived from a secret (for example `HMAC(secret, digest)`), anything that can read the installation store, and reads are open to the agent on the user's computer, could compute it. A random code exists only in the Telegram message and as a hash in the database. The code is 8 characters of Crockford base32 (40 bits) from a cryptographic generator, and five failed attempts on a challenge void it. The short id typed with it is only an identifier.

### 7.3 Binding and narrowness

Bound to digest, row version and title at issue. Any edit changes the digest and voids the challenge; a rename keeps the approval today (`task-approval-contract.md`, "Title is a label") but the notice shows the title, so a rename between notice and reply refuses the reply and sends a new notice with a new code. The function can only write the authorization of an already queued, client-consented task: it cannot approve, create, edit, cancel, queue, send, change capacity or touch an A3 mandate. That describes what the route does; what the authorized task then does is limited by the provider's own permissions, exactly as after `task.authorize_run` through MCP. Expiry is 30 minutes (owner decision, section 16), configurable, never longer than the approval wait (72 hours by default).

### 7.4 What the state function must build itself (found in review)

Reviewed on `abafe6e`: the properties the MCP route has today are not in the state layer, so a state function called from the gateway inherits nothing.

- `task_authorize_run` (`solar_state.py:2564-2583`) only calls `authorization_readiness` and writes `run_authorized_digest`. `authorization_readiness` returns `ready=True` for a task that is queued with a valid approval even when `approved_consent` is not `client` and even when authorization is already satisfied (it only changes the message). The refusal of an unnecessary authorization is `_pre_authorize_run` in `operations.py` (MCP only).
- `refuses_mandate` (`mcp_gate.py:179`, set on `task.approve` and `task.authorize_run`) refuses only when the call carries a `mandate` argument or `authority=A3`. A task has no mandate field, so nothing in state recognizes a "mandate-backed task".
- The MCP gate stack (authority check, `client_consent`, approval record, audit of the decision) does not run on the channel route.

Therefore the channel function must:

1. Refuse, each with its own code, unless the task is `queued` (`task_state_refused`), its content approval is valid, `approved_consent` is `client` (new code, working name `consent_not_client`) and `needs_run_authorization` is true; "already satisfied" is a refusal (`task_authorization_not_required`), never a second write. Refuse also when the switch mode is not `active`.
2. Take no `mandate`, `authority` or approval argument at all. The A3 refusal then holds by construction: the route has no input through which a mandate could be named, and it never creates A3 authority. A run under a mandate is checked where it is today, at execution.
3. Replace the MCP decision record with its own audit rows (issue, use, refusal, expiry; 12.1 "Recorded" and section 13) so that every outcome is traceable, and replace the `client_consent` basis with the registered-person checks of 6.3 and 4.2. The authority level is A2 formal in front of a human, consistent with the authority model. The function sends nothing: the notice and the replies go from the gateway to the chat already bound in the registry, and the External Communication Gate keeps covering `telegram.send` and every other recipient.
4. Authorize only an eligible task. The datum is the state of the approved task itself: it declares an `access_policy` whose every scope is inside the workspace (the same physical-path rule the state already applies to read-only questions) and it declares no `executor` or `local_command`. Undeclared or indeterminate is refused and the person authorizes it in the client instead. This bounds what the channel will authorize; it does not verify what the task does, because the zone is declared, not verified (the limit of `task.create`'s zone report), and a task that sends to third parties through a browser session is outside what Solar can see. The channel does not claim to stop that.
5. Be covered by tests that call the state function directly with each refused case, not only through the gateway.

## 8. n8n: decision by modality

### 8.1 The problem

The gateway trusts n8n: a shared secret proves the call came from n8n, and the sender is taken from the body. Whoever controls n8n can claim to be anyone.

### 8.2 Options

| | Own bot, own webhook | Second factor (code bound to the task) |
|---|---|---|
| Stops n8n forging an approval | Yes: Telegram signs the call with a `secret_token` Solar holds; n8n is out of the path | Yes: n8n forges the sender but cannot know the code, which Solar sent straight to the chat |
| Stops n8n forging a requester or reading content as someone else (classification, section 5) | Yes | **No**: classification still trusts the claimed sender |
| Stops a stolen Telegram account | No | No: the code arrives in the same chat |
| New parts | Second bot token, `setWebhook` with `secret_token`, a public route, coexistence with the n8n bot (one bot has one webhook) | A challenge table and a reply format |
| Size | M | S to M |
| Cost to the person | None after setup | One short code per approval |

`secret_token` is a shared secret that Telegram sends in a request header (`X-Telegram-Bot-Api-Secret-Token`) to the webhook URL Solar registered. It proves the call carries the secret, not where it came from at network level.

Residual risk of the second factor: the notice goes out directly through the Bot API (`notify_if_configured.sh`), so n8n does not see it; the reply returns through n8n, which sees the code when it is used. It cannot use it for another task (one digest, one use) and could at most apply the approval earlier than the person intended.

### 8.3 Recommendation

- **Assistant:** second factor first. It closes the threat that motivated the question (n8n impersonating the builder to authorize), needs no new bot and no public route, and is the smaller piece. Identity alone never authorizes, so the sender being claimed through n8n does not matter for authorization; the reply is accepted only through the challenge-reply branch of 7.1.
- **Orchestrator: own bot and own webhook are required, not optional.** With several people, "unverified content never reaches a provider" and the requester recorded on tasks both depend on the sender being proven, and the second factor does not protect those. n8n leaves the inbound path of the bot that serves people.
- Both together are not redundant: the own bot proves who sent, the code proves that this person chose this task now.

## 9. Revocation in `task_claim`

Revocation uses one mechanism: the check happens where the approval-digest gate already is, inside the claim transaction (`task_claim` and `task_claim_next`, after block, schedule and recurrence, before `queued -> active`, as in `task-approval-contract.md`).

New checks, in the same transaction, each failing closed:

1. **Requester.** If the task has a `requester_person` and that person is `revoked` or disabled, the task does not start. It stays out of the queue and the reason is recorded (`requester_revoked`). Owner decision (section 16): it returns to draft with its approval withdrawn, the same path as `approval_wait_expired`.
2. **Approver.** If `run_authorized_by` names a person who is revoked or no longer eligible for the task's permission scope, the authorization is withdrawn and the task waits again for an eligible approver. The approval of the content stays.
3. **A3 mandates.** A mandate's `owner` must be a registered person (today `owner` is free text in `mandates.py`). Revoking that person suspends their mandates and their pre-authorized recurring sends; the evidence log records the suspension and the reason.
4. **Running work.** A task already active when a person is revoked is handled explicitly: a stop request through the existing cancel path for active tasks, an audit event naming the revocation and the task, and a visible state. Solar does not claim it undoes effects that already happened.
5. **Delivery.** Results and notifications for a revoked person's tasks are not sent to their channels (`deliver` refuses an unbound address). Solar does not forward them to a different recipient.

Ordering. The person's status is written to solar-state in one transaction by the terminal command and read by the claim inside its own transaction, so the database serializes revocation and the `queued -> active` change: either the claim commits first (and the stop request of item 4 applies) or the revocation does and the claim refuses. Reading a file inside the transaction would leave a window between that read and the commit; this removes it. A concurrent test revokes the person after the claim has read the state and before it commits (negative test 21). Inbound messages read the registry and the status fresh on every message. Pending challenges for the revoked person are voided in the same transaction. Revocation never needs the channel being revoked.

## 10. Privileged changes

Granting or revoking `admin` or owner rights, and adding a channel to a person, require confirmation through a second bound channel of the acting administrator:

- Orchestrator: the terminal command issues a one-time code that must be returned on a second enabled channel of the same administrator before the change is written.
- Assistant: one person, one channel in v1, so the second bound channel is the terminal itself; adding a channel needs the one-time code from the first channel as in 3.4. A second channel makes the stricter rule available.

## 11. Relation to PR #148 (priority 1) and the notice

PR #148 changes the waiting notice so it carries a short task id (first 8 characters, longer only if another task shares them), the expiry in local time (or "No expiry"), and "Ask your assistant: review and authorize task <short id>". It adds read-only `task short-id` and `task wait` commands. It adds no buttons and no authority, and keeps "title only, never the instructions, once per wait, the task untouched".

Why it matters here:

1. **It is the carrier.** The challenge of section 7 rides in the same notice. The short id in the reply uses the same `task_short_id`, so what the person sees and what they type match.
2. **Land it first.** Changing the same script twice in parallel invites conflict. #148 is independent of everything in this document and stays valid with the switch off.
3. **Its open risk is ours.** The "Risk" section of the PR description says it is not verified that `solar_search` or `task.authorize_run` accept a prefix; the code on the branch does not state it. On the base `abafe6e` the short-id code does not exist yet, so every statement about it here must be reverified against the PR before piece F. The channel route must resolve the short id itself, refuse an ambiguous one and never guess.
4. **One gap it leaves for Orchestrator.** The notice goes to the single configured chat (`TELEGRAM_CHAT_ID`). With several people it must go to the bound channels of the eligible approvers of that task. That is a change to the notice routing in section 14, piece F2.
5. **Text, when the challenge is on.** The line "Ask your assistant to review and authorize" stays for the client route; the code line is added only when the switch is on and an eligible approver has an enabled channel.

## 12. Proposed text for the documents (draft; the files are not edited here)

### 12.1 `core/docs/authority-model.md`: new section "Consent by channel"

> ### Consent by channel (not built yet)
>
> Status: a design; no code executes any control below. Every statement that follows describes what must hold when it is built, and must not be quoted as a guarantee before then.
>
> A registered person's reply on a verified channel may stand in for the native confirmation of `task.authorize_run`, and for nothing else. Everything below must hold; any failure refuses and leaves the task waiting.
>
> - **Registered people, registered out of band.** People, their profiles and their channels are recorded in a registry that only an administrator writes, from a terminal. No MCP operation, agent or channel message writes it, adds a channel or raises a right. Self-asserted identity never binds or elevates.
> - **Verified sender.** Per channel, the platform-authenticated identifier (numeric user id on Telegram, authenticated identifier within the tenant on Chat or Teams, DKIM/DMARC-aligned From on email), in a private conversation. Names and shared chats never qualify. Where Solar authenticates the route itself, content from an unverified sender never reaches a provider, and a verified person with no permissions is treated as an unknown sender. Through an intermediary the sender is only claimed, and the code, not the claimed identity, authorizes.
> - **Eligible approver.** The person has `may_approve` for the task's permission scope. Approval eligibility is separate from access level.
> - **A second factor the intermediary cannot see.** The reply carries a random one-time code (8 characters; five failures void it) that Solar sent straight to the approver's chat through the Bot API and stores only as a hash. Where the reply returns through an intermediary, that intermediary sees the code when it is used; it can apply that approval earlier, not another.
> - **Exact content.** The code is bound to the approved digest, row version and the title shown. An edit, a rename or a new approval voids it.
> - **Short and single use.** It expires in 30 minutes by default, configurable, never beyond the approval wait, and is consumed on use.
> - **Narrow effect.** The route only writes the authorization of one task already approved by the client and not confined, and only if the task declares access inside the workspace and no local command; otherwise it refuses and the person authorizes in the client. It never queues, approves, edits, sends, or touches capacity or mandates, and it takes no mandate input. What an authorized task does is limited by the provider's own permissions, as with the native confirmation; `telegram.send` and every other recipient stay under the External Communication Gate.
> - **Revocable at claim.** Revocation is serialized with the claim in the state database. A revoked requester's task returns to draft and loses its approval; a revoked approver's authorization is withdrawn and the content approval stays; mandates owned by a revoked person are suspended.
> - **Recorded.** Each issue, use, refusal and expiry is audited with sender, channel, task, digest and decision, never the message body or the instructions.
> - **Off by default.** An installation switch with three modes (off, observe, active), set from a terminal and read again when a code is used, turns it on.
>
> It is a second surface of consent. It does not make the console an approval surface. It does not isolate people from each other: the registry is not editable by the agent only where a service account separate from the operators exists, and the first pilot uses shareable information only.

Also, in "Client consent and risk at execution (MCP)": add "`task.authorize_run` can also be satisfied by consent by channel (below), never by caller prose."

### 12.2 `docs/solar-scope-and-enforcement.md`: row "Approval"

Assistant cell, replacing "In the harness: its own permission prompt or the MCP confirmation":

> In the harness: its own permission prompt or the MCP confirmation. Optionally, for `task.authorize_run` only, the builder's reply on a verified channel with a one-time code, once enabled from a terminal (off by default; not built yet). Never `telegram.send`, third parties or capacity changes.

Orchestrator cell, replacing "To happen in the channel where the request arrived; not built yet":

> In the channel where the request arrived, by an eligible registered person, with a one-time code, on a route Solar itself authenticates; not built yet.

In "Orchestrator requirements (not yet enforced)", add: "Revocation is checked at the claim, so it blocks pending work; a revoked person's A3 mandates are suspended." In "Assistant limits", add: "The builder's channel is a registered source of authority only for `task.authorize_run`, and only with the controls of 'Consent by channel'."

## 13. Threat model by severity and negative tests

| # | Threat | What the design does | Negative test |
|---|---|---|---|
| 1 | The agent's own service account is registered as an approver (self-approval) | Registry written only from a terminal on the operator account; the agent's account is refused as a person id and cannot hold a channel | Enroll with the service account's identity: refused. Challenge answered from a channel not bound to an eligible person: refused |
| 2 | The registry is a file the agent can edit (self-elevation) | Outside the workspace, not writable through mediated routes; on the VPS, owned by the operator account | From a default-launch client, writing the registry fails; no registered operation writes it; the gateway ignores a registry with wrong owner or mode |
| 3 | n8n (or anyone behind the shared secret) forges a sender to authorize | Random code sent directly by Solar, stored hashed | Correct secret, registered `user_id`, no code: refused; wrong code: refused and counted; five failures void the challenge. A valid code authorizes, and that reply never reaches the router; an ordinary message through the same route continues as today |
| 4 | n8n forges a sender to be classified as a known person (Orchestrator) | Own bot and webhook with a verified `secret_token`; n8n out of that path | Forged update without the secret header or with a wrong one: rejected before content. A correct header from another origin is not claimed to be stopped (network level) |
| 5 | The agent derives or reads a valid code | Random code, hash only | Reading the state database and the secrets store does not yield a code that passes |
| 6 | Edit or rename between notice and reply | Challenge bound to digest, row version and title | Edit then reply: refused, voided. Rename then reply: refused, new notice |
| 7 | Identity taken from an unverified email From | Verified only with DKIM/DMARC alignment | Spoofed From without alignment: unknown sender, content not fetched |
| 8 | Wrong person, wrong chat, group, forwarded message | `from.id` and private chat both checked; every group message rejected | Valid code from another `user_id`, or from a group: refused |
| 9 | An unknown or unpermissioned in-organization sender reaches a provider (Orchestrator, authenticated route only) | Classify before content | Message from a known sender with no permissions: no provider call, fixed reply or none |
| 10 | Revocation leaves pending work alive | Checks at the claim for requester, approver and mandates; status in the database; pending challenges voided | Revoke a requester with a queued approved task: it does not start. Revoke an approver: authorization withdrawn. Revoke a mandate owner: mandate suspended, recurring send blocked. Reply with a previously valid code after revoking: refused |
| 11 | Replay or duplicate delivery of the reply | One use; update id de-duplicated | Same reply twice: first authorizes, second refused as consumed |
| 12 | Late reply | Own short expiry inside the wait | Reply after expiry: refused, audited, no write |
| 13 | Channel authorizes something outside its remit (send, third party, capacity, A3) | The function takes no mandate, authority or approval input and builds its own checks (7.4): client-consented, authorization required, queued, valid | State function called directly with a `mandate` or `authority` argument: not accepted. Not queued, not `approved_consent: client`, already authorized, switch not `active`: refused, each with its own code. A queued, client-consented task with undeclared or outside-workspace access, or with a local command: refused and left without `run_authorized_digest` |
| 14 | A blocked attempt stores the message body | Audit stores sender, channel, subject or identifier, and decision | A refused message leaves an audit row with no body text |
| 15 | Cross-project confidentiality inside one planet | Not claimed: MCP filtering is not isolation | Documented; pilot uses shareable information only |
| 16 | Stolen Telegram account or SIM | Not stopped: the code arrives in the same chat. Accepted residual risk | Documented; revoke from the terminal works without that channel |
| 17 | Enrollment raced by n8n | A second code goes straight to the claimed chat; the administrator types it | Intermediary keeps the right code and `user_id` but replaces `chat_id`: the second code goes to the wrong chat, nothing is written. A forged `user_id`: same. A group chat: refused |
| 18 | Switch left on by default, or turned off with codes pending | Off by default, including after upgrade; mode read again at consumption | Fresh install and upgrade: replies authorize nothing. A code issued before switching to `off`, or during `observe`: never writes `run_authorized_digest` |
| 19 | Two authorized people and an unknown sender (Orchestrator, authenticated route) | Adapter resolves each separately; group messages rejected | Acceptance case from #130 in their private chats, narrower than "including in a group" (4.2); a group message from either person: rejected |
| 20 | A person with a permission to approve, or to request in scope A, enqueues a task of scope B | `may_request` resolved from trusted context at task creation (6.4) | Approve-only person and A-only requester: task of B refused and recorded; absent or ambiguous scope refused |
| 21 | Revocation races the claim | Status in the database, serialized by the transaction (9) | Revoke after the claim read the state and before it commits: either the claim wins and the stop request applies, or the claim refuses |

Cross-review must also check what this document cannot prove: that no existing path already lets a gateway message reach `run_authorized_digest`. From the read, none does.

## 14. Pieces, size, closure criteria and order

Sizes are relative estimates (S, M, L), not measurements.

| Piece | Size | Closes when | Depends on |
|---|---|---|---|
| A. This design reviewed; the two text drafts applied to `authority-model.md` and the scope document (docs only) | S | The owner and the cross-review AIs reviewed it; texts merged | none |
| B. People registry, reader and terminal command (enroll, add-channel, grant, revoke, status), switch mode and person status in the database | M | Tests 1, 2, 17, 18 pass; mode and owner checked; no operation can write it; enrolling a second person is refused until C2; a real enrollment with the owner's yes | A |
| C. Requester on tasks, executions and audit (`requester_person`, `requester_basis`), console column filled | M | The console shows the requester with its basis; old records stay `unknown`; no value comes from tool arguments | B |
| C2. Permission scope field on tasks (6.1), declared by the planet that creates the task, distinct from the existing free-text `scope` column | S | A task records its permission scope, the claim and the authorization read it, an absent scope means only a person with the wildcard permission may approve, and test 20 passes | B, C |
| D. Challenge store and `task_authorize_run_by_channel` (no transport), `run_authorized_by`, audit events | M | Tests 3, 5, 6, 11, 12, 13, 14 and 18 pass by calling the state function directly, with the rejections of 7.4 named: `task_authorization_not_required`, task not `queued`, `approved_consent` not `client`, switch not `active`, ineligible task | A, B |
| E. Gateway: adapter contract for Telegram, sender resolution, classify before content, fixed replies, reply parsing | M | Tests 3, 8, 11 and 14 pass through the real HTTP bridge on `/webhook/n8n` with faked Telegram payloads (challenge-reply branch included); on `/webhook/telegram` a forged update never reaches the router; one real round trip with the owner's yes | B, D, and PR #148 merged |
| F. Notice with the code line, for one approver (phase 1) | S | The notice goes to the builder's bound channel and carries the code only with the switch on; the line shows the short id as PR #148 defines it, reverified against that PR | E, PR #148 |
| F2. Notice routing to every eligible approver of the task (phase 2) | S | The notice goes to each eligible approver's bound channel and not to a single configured chat | F, B, permission scope field (piece C2) |
| G. Revocation at the claim: requester, approver, A3 mandate owner, running work, delivery | M | Tests 10 and 21 pass in every variant; the audit names the revocation | B, C, D |
| H. Privileged changes through a second bound channel | S | Granting or revoking admin, or adding a channel, needs the second channel; refused without it | B, E |
| I. Shadow mode: issue and verify challenges, record would-have-authorized, authorize nothing | S | A real week of waits with correct sender and digest and zero authorizations | E, F |
| J. Switch on for the builder (Assistant) | S | The owner turns it on from a terminal after I's evidence; a real authorization with the owner's yes | I |
| K. Own bot, own webhook, `secret_token` verified, n8n out of that path | M | Tests 4, 9 and 19 pass; the bot serves the registered people without n8n | E; required before Orchestrator |
| L. Email adapter (contract tests; implementation when a pilot client requires it) | M | Test 7 passes (DKIM/DMARC cases); headers classified before the body is fetched | E |
| M. Google Chat or Teams adapter (same rule as L) | M | Tenant and identifier cases pass | E |
| N. VPS prerequisites (service account separate from operators, registry owned by the operator account, one installation and workspace) | L | Done under #129; this document only states what it needs | #129 |

### Two phases

The whole design is one document, and delivery is in two phases, so that Orchestrator never rebuilds what Assistant ships.

- **Phase 1, Assistant (one person):** A, B, D, E, F (one approver), then I (shadow) and J (switch on). Protection against n8n is the second factor. Closes when the builder authorizes a real waiting task from the phone, with the owner's yes, and the negative tests of those pieces pass.
- **Phase 2, Orchestrator (several people, VPS):** C, C2, F2, G, H, K, plus N (under #129), then L and M when a pilot client requires them. Only here may Solar claim to control who requests and who approves. Closes with the acceptance of #130: two authorized users and an unknown sender distinguished in their private chats (group messages are rejected, 4.2); revocation blocks pending work.
- **What phase 1 already prepares:** the registry is a list of people with a profile (one row), the challenge is bound to a person and to the task, and the audit events are the same. Phase 2 adds rows, profiles, the requester on tasks, revocation at the claim and the own bot.
- **What phase 1 must not claim:** that the registry is out of the agent's reach (only true with piece N), that the sender is proven through n8n, that classification controls anything on the n8n route, or that it serves several people.

Order for Assistant: A, then B and D, then E and F, then I, then J. Orchestrator adds C, G, H and K before it can claim to control who requests or approves, and N before it can claim the registry is not editable by the agent. L and M follow a pilot client's need.

## 15. What this does not cover

- `telegram.send`, arbitrary external-send approvals and any message to third parties: still the native form and the External Communication Gate.
- Capacity changes, A3 mandates activation, and credential-policy changes through this door.
- Approving or creating tasks from a channel: this authorizes only the run of an already approved task.
- Changing how the builder converses with Solar through n8n in phase 1: ordinary messages continue to the router as today.
- Remote console publication, SSO and corporate IAM, self-registration, several organizations or workspaces, generic task and service controls.
- Isolation between people: MCP filtering is not filesystem or process isolation; the first pilot uses shareable information only.
- The Linux platform itself, systemd, CLI login and instance exclusivity (#129); only what this design needs from it is listed (piece N).
- Real-client behavior: nothing was sent or received to write this; every flow above is untested design.

## 16. Decisions taken by the owner (2026-11-08)

1. An in-organization sender with no permissions is treated as an unknown sender (no "public content only" mode).
2. On revocation of a requester, a queued task goes back to draft with its approval withdrawn.
3. The expiry of the code starts at 30 minutes, configurable, never longer than the approval wait.

These are decisions of the design, not of an implementation: they remain open to the cross-reviews and nothing here authorizes code.
