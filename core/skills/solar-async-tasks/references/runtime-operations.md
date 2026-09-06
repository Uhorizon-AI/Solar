# Reference: Runtime Operations

Operational details for scheduling, recurrence, resource cleanup, notifications, runtime folders, and error recovery in `solar-async-tasks`.

## Scheduling

Tasks can run only at a specific time and on specific weekdays.

Frontmatter:

```yaml
scheduled_time: "10:00"              # HH:MM or HH:MM:SS
scheduled_weekdays: "1,2,3,4,5"      # ISO 1=Monday ... 7=Sunday
```

Behavior:

- A +/- 15 minute window applies around `scheduled_time`.
- Tasks without schedule fields are always eligible.
- `start_next.sh` and `run_worker.sh` only pick eligible queued tasks.

Command:

```bash
bash core/skills/solar-async-tasks/scripts/schedule.sh <task_id> "10:00" "1,2,3,4,5"
```

## Recurring Tasks

Use recurring tasks for periodic execution, such as daily searches or weekly reports.

Commands:

```bash
# Unlimited runs, 24h interval
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id>

# Max 10 runs, 24h interval
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id> 10

# Unlimited runs, 1h interval
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id> 0 3600
```

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
2. `complete.sh` checks `recurring: true`.
3. If max runs is not reached, the task is moved back to `queued/`.
4. If max runs is reached, the task is moved to `archive/`.

Race protection:

- `recurring_last_run` and `recurring_min_interval` prevent duplicate execution.
- If the interval has not elapsed, the worker skips the task and leaves it queued.

## Resource Cleanup

Tasks that use resources such as browser sessions, databases, or MCP servers can declare cleanup requirements.

Command:

```bash
# Single resource, default 30s timeout
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh <task_id> chrome-dev-tools

# Multiple resources
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh <task_id> chrome-dev-tools,postgres

# Custom timeout
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh <task_id> chrome-dev-tools 60
```

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

Install hook templates:

```bash
bash core/skills/solar-async-tasks/scripts/install_hooks.sh <resource-name>
```

Execution flow:

1. `start_next.sh` runs `pre_start.sh` hooks.
2. If a pre-start hook fails, the task is skipped and the worker tries another task.
3. `complete.sh` runs `post_complete.sh` hooks.
4. If cleanup fails, `on_error.sh` runs and the task moves to `error/`.

See `hook-system.md` for full hook behavior.

## Notifications

When a long-running user request should notify on completion:

1. Offer to create an async task.
2. Confirm title, objective, and priority.
3. Create, plan, and approve the task.
4. Run:

```bash
bash core/skills/solar-async-tasks/scripts/add_notify.sh <task_id>
```

This sets `notify_when: completed`.

`complete.sh` calls `notify_if_configured.sh`. Send happens only when `notify_when: completed` is set and the origin chat is allowlisted (`origin_chat_id` or `TELEGRAM_CHAT_ID`). There is no `SOLAR_ASYNC_NOTIFY_TELEGRAM` env flag. Gateway parents get `notify_when` from `create.sh --metadata`; children created with bare `--queued` do not.

Delivery failures are recorded on the task as `notify_status: failed`,
`notify_error`, and `notify_attempted_at`; the notifier returns nonzero. A successful
retry records `notify_status: delivered` and `notify_delivered: true`, so a later
invocation skips delivery. Retry explicitly with
`bash core/skills/solar-async-tasks/scripts/notify_if_configured.sh <task-file>`
after resolving the failure. Automatic retry scheduling is not enabled.

The executor also invokes the notifier after execution failure or timeout; cleanup
failure uses the same path. Only tasks already carrying `notify_when: completed`
are eligible, and the origin allowlist still applies. Failure messages are brief
and omit execution details. The sender is resolved from the installation root;
task data and environment remain in the workspace.

## Runtime Structure

Default task root: `sun/runtime/async-tasks/`

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
2. Requeue the task:

```bash
bash core/skills/solar-async-tasks/scripts/requeue_from_error.sh <task_id>
```

The task will run on the next eligible worker cycle.

Logs:

- Each task has one log with the same base filename and `.log` extension.
- Logs reflect the last run.
- Logs older than seven days are cleaned by the worker.
