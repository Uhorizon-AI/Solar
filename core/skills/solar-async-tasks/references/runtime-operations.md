# Reference: Runtime Operations

Operational details for scheduling, recurrence, resource cleanup, notifications, runtime folders, and error recovery in `solar-async-tasks`.

## Scheduling

Tasks can run only at a specific time and on specific weekdays.

There is no MCP verb for `scheduled_time` or `scheduled_weekdays`. The agent stops. It does not set them through the shell.

Frontmatter:

```yaml
scheduled_time: "10:00"              # HH:MM or HH:MM:SS
scheduled_weekdays: "1,2,3,4,5"      # ISO 1=Monday ... 7=Sunday
```

Behavior:

- A +/- 15 minute window applies around `scheduled_time`.
- Tasks without schedule fields are always eligible.
- The worker only picks eligible queued tasks.

## Recurring Tasks

Use recurring tasks for periodic execution, such as daily searches or weekly reports.

There is no MCP verb for `recurring` or its interval fields. The agent stops. It does not set them through the shell.

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
3. If max runs is not reached, the task is moved back to `queued/`.
4. If max runs is reached, the task is moved to `archive/`.

Race protection:

- `recurring_last_run` and `recurring_min_interval` prevent duplicate execution.
- If the interval has not elapsed, the worker skips the task and leaves it queued.

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
4. If cleanup fails, `on_error.sh` runs and the task moves to `error/`.

See `hook-system.md` for full hook behavior.

## Notifications

When a long-running user request should notify on completion:

1. Offer to create an async task.
2. Confirm title, objective, and priority.
3. Create the task with `solar_task_create` and approve it with `solar_task_approve`.
4. Set `notify_when: completed` on that task. Origin metadata does this for a gateway parent.

On completion the runtime notifies when `notify_when: completed` is set and the origin chat is allowlisted (`origin_chat_id` or `TELEGRAM_CHAT_ID`). There is no `SOLAR_ASYNC_NOTIFY_TELEGRAM` env flag. Gateway parents get `notify_when` from origin metadata; children created already queued, without that metadata, do not.

Delivery failures are recorded on the task as `notify_status: failed`,
`notify_error`, and `notify_attempted_at`; the notifier returns nonzero. A successful
retry records `notify_status: delivered` and `notify_delivered: true`, so a later
invocation skips delivery. A later run of the notifier retries after the failure is resolved. Automatic retry scheduling is not enabled.

The executor also invokes the notifier after execution failure or timeout; cleanup
failure uses the same path. Only tasks already carrying `notify_when: completed`
are eligible, and the origin allowlist still applies. Failure messages are brief
and omit execution details. The sender is resolved from the installation root;
task data and environment remain in the workspace.

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
a delivery instead of announcing it as resolved. The flag is written by the same
call that puts the instruction in the task body: removing the instruction must
remove the flag, or every task would report a missing delivery. A task without
the flag keeps the earlier notice: a brief line plus the result location.

## Runtime Structure

Default task root: `<runtime root>/async-tasks/`

```text
drafts/     captured, not planned or approved
planned/    ready for review, not executable
queued/     approved and eligible for worker selection
active/     currently being executed
completed/  finished successfully
error/      failed execution or cleanup
archive/    historical or max-run recurring tasks
logs/       last execution log per task
hooks/      user-defined resource hooks
.locks/     resource lock files
```

Only `queued/` is worker input. `drafts/`, `planned/`, `error/`, and `archive/` are never re-run automatically.

## Error Recovery

Tasks in `error/` are terminal until an operator acts.

To run a failed task again:

1. Fix the underlying cause: provider auth, env, binary, prompt, hook, or resource.
2. Requeue the task with `solar_task_requeue`. It moves `error` back to the queue and leaves object, scope and effect as they are.

The task will run on the next eligible worker cycle.

Logs:

- Each task has one log with the same base filename and `.log` extension.
- Logs reflect the last run.
- Logs older than seven days are cleaned by the worker.
