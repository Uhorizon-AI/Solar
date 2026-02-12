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

# Optional: set schedule for a task (weekdays 1–7, e.g. 1,2,3,4,5 = Mon–Fri)
# bash core/skills/solar-async-tasks/scripts/schedule.sh <task_id> "10:00" "1,2,3,4,5"

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

## Scheduling (optional)

Tasks can be scheduled to run only at a specific time and on specific weekdays (e.g. weekdays at 10:00).

- **Frontmatter** (optional): `scheduled_time: "10:00"` (HH:MM or HH:MM:SS), `scheduled_weekdays: "1,2,3,4,5"` (ISO 1=Monday … 7=Sunday). Store only numeric weekdays; display in `list.sh` uses L,M,X,J,V,S,D.
- **Window**: A ±15 minute margin applies so that if the worker runs every 60s and the scheduled time is 10:00, the task stays eligible from 09:45 to 10:15.
- **Eligibility**: `start_next.sh` and `run_worker.sh` only pick a task when it is within its scheduled window (and by priority). Tasks without `scheduled_time` / `scheduled_weekdays` are always eligible.
- **Set schedule**: `schedule.sh <task_id> ["HH:MM"] ["1,2,3,4,5"]` adds or updates the schedule in the task frontmatter. Example: `schedule.sh 20250211-120000 "10:00" "1,2,3,4,5"` for weekdays at 10:00.

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
-   `queued/`: Approved and prioritized (001-high, 002-med, 003-low).
-   `active/`: Currently in progress.
-   `completed/`: Finished.
-   `archive/`: Old tasks.

## Output format

Scripts output JSON or simple text depending on flags, optimized for both human reading and machine parsing.
