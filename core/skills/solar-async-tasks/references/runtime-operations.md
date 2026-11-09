# Reference: Runtime Operations

Operational details for scheduling, recurrence, resource cleanup, notifications, runtime folders, and error recovery in `solar-async-tasks`.

## Scheduling

Tasks can run only at a specific time and on specific weekdays.

`task.schedule` sets the schedule of a draft or planned task. It never queues the task, and it
refuses a task that is already approved: prepare a revision instead (`task.create` with
`revises_task_id`). The agent does not set schedule fields through the shell.

Frontmatter:

```yaml
scheduled_time: "10:00"              # HH:MM or HH:MM:SS
scheduled_weekdays: "1,2,3,4,5"      # ISO 1=Monday ... 7=Sunday
scheduled_timezone: "Europe/Madrid"  # IANA zone; required by task.schedule
```

Behavior:

- For automatic starts, recurring tasks retain a ±15 minute window around `scheduled_time`.
  One-off tasks become eligible at that time through the end of the minute 15 minutes later.
- The clock and weekdays are read in `scheduled_timezone`. An unknown zone never matches.
  Without a zone, host local time applies (tasks created before `scheduled_timezone`).
- A nonexistent local time is skipped for a one-off task. Recurring windows may still include
  valid minutes on either side of a clock change.
- Tasks without schedule fields are always eligible.
- The worker only picks eligible queued tasks.

## Recurring Tasks

Use recurring tasks for periodic execution, such as daily searches or weekly reports.

`task.schedule` also sets `recurring`, `recurring_max_runs` and `recurring_min_interval` on a draft or
planned task. With a schedule, it derives the interval from the shortest gap between occurrences
minus two hours and refuses a longer one: a one-hour-shorter week would otherwise skip a run.
`task.archive` retires a recurrence without deleting its history.

Frontmatter:

```yaml
recurring: true
recurring_max_runs: 0          # 0 = unlimited
recurring_run_count: 0         # auto-incremented
recurring_last_run: ""         # auto-updated
recurring_min_interval: 86400  # seconds
```

Behavior:

1. Task completes successfully.
2. On success the worker checks `recurring: true`.
3. If max runs is not reached, the status goes back to `queued`.
4. If max runs is reached, the status becomes `archived`.

Race protection:

- `recurring_last_run` and `recurring_min_interval` prevent duplicate execution.
- If the interval has not elapsed, the worker skips the task and leaves it queued.
- `recurring_last_run` is written after a claim that won, never before: a claim refused by the approval check (`approval_digest_mismatch`) does not consume the interval. Editing, returning to draft and approving again keep `recurring_run_count` and `recurring_last_run`, and add no run.

## Resource Cleanup

Tasks that use resources such as browser sessions, databases, or MCP servers can declare cleanup requirements.

There is no MCP verb for `resources`, `cleanup_required` or `cleanup_timeout`. The agent stops. It does not set them through the shell.

Frontmatter:

```yaml
resources: "res1,res2"
cleanup_required: true
cleanup_timeout: 30
```

Hooks are user-defined and live in the runtime workspace, not in the core skill:

```text
$SOLAR_TASK_ROOT/
├── hooks/
│   └── <resource-name>/
│       ├── pre_start.sh
│       ├── post_complete.sh
│       └── on_error.sh
└── .locks/
    └── <resource-name>.lock
```

Hook templates live next to the resource, under `hooks/<resource-name>/`.

Execution flow:

1. The worker runs `pre_start.sh` hooks.
2. If a pre-start hook fails, the task is skipped and the worker tries another task.
3. On completion the worker runs `post_complete.sh` hooks.
4. If cleanup fails, `on_error.sh` runs and the status becomes `error`.

See `hook-system.md` for full hook behavior.

## Notifications

When a long-running user request should notify on completion:

1. Offer to create an async task.
2. Confirm title, objective, and priority.
3. Create the task with `task.create` and approve it with `task.approve` (both through `solar_execute`).
4. Set `notify_when` on that task: pass it to `task.create`/`task.update` as a list of `completed`, `delivery` and `failed` (`delivery` is opt-in: a success is announced only when this run's `## Delivery` is non-empty, never `completed` with it; stored as a comma list in the order completed, delivery, failed; asking for `completed` alone is stored as `completed,-failed`). Origin metadata sets `completed,failed` for a gateway parent.

On completion the runtime notifies when `notify_when` lists `completed`, or lists `delivery` and this run's `## Delivery` has text (a run with no block, or an empty one, sends nothing), and the origin chat is allowlisted (`origin_chat_id` or `TELEGRAM_CHAT_ID`). There is no `SOLAR_ASYNC_NOTIFY_TELEGRAM` env flag. Gateway parents get `notify_when` from origin metadata; children created already queued, without that metadata, do not.

Delivery failures are recorded on the task as `notify_status: failed`,
`notify_error`, and `notify_attempted_at`; the notifier returns nonzero. A successful
retry records `notify_status: delivered` and `notify_delivered: true`, so a later
invocation skips delivery. A later run of the notifier retries after the failure is resolved. Automatic retry scheduling is not enabled.

The executor also invokes the notifier after execution failure or timeout; cleanup
failure uses the same path. Only tasks whose `notify_when` lists `failed` are eligible, and so is a bare `completed` (the value older tasks carry, which always reported failures); only the explicit `completed,-failed` that `task.create`/`task.update` store for "completion only" is silent when the task fails, and the notice adds a one-line reason (the machine `error_code` of the current attempt, never the provider's text); the origin allowlist still applies. Failure messages are brief
and omit execution details. The sender is resolved from the installation root;
task data and environment remain in the workspace.

The supervisor bounds its terminal failure notifier at 180 seconds, separately
from the 30-second approval-notice deadline. This leaves the notifier's 150-second
lock wait time to record `notify_lock_timeout` instead of being killed first.
Shutdown still ends the sender and its process group immediately. This does not
guarantee delivery or enable automatic retries: an interrupted sender or an
unavailable transport remains a failed or uncertain delivery. The per-task lock is
an `flock` the kernel releases when its holder ends: a slow sender keeps it, a dead
one frees it, and there is no age-based reclaim. A failure the supervisor declares
carries the run that failed; a task claimed again before the notifier holds its
lock gets no notice for the old failure.
Failure notices share one serial sender, so a stalled terminal notifier can delay
later failure notices for up to this longer deadline; it does not delay the
supervisor's admission/heartbeat loop or the separate approval-notice sender.

### What the notice contains

A gateway parent is asked to end its reply with a `<delivery>` block: plain prose
in the language of the request, written the way a colleague who did the work
would: what was done and what it means, with the evidence worked into the
closing sentence. No labels and no template, because a filled-in form reads like
a machine. Clarity comes before brevity: the block takes the room the work needs,
up to the cap, and the cap is a ceiling rather than a target.

The evidence is something the reader can go to. A link they can open from the
channel is the only kind they can follow from a phone, so it wins whenever one
exists; today none does, and the executor falls back to a verifiable reference:
a relative path or a stable id, named together with the system it lives in, to
be checked later from a machine. A sentence describing where the detail lives is
not evidence either way. Tooling that failed on the executor's side belongs in
the block only when it changed the answer or left part of the work unverified.

The worker copies that block into the task as `## Delivery` (capped at 1200
characters, keeping the last line; a cut sets `delivery_truncated: true`),
and the notifier sends that section as the whole message. It is what the user
reads on a phone, so no fixed prefix and no local path go in front of it.

`## Result` is never sent. It is the provider's own account, unbounded, and
transporting it is not the same as compressing it.

Tasks created with `delivery_expected: true` that finish without the block are
marked `delivery_missing: true`, and their notice says the task finished without
a delivery instead of announcing it as resolved. With `notify_when` `delivery` (alone or with `failed`) that notice is not sent: no block, or an empty one, is silent even when `delivery_expected` is true. The flag is written by the same
call that puts the instruction in the task body: removing the instruction must
remove the flag, or every task would report a missing delivery. A task without
the flag keeps the earlier notice: a brief line plus the result location.

## Runtime Structure

The task is a row. Its status is a column: `draft`, `planned`, `queued`, `active`, `completed`, `error`, `archived`, `cancelled`. Only `queued` is worker input. `draft`, `planned`, `error` and `archived` are never re-run automatically.

```text
<runtime root>/task-logs/          last execution log per task
<runtime root>/async-tasks/hooks/  resource hooks (configuration)
<runtime root>/async-tasks/.locks/ resource lock files
```

## Error Recovery

A task in `error` is terminal until an operator acts.

To run a failed task again:

1. Fix the underlying cause: provider auth, env, binary, prompt, hook, or resource.
2. Requeue the task with `task.requeue`. It moves `error` back to the queue and leaves object, scope and effect as they are.

The task will run on the next eligible worker cycle only while its content approval and execution consent remain valid. Read `readiness` in the task detail/status for the next valid recovery operation.

To edit a failed task, use `task.return_to_draft` directly from `error`; never requeue first merely to withdraw it again. The transaction retains diagnostics, history and counters, withdraws all prior approval/consent, and never exposes the task to a worker. Then edit, approve and (only for high-risk work) accept the native execution form. The ordinary retry via `task.requeue` keeps its existing error-body trimming behavior.

Logs:

- Each task has one log, `<runtime root>/task-logs/<task-id>.log`.
- Logs reflect the last run.
- Logs older than seven days are cleaned by the worker.

A claim clears `notify_delivered` and the other notice records, so a recurring task notifies once per run
and a retry of the same run's notice is still deduplicated. The wait for `task.authorize_run` is announced by
the supervisor, with the reason, for every task whatever its `notify_when` says.

`delivery` is not available on a question (`ask`) or a review: those tasks keep no `## Delivery`, and `task.create`/`task.update` refuse the combination. The `## Delivery` section ends at the next runtime heading (`## Subtask results`, `## Execution Error` or `## Result`), so the delivery may contain other `##` headings; a delivery line that is exactly one of those headings is indented by one space when it is recorded. With `notify_when` `delivery` the notice also requires `delivery_recorded: true`, which the worker sets only when this run's reply carried a non-empty block. The heading is recognised exactly (`## Delivery` and nothing else on the line, so a look-alike in the instructions is neither replaced nor sent), and a delivery is stored with LF line endings. A re-run replaces the delivery only in what the runtime appended after the approved instructions (the boundary `solar-state` recorded), and the notice reads the last `## Delivery`, so a `## Delivery` heading inside the instructions is left whole and is never sent. No notice (`completed` included) sends a delivery the worker did not mark `delivery_recorded`; without the mark it falls back to the brief line, or to "finished without a delivery" when one was expected.
