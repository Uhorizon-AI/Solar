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

-   Manage task lifecycle: `draft` -> `planned` -> `queued` -> `active` -> `completed`.
-   Persist state in `sun/runtime/async-tasks/`.
-   No external database dependency.

## Required MCP

None

## Validation commands

```bash
# Setup runtime directories
bash core/skills/solar-async-tasks/scripts/setup_async_tasks.sh

# Create a task
bash core/skills/solar-async-tasks/scripts/create.sh "My Task" "Do something cool"

# List tasks (QUEUED is ordered by priority: high, normal, low)
bash core/skills/solar-async-tasks/scripts/list.sh

# Worker: one-shot (e.g. for cron)
bash core/skills/solar-async-tasks/scripts/run_worker.sh --once

# Verify skill packaging
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-async-tasks /tmp
```

## Required environment variables

None. (Uses default `sun/runtime/async-tasks` path, overridable via `SOLAR_TASK_ROOT`)

## Workflow

1.  **Draft**: `create.sh` creates a task in `drafts/`.
2.  **Plan**: `plan.sh` prepares the task for execution, moving it to `planned/`.
3.  **Approve**: `approve.sh` moves a planned task to `queued/` with a priority (high, normal, low).
4.  **Start**: `start_next.sh` or `run_worker.sh` picks the highest priority task from `queued/` and moves it to `active/`.
5.  **Complete**: `complete.sh` moves a task from `active/` to `completed/`.

## Automatic execution (run_worker)

- **`run_worker.sh [--once] [--interval SECS]`**: Calls `start_next.sh` to move one queued task to active. Does not execute task content; that is done by the agent or user when they see the task in `active/`.
- **`--once`**: Run one cycle and exit. Useful for cron (e.g. `run_worker.sh --once` every 5 minutes).
- Without `--once`: Loop every `SECS` (default 60). Use Ctrl+C to stop; trap ensures clean exit.
- **Error handling**: If `start_next.sh` fails, the worker logs to stderr and in loop mode continues on the next interval. "No tasks in queue" is normal and not an error.

## Runtime Structure

Default: `sun/runtime/async-tasks/`
-   `drafts/`: Initial capture.
-   `planned/`: Ready for review.
-   `queued/`: Approved and prioritized (001-high, 002-med, 003-low).
-   `active/`: Currently in progress.
-   `completed/`: Finished.
-   `archive/`: Old tasks.

## Output format

Scripts output JSON or simple text depending on flags, optimized for both human reading and machine parsing.
