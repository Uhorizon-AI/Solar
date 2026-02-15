---
name: solar-async-tasks
description: >
  Manage asynchronous tasks within Solar. Create drafts, plan them, approve for execution,
  then run from a priority-ordered queue (manual or automatic). Plan → approve → queue by
  priority → execute when ready (start_next or run_worker).
---

# Solar Async Tasks

## Purpose

Provide a local-first, filesystem-based task management system for Solar.
- **Capture**: Quickly create task drafts.
- **Plan**: Detailed planning phase for tasks.
- **Approve**: Prioritize and queue tasks for execution.
- **Execute**: Track active and completed tasks.

## Scope

-   Manage task lifecycle: `draft` -> `planned` -> `queued` -> `active` -> `completed` -> `archive` (with optional `error` state).
-   **Recurring tasks**: Automatically re-queue tasks after completion with configurable intervals and limits.
-   **Resource cleanup**: MCP resource lifecycle management (locks, cleanup hooks).
-   Persist state in `sun/runtime/async-tasks/`.
-   No external database dependency.

## Required MCP

None

## Dependencies

- **solar-router:** Task execution uses `solar-router` to invoke AI providers. Ensure `solar-router` is configured:
  ```bash
  bash core/skills/solar-router/scripts/onboard_router_env.sh
  bash core/skills/solar-router/scripts/check_providers.sh
  ```

## Validation commands

```bash
# Setup runtime directories
bash core/skills/solar-async-tasks/scripts/setup_async_tasks.sh

# Create a task
bash core/skills/solar-async-tasks/scripts/create.sh "My Task" "Do something cool"

# List tasks (shows recurring 🔁, cleanup 🧹, error ❌)
bash core/skills/solar-async-tasks/scripts/list.sh

# Worker: one-shot (e.g. for cron/launchd)
bash core/skills/solar-async-tasks/scripts/run_worker.sh --once

# Optional: execute active tasks directly
bash core/skills/solar-async-tasks/scripts/execute_active.sh --once

# Optional: set schedule for a task (weekdays 1–7, e.g. 1,2,3,4,5 = Mon–Fri)
bash core/skills/solar-async-tasks/scripts/schedule.sh <task_id> "10:00" "1,2,3,4,5"

# Optional: make task recurring (unlimited runs, 24h interval)
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id>

# Optional: install hook templates for a resource (first time only)
bash core/skills/solar-async-tasks/scripts/install_hooks.sh <resource-name>

# Optional: configure resource cleanup (requires hooks installed)
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh <task_id> <resource-name>

# Check locks (resource availability)
ls -la $SOLAR_TASK_ROOT/.locks/

# Check error state tasks (runtime location)
ls -la $SOLAR_TASK_ROOT/error/

# Verify skill packaging
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-async-tasks /tmp
```

## Required environment variables

None. (Uses default `sun/runtime/async-tasks` path, overridable via `SOLAR_TASK_ROOT`)

## System activation (via solar-system)

For automatic host-level execution, enable this feature through `solar-system`:

```dotenv
# [solar-system] required environment
SOLAR_SYSTEM_FEATURES=async-tasks
```

Then install the single Solar LaunchAgent:

```bash
bash core/skills/solar-system/scripts/install_launchagent_macos.sh
```

## Workflow

1.  **Draft**: `create.sh` creates a task in `drafts/`.
2.  **Plan**: `plan.sh` prepares the task for execution, moving it to `planned/`.
3.  **Approve**: `approve.sh` moves a planned task to `queued/` with a priority (high, normal, low).
4.  **Start + Execute**: `run_worker.sh` picks the highest priority eligible task from `queued/`, moves it to `active/`, then executes one active task.
5.  **Execute (manual/extra)**: `execute_active.sh` processes one `active/` task via `run_router.py` using `SOLAR_ROUTER_PROVIDER_PRIORITY`.
6.  **Complete**: `complete.sh` moves a task from `active/` to `completed/` (or recurring flow).

## Automatic execution (run_worker)

- **`run_worker.sh [--once] [--interval SECS]`**: Calls `start_next.sh` and then `execute_active.sh --once` in the same cycle.
- **`--once`**: Run one cycle and exit. Useful for cron (e.g. `run_worker.sh --once` every 5 minutes).
- Without `--once`: Loop every `SECS` (default 60). Use Ctrl+C to stop; trap ensures clean exit.
- **Error handling**: If `start_next.sh` fails, the worker logs to stderr and in loop mode continues on the next interval. "No tasks in queue" is normal and not an error.

## Task execution (execute_active)

- **`execute_active.sh [--once|--all]`**: Executes task content from `active/` by calling `core/skills/solar-router/scripts/run_router.py`.
- Provider selection uses `SOLAR_ROUTER_PROVIDER_PRIORITY` (fallback order, first success wins).
- Task body is used as semantic instruction source (including agent + skill directions in natural language).
- On success: writes execution log to `$SOLAR_TASK_ROOT/logs/` and runs `complete.sh`.
- On failure across all providers: task is moved to `error/`.

## Scheduling (optional)

Tasks can be scheduled to run only at a specific time and on specific weekdays (e.g. weekdays at 10:00).

- **Frontmatter** (optional): `scheduled_time: "10:00"` (HH:MM or HH:MM:SS), `scheduled_weekdays: "1,2,3,4,5"` (ISO 1=Monday … 7=Sunday). Store only numeric weekdays; display in `list.sh` uses L,M,X,J,V,S,D.
- **Window**: A ±15 minute margin applies so that if the worker runs every 60s and the scheduled time is 10:00, the task stays eligible from 09:45 to 10:15.
- **Eligibility**: `start_next.sh` and `run_worker.sh` only pick a task when it is within its scheduled window (and by priority). Tasks without `scheduled_time` / `scheduled_weekdays` are always eligible.
- **Set schedule**: `schedule.sh <task_id> ["HH:MM"] ["1,2,3,4,5"]` adds or updates the schedule in the task frontmatter. Example: `schedule.sh 20250211-120000 "10:00" "1,2,3,4,5"` for weekdays at 10:00.

## Recurring Tasks

Tasks can be configured to automatically re-queue after completion, enabling periodic execution (e.g., daily job search, weekly reports).

### Configuration

Use `set_recurring.sh` to mark a task as recurring:

```bash
# Unlimited runs, 24h minimum interval between executions
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id>

# Max 10 runs, 24h interval
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id> 10

# Unlimited runs, 1h interval
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id> 0 3600
```

### Frontmatter Fields

- `recurring: true|false` - Whether task should re-queue after completion
- `recurring_max_runs: N` - Maximum runs (0 = unlimited)
- `recurring_run_count: N` - Current run counter (auto-incremented)
- `recurring_last_run: ISO8601` - Timestamp of last execution start
- `recurring_min_interval: seconds` - Minimum time between runs (default: 86400 = 24h)

### Behavior

1. Task completes normally → `complete.sh` checks `recurring: true`
2. If `recurring_run_count < recurring_max_runs` (or unlimited):
   - Increment `recurring_run_count`
   - Update `status: queued`
   - Move back to `queued/`
3. If max runs reached:
   - Update `status: archived`
   - Move to `archive/`

### Race Protection

`recurring_last_run` + `recurring_min_interval` prevent double execution:
- Worker checks if `(now - recurring_last_run) >= recurring_min_interval`
- If not ready, task is skipped and remains in queue
- On start, `recurring_last_run` is updated to current timestamp

### Example: Daily LinkedIn Job Search

```bash
# 1. Create and plan task
bash core/skills/solar-async-tasks/scripts/create.sh \
  "Revisar LinkedIn Jobs" \
  "Buscar nuevos puestos y evaluar según mi perfil"

TASK_ID="<from_output>"
bash core/skills/solar-async-tasks/scripts/plan.sh $TASK_ID

# 2. Schedule: Mon-Fri at 9am
bash core/skills/solar-async-tasks/scripts/schedule.sh $TASK_ID "09:00" "1,2,3,4,5"

# 3. Make recurring (unlimited, 24h interval)
bash core/skills/solar-async-tasks/scripts/set_recurring.sh $TASK_ID

# 4. Approve with normal priority
bash core/skills/solar-async-tasks/scripts/approve.sh $TASK_ID normal

# Task will now run Mon-Fri at 9am indefinitely
```

## Resource Cleanup

Tasks using MCP resources (e.g., `chrome-dev-tools`, databases) can define cleanup requirements to prevent resource leaks.

### Configuration

Use `set_cleanup.sh` to configure cleanup for a task:

```bash
# Single resource, 30s timeout (default)
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh <task_id> chrome-dev-tools

# Multiple resources (CSV)
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh <task_id> chrome-dev-tools,postgres

# Custom timeout
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh <task_id> chrome-dev-tools 60
```

### Frontmatter Fields

- `resources: "res1,res2"` - CSV string of MCP resource names
- `cleanup_required: true|false` - Whether cleanup hooks should run
- `cleanup_timeout: N` - Timeout in seconds for cleanup operations (default: 30)

### Hook System

**Important:** Hooks are **user-defined** and live in your runtime workspace (`$SOLAR_TASK_ROOT/hooks/`), not in the core skill. This allows you to manage hooks for the specific MCPs and resources you have configured.

**Hook types:**
1. `pre_start.sh` - Run before task starts (e.g., acquire resource lock)
2. `post_complete.sh` - Run after task completes (e.g., close connections, release locks)
3. `on_error.sh` - Run if cleanup fails (e.g., force kill processes)

**Hook location:**

Hooks should be placed in your runtime workspace:

```
$SOLAR_TASK_ROOT/
├── hooks/
│   └── <resource-name>/
│       ├── pre_start.sh       (optional)
│       ├── post_complete.sh   (optional)
│       └── on_error.sh        (optional)
└── .locks/
    └── <resource-name>.lock
```

**Installing hooks:**

1. **Quick start** (install templates):
   ```bash
   bash core/skills/solar-async-tasks/scripts/install_hooks.sh <resource-name>
   ```
   This copies templates from `assets/` to `$SOLAR_TASK_ROOT/hooks/<resource-name>/`

2. **Customize** the installed hooks to add your cleanup logic

3. **Use** the resource in tasks via `set_cleanup.sh`

For detailed documentation see `references/hook-system.md`.

### Execution Flow

1. **On task start** (`start_next.sh`):
   - Runs `pre_start.sh` hooks for each resource
   - If hook fails (e.g., resource locked), task is skipped and worker tries next task
   - If successful, task moves to `active/`

2. **On task completion** (`complete.sh`):
   - Runs `post_complete.sh` hooks for each resource
   - If hook fails: runs `on_error.sh` hooks → moves task to `error/`
   - If successful: moves task to `completed/` (or re-queues if recurring)

### Resource Locks (Queue-Wait)

Pre-start hooks can acquire locks to prevent concurrent usage:
- Lock file created at `$SOLAR_TASK_ROOT/.locks/<resource>.lock`
- Contains task ID and timestamp
- If lock exists, task is skipped (worker will retry later)
- No fail-fast: worker continues to next task in queue

**Note:** Lock management is implemented in user-defined hooks, not in the core skill. See hook examples for reference implementations.

### Error State

If cleanup fails, task moves to `error/` state:
- Requires manual intervention (review logs, fix issue)
- Can be moved back to `queued/` or `archive/` manually
- Task frontmatter includes `cleanup_error: true` and `cleanup_error_time`

### Example: Resource Cleanup Task

```bash
# 1. Install hook templates for your resource (first time only)
bash core/skills/solar-async-tasks/scripts/install_hooks.sh my-resource

# 2. Edit hooks to add cleanup logic
# Edit: $SOLAR_TASK_ROOT/hooks/my-resource/post_complete.sh
# Edit: $SOLAR_TASK_ROOT/hooks/my-resource/on_error.sh

# 3. Create task
bash core/skills/solar-async-tasks/scripts/create.sh \
  "Process data" \
  "Execute data processing with resource management"

TASK_ID="<from_output>"
bash core/skills/solar-async-tasks/scripts/plan.sh $TASK_ID

# Configure cleanup for your resource
bash core/skills/solar-async-tasks/scripts/set_cleanup.sh $TASK_ID <your-resource-name>

# Approve
bash core/skills/solar-async-tasks/scripts/approve.sh $TASK_ID high

# Worker will:
# 1. Acquire resource lock (pre_start.sh from your hooks)
# 2. Execute task
# 3. Cleanup and release lock (post_complete.sh from your hooks)
# 4. On failure: emergency cleanup (on_error.sh from your hooks)
```


## When to suggest async (e.g. Telegram)

When the user’s request (e.g. via Telegram) is long-running or complex:

1. **Offer**: Tell the user you can create an async task and notify them when it’s ready or when it’s completed.
2. **Describe**: Briefly say how you’ll create it: task title, one-line objective, and priority (high/normal/low).
3. **Confirm**: Ask for confirmation (e.g. “¿La creo como tarea asíncrona y te aviso cuando esté lista?”).
4. **Create**: If they confirm: run create → plan → approve, then run `add_notify.sh <task_id>` to set `notify_when: completed` in the task frontmatter so the user is notified on completion.

**Task metadata**: Only `notify_when: completed` is stored on the task. The notification channel is **not** stored per task; it is read from the user’s preferences (see below).

**On completion**: If a task has `notify_when: completed`, send an alert using the channel defined in preferences. In v1 the agent can do this when it sees the task in `completed/`. Optionally, `complete.sh` can call `notify_if_configured.sh` so that notifications are sent automatically when a task is completed.

### Notification (Telegram)

- **Default**: `notify_if_configured.sh` (called by `complete.sh`) uses **`.env`** in the repo root: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. If those are set, completing a task with `notify_when: completed` sends "Tarea completada: [title]" via solar-telegram.
- **Override** (optional): `sun/preferences/profile.md` or `notifications.md` can define `telegram_chat_id` to override the chat; otherwise the script uses `TELEGRAM_CHAT_ID` from `.env`.

## Runtime Structure

Default: `sun/runtime/async-tasks/`
-   `drafts/`: Initial capture.
-   `planned/`: Ready for review.
-   `queued/`: Approved and prioritized (high, normal, low).
-   `active/`: Currently in progress.
-   `completed/`: Finished.
-   `error/`: Tasks with cleanup failures (requires manual intervention).
-   `archive/`: Old tasks or completed recurring tasks.

## Output format

Scripts output JSON or simple text depending on flags, optimized for both human reading and machine parsing.
