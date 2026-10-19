# Task approval contract

What a queued task was approved with, and what the worker checks before it claims one.

## What is approved

`task.approve` and `task.create` with `queue: true` record, in the task's frontmatter (a task created queued by a local script with `task_create(status="queued")` records the first four only):

- `approved_digest`: `v2:` + sha256 of the material fields and the definition.
- `approved_definition`: the definition as approved (the snapshot).
- `approved_at`, `approved_row_version`.
- `approved_consent: "client"` when the queue entry was made through MCP on the client's own tool permission (no form), and `run_authorized_digest` once `task.authorize_run` authorized this exact content. Both are withdrawn with the approval. An approval without `approved_consent` (made before it existed, or by a local script) needs neither.

Material fields: `solar_state.MATERIAL_KEYS`, including `executor`, `local_command` and
`local_timeout` (a different command is a different task). Not material: run counters,
`recurring_last_run`, claims, notification status.

Five keys cover the concurrency contract: `access_policy`, `subtask_policy`, `execution_profile`,
`review_input_digest`, `review_input_manifest`. They are part of the digest only when the task
declares them, so a task without them keeps its `v2:` digest and its approval; the digest version
did not change and nothing needs re-approving. The two policies are validated JSON and are hashed
in canonical form; an invalid one refuses the approval. See `core/docs/execution-reservations.md`.

**Definition** = the body without a first line `# {title}` that equals the stored title, with
leading blank lines and trailing whitespace removed. Renaming rewrites the title and that
heading together, so it does not change the digest.

## What the claim does

`task_claim` and `task_claim_next` compare the current digest with `approved_digest` inside the
claim transaction, after block, schedule and recurrence, before `queued -> active`:

- With a snapshot, the body must be the snapshot followed by nothing, or by sections the runtime
  wrote (`## Delivery`, `## Subtask results`, `## Execution Error`, `## Result`). From the first
  such heading on, everything is generated content, headings of its own included.
- Without a snapshot, `definition_body()` removes those sections, each up to the next `## `.
- No digest (`absent`), a digest without the `v2:` prefix (`legacy`) or a different one
  (`mismatch`): the task stays `queued`, the next candidate is tried and
  `approval_digest_mismatch` is written to `audit` (once per task, reason and row version), to the
  log and to the console. Nothing is converted: approve it again with `task.approve`.
  `python3 core/skills/solar-state/scripts/solar_state.py task list-unapproved` lists them.

After the digest gate, the claim applies the risk gate (`needs_run_authorization`): a task with
`approved_consent: client` whose execution is not confined (`run_risk` high: no restricted profile with a
verified implementation for its provider, or not read-only) stays `queued` with the reason
`awaiting_approval` until `run_authorized_digest` equals `approved_digest`. A confined task runs at once.
A recurring task keeps its authorization for every repeat, and `task.requeue` (error to queued) keeps it too, while the digest does not change.

### The wait is visible, bounded and announced

A wait is one approval (its digest and the row version it was made at, so approving the same content again starts a new wait) at one occurrence (a recurring task's `recurring_last_run`).

- **Visible.** `task list` in `solar_search` (`awaiting_approval`, `waiting_since`, `waiting_expires_at`), the task
  detail and status views, and the console's waiting list (reason, `since`, `expires_at`).
- **Recorded once.** The first claim that finds the wait writes `awaiting_approval` to `audit` (task, digest,
  occurrence, risk; never the instructions). Polling adds nothing. Before that record exists, `since` is `approved_at` (the wait began at the approval, and the first claim that finds it records that same start, so a task nobody claimed for longer than the limit ends at that first claim). A recurring task's later occurrence has no start until the claim that finds it, so the views show no dates before.
- **Bounded.** `SOLAR_APPROVAL_WAIT_HOURS` (default 72; `0` or less turns it off; an unreadable value keeps the default; set it in the environment of the supervisor, the MCP server and the console alike, because the supervisor applies the limit and the others only show it)
  is how long a wait may last. Past it, the claim ends the wait and writes `approval_wait_expired`:
  a one-off task goes back to draft (approval withdrawn, `task_approval_withdrawn` with reason
  `approval_wait_expired`); a recurring task skips only that occurrence (`recurring_last_run` is stamped, approval and
  schedule are kept, nothing is owed later, and the next occurrence starts a wait of its own). Reading the queue never ends a wait.
- **Announced once.** The async supervisor tells the configured chat, through `notify_if_configured.sh`
  (`--waiting`, `--expired-draft`, `--expired-skipped`), when a wait begins and when it ends: title only, never the
  instructions, never the chat a task names, and the task is not touched. The sending runs on its own thread of the supervisor (a slow sender never delays a claim, the heartbeat or a drain); a chat that is not configured or not allowed is recorded as not delivered (`reason: not_configured`), not as sent. A notice is taken in `audit`
  (`approval_notice`) before it is sent, so a failure is recorded (`approval_notice_result`) and not retried; a wait
  that is already over (authorized, edited, cancelled) is marked and not announced, and so is an expiry that is no longer
  true (the task was approved or authorized again since). When the supervisor stops, a notice still being sent is ended
  with its process group and its thread is collected before the supervisor leaves.
  A stop that arrives before a notice's send began, whether before it was taken or between taking it and starting the
  sender, leaves the notice for the next supervisor (`approval_notice_released`): announcing late is better than not
  announcing. A send that was already running when the supervisor stopped is ended and recorded as not delivered
  (`reason: supervisor_stopping`); it is not retried, because it may have reached the chat. Without a configured and allowed
  chat nothing is sent. At most three notices go out per run of that thread, never while the supervisor drains, and a
  sender that hangs is ended after 30 seconds with its whole process group.
- **Upgrade.** The wait counts from the approval, so a task that was already waiting for longer than the limit when this version is installed ends at its first claim, with one notice each.
- **Limit.** A recurring task nobody ever authorizes starts a new wait, and sends a new notice, at each occurrence
  (about every `recurring_min_interval`); archive or cancel it to stop them. After a skipped occurrence the views show
  no dates until the next claim finds the new wait. Because the wait counts from the approval, a task out of its schedule window, blocked by a dependency or inside its recurring interval can already be past its limit when it first becomes claimable, and a task with a schedule window only ends on the first claim pass inside the window after the limit. Starting a task by name past its limit ends the wait the same way
  (`approval_wait_expired`).

## Decisions and limits

- **Title is a label.** Renaming keeps the approval. The title still reaches the provider
  (`Task Title:` in the prompt, and the heading of the body), so a rename can change what the
  provider reads. The rename is a task operation on the client's own permission (no form) and keeps
  `run_authorized_digest` along with the approval. If a stricter rule is wanted, put `title` back in
  `MATERIAL_KEYS`; renames then return the task to draft.
- **Created queued = approved by the creator.** `task_create(status="queued")` stamps the approval
  (explicit queue scripts). Derived children require transactional policy/input validation, their own snapshots and recorded provenance; see `restricted-review-profile.md`. `task_import` does not.
- **Runtime sections.** Text placed under a runtime heading after the first result is not
  protected. `task.update` refuses new instructions that reuse those section names while results
  are recorded, and treats them as an instruction change otherwise.
- **Two snapshots, on purpose.** `approved_definition` belongs to the approval: the digest binds it,
  the claim compares it, and a withdrawn approval removes it. `definition_snapshot` only records
  where the results begin; it is not an approval and survives a withdrawal.
- **Where the results begin.** `definition_snapshot` records the definition the body starts with. It is
  kept when an approval is withdrawn, so results (with headings of their own) stay apart from the
  instructions through any number of edits and approvals. `approved_definition`, bound by the
  digest, is what the claim compares.
- **Edits.** A queued task keeps its approval only when the digest is unchanged (a rename) and the approval is valid; a queued task whose approval is absent, legacy or mismatching goes to draft on any edit. Any
  other edit returns it to draft in the same transaction and withdraws `approved_*`
  (`task_approval_withdrawn` in `audit`). Counters and `recurring_last_run` are kept.
