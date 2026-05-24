---
name: solar-async-tasks
description: >
  Manage asynchronous tasks within Solar. Use for approved deferred work,
  long-running requests, recurring jobs, provider-backed execution, and parent
  tasks that wait on subtasks before synthesizing results.
---

# Solar Async Tasks

## Purpose

Provide a local-first, filesystem task runtime for Solar:

- capture work as drafts,
- plan and approve work before execution,
- queue tasks by priority and schedule,
- execute approved tasks through `solar-router`,
- pause parent tasks until child tasks finish,
- preserve task state under `sun/runtime/async-tasks/`.

Use this skill when the work should not block the current conversation, needs provider execution, spans multiple AI providers, waits on subtasks, recurs over time, or depends on external resources.

## Required MCP

None

## Dependencies

- `solar-router`: executes active tasks with `channel=async-task` and `mode=direct_only`.
- `solar-system`: optional but preferred host supervisor for automatic queue processing.

Router diagnostics:

```bash
bash core/skills/solar-router/scripts/onboard_router_env.sh
bash core/skills/solar-router/scripts/diagnose_router.sh
```

## Core Commands

```bash
# Setup runtime directories
bash core/skills/solar-async-tasks/scripts/setup_async_tasks.sh

# Create a task draft
bash core/skills/solar-async-tasks/scripts/create.sh "My Task" "Do something useful"

# Plan and approve
bash core/skills/solar-async-tasks/scripts/plan.sh <task_id>
bash core/skills/solar-async-tasks/scripts/approve.sh <task_id> normal

# List task state
bash core/skills/solar-async-tasks/scripts/list.sh

# Schedule or recur
bash core/skills/solar-async-tasks/scripts/schedule.sh <task_id> "10:00" "1,2,3,4,5"
bash core/skills/solar-async-tasks/scripts/set_recurring.sh <task_id>

# Requeue after fixing an error
bash core/skills/solar-async-tasks/scripts/requeue_from_error.sh <task_id>

# Validate lifecycle and packaging
bash core/skills/solar-async-tasks/scripts/validate_lifecycle.sh
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-async-tasks /tmp
```

Operator-only execution entrypoint:

```bash
bash core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh
```

Do not call `run_worker.sh` directly. `ensure_async_tasks.sh` is the only execution entrypoint, and normally `solar-system` calls it automatically.

## System Activation

For automatic host-level execution, enable `async-tasks` through `solar-system`:

```dotenv
SOLAR_SYSTEM_FEATURES=async-tasks
```

Install or check the host orchestrator through `solar-system`:

```bash
bash core/skills/solar-system/scripts/install_launchagent_macos.sh
bash core/skills/solar-system/scripts/check_orchestrator.sh
```

When `solar-system` supervises `async-tasks`, the agent stops after `approve.sh`; the LaunchAgent picks up the queued task on its tick.

Fallback rule: if `solar-system` is not supervising `async-tasks`, use `ensure_async_tasks.sh` once as documented fallback. Do not bypass the runtime with direct provider CLIs.

## Workflow

1. Draft: `create.sh` writes to `drafts/`.
2. Plan: `plan.sh` moves the task to `planned/`.
3. Approve: `approve.sh` moves it to `queued/` with priority.
4. Execute: `solar-system` calls `ensure_async_tasks.sh`, which starts one eligible queued task and executes it.
5. Complete: success moves to `completed/`, recurrence may requeue, failure moves to `error/`.

For user-facing work, approval ends the conversational agent's execution role. The system runtime owns actual execution.

Use this workflow for:

- Multiprovider review of a plan or proposal, where child tasks may target specific providers and the parent synthesizes results;
- External provider execution that may require network, auth, keychain, browser, or MCP resources;
- Long-running analysis where unavailable providers should be recorded as errors without blocking synthesis from available results.

If the user asked for review before final edits, write a proposal or result artifact and wait for approval before modifying the final target file.

## Execution Consent

Queued or active tasks are already approved to execute their declared body and write declared artifacts/output paths.

Still request explicit approval for:

- external sends,
- deletions,
- credential changes,
- irreversible actions,
- writes outside the declared task scope.

See `references/execution-consent.md`.

## Task Body Authoring

The task body is the instruction set executed by the provider.

Use `## Result` in the task file when:

- the task is a child task whose parent will read its output,
- the body does not define a concrete output path.

Do not append `## Result` when the task writes a dedicated artifact such as a plan, report, message draft, or recurring run output. In that case, the artifact is the result.

Find the current task file by Task ID because files move between state folders:

```bash
TASK_FILE=$(grep -rl "id: \"<task_id>\"" sun/runtime/async-tasks/ | head -1)
```

## Parent Tasks With Subtasks

Use parent tasks when final output depends on independent child tasks, such as multiprovider feedback.

Rules:

- Execution 1 creates child tasks and stops.
- The runtime requeues the parent with `blocked_by_task_ids`.
- `start_next.sh` skips the parent until child tasks are terminal.
- `completed`, `archived`, and `error` are terminal for dependency purposes.
- Execution 2 reads child `## Result` sections and synthesizes the final artifact.
- Do not use `blocked_by_task_ids` as the task body's execution-2 signal; it is internal runtime metadata and is removed before activation.

See `references/task-with-subtasks.md`.

## Reference Guides

| Pattern | File |
|---|---|
| Single execution | `references/simple-task.md` |
| Subtasks with synthesis | `references/task-with-subtasks.md` |
| Detached subtasks | `references/detached-subtasks.md` |
| Recurring task with validation gate | `references/recurring-with-gate.md` |
| Execution consent | `references/execution-consent.md` |
| Scheduling, recurrence, cleanup, notifications, errors | `references/runtime-operations.md` |
| Resource hook system | `references/hook-system.md` |

## Runtime States

Default root: `sun/runtime/async-tasks/`

- `drafts/`: captured, not executable.
- `planned/`: ready for review, not executable.
- `queued/`: approved and eligible for execution.
- `active/`: currently executing.
- `completed/`: finished successfully.
- `error/`: failed and requires manual fix/requeue.
- `archive/`: historical or max-run recurring tasks.

Only `queued/` is worker input.

## Validation

After modifying this skill:

```bash
uv run --project core/tests pytest core/tests/skills/solar-async-tasks -q
bash core/skills/solar-async-tasks/scripts/validate_lifecycle.sh
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-async-tasks /tmp
```

After any `core/skills/` change, run:

```bash
bash core/scripts/sync-clients.sh
```
