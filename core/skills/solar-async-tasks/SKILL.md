---
name: solar-async-tasks
description: >
  Manage asynchronous tasks within Solar. Use for approved deferred work,
  long-running requests, recurring jobs, provider-backed execution, and parent
  tasks that wait on subtasks before synthesizing results.
---

# Solar Async Tasks

## Purpose

Provide a local-first task runtime for Solar. The task is a row in `solar-state`, not a file:

- capture work as drafts,
- approve work before execution,
- queue tasks by priority and schedule,
- execute approved tasks through `solar-router`,
- pause parent tasks until child tasks finish,
- keep resource hooks and their locks under `<runtime root>/async-tasks/hooks/` and `.locks/`.

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

The agent uses `solar_search` to read tasks and `solar_execute` operations to change them. Each operation asks for client approval and writes only through `solar-state`. If the runtime format is not `sqlite`, the operation refuses. They do not change the task's object, scope or effect.

- `task.create` — a draft (or a draft revision of another task with `revises_task_id`). Queuing is `task.approve`, never an option of create
- `task.update` / `task.schedule` — edit or schedule a draft or planned task under `expected_row_version`. They never queue. A queued task that is only renamed keeps its id, place and approval; any other change returns it to draft and withdraws the approval. Results, delivery and errors of earlier runs stay in the body, outside the definition. An active task is immutable and a finished one is not edited: prepare a revision
- `task.return_to_draft` — a queued task back to draft under `expected_row_version`. The approval is withdrawn, so the worker cannot claim it; id, body, schedule, counters and history stay. It needs `task.approve` to queue again
- `task.approve` — a draft, or a task already planned, to the queue, for the exact stored version. Records the approved digest and a snapshot of the definition. Refuses an A3 mandate. There is no separate plan operation
- `task.requeue` — error back to the queue
- `task.cancel` — a queued task becomes cancelled; an active task stays active and the request is recorded
- `task.archive` — retire a task keeping its row, body and events; a queued recurrence is cancelled in the same step
- `solar_search` with `scope=tasks` — list, or read one task (`view`: `detail`, `instructions`, `config`, `status`, `result`, `error`, `history`)

**Approval at claim.** A claim (`claim-next`, `claim`, `activate.sh`) takes a queued task only when its approval covers what is stored: the material fields (not the title) and the definition (the body without the `# {title}` heading and without the runtime sections `## Delivery`, `## Subtask results`, `## Execution Error`, `## Result`). Otherwise the task stays `queued`, the next candidate is tried, and `approval_digest_mismatch` is recorded in `audit` with the reason `absent`, `legacy` (digest of the old algorithm) or `mismatch`. A task in that state is approved again with `task.approve`; nothing is converted automatically, and `python3 core/skills/solar-state/scripts/solar_state.py task list-unapproved` lists the queued tasks the worker is refusing. An explicitly queued task (`create.sh`) is stamped with its own approval. Derived children instead require `Session.materialize_children`: an approved bounded policy and immutable inputs authorize each child, transactionally, with its own digest and provenance. Merely naming a parent never authorizes a child. Limit: once a task has recorded results, text placed under a runtime heading (`## Result` and the others) counts as generated and is not covered by the approval, so instructions never go under those names. Contract: `core/docs/task-approval-contract.md`. **Reservation at claim.** The same claim takes the task's place (capacity, provider limit, declared access, resources; a task that declares no access runs alone) and returns an execution token that the executor, `complete.sh`, `await_subtasks.sh` and the rest use (`SOLAR_TASK_TOKEN`). `start_next.sh` hands the worker the claimed id and token; `execute_active.sh --task <id> --token <token>` runs exactly that claim, and `--once` only takes over an active task nobody runs. With the initial capacity `1` the worker stays sequential. During an update the maintenance barrier stops claims and `ensure_async_tasks.sh`. Contract: `core/docs/execution-reservations.md`. `activate.sh` fails when its claim is refused, and a recurring task's `recurring_last_run` is stamped only after a winning claim.

Contracts and migration from the previous tool names: `solar_docs id=operation:<name>` and `core/docs/mcp-tool-migration.md`.

Host setup stays with `solar-system` and the LaunchAgent. The agent does not start the worker and does not drive the queue through the shell.

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

When `solar-system` supervises `async-tasks`, the agent stops after `task.approve`; the LaunchAgent picks up the queued task on its tick.

Fallback rule: if `solar-system` is not supervising `async-tasks`, run `ensure_async_tasks.sh` **once** as the documented fallback and read its answer (JSON on the last line of stdout): exit `0` ready, `10` starting (a live, identified supervisor is still reconciling: do nothing, the next observation sees the same one), `20` blocked (maintenance, recovery, stale heartbeat or no live identity: report it, do not retry or start anything else), `1` failed. Never start `run_worker.sh` or any other launcher, and never bypass the runtime with direct provider CLIs. `check_async_tasks.sh` only observes (same JSON and codes).

**The resident supervisor.** Production runs one `supervisor.py` per workspace/runtime, started by `launch_supervisor.sh` (detached: its own session, stdin null, stdout/stderr on its own log) and kept alive by the tick (`ensure_async_tasks.sh`, which waits at most 5 seconds for the handshake and never for the tasks). Only the supervisor takes `<runtime root>/async-tasks/.locks/supervisor.lock`, resolved through solar-paths and bound to the workspace owner; the tick and `check_async_tasks.sh` observe its published identity (workspace, runtime, install, pid and start time, heartbeat) without taking the lock or writing its pid. It dispatches every claim by id and token to its own executor in its own process group, collects it with wait/poll and fills a free place within one second of one ending (or of a `SIGUSR1`), without waiting for the next tick. Capacity is decided only by the reservation of `solar-state` (the same one `activate.sh` uses); with the initial capacity `1` it is sequential. `stop_supervisor.sh --drain [--timeout N]` is how an update or a stop asks it to finish its executions and exit; it never removes the lock and never kills by pid. Contract and recovery rules: `core/docs/async-supervisor.md`. `run_worker.sh` is no longer an entry point: it needs `--diagnostic` and goes through the same reservations.

## Workflow

1. Draft: `task.create` stores a draft; `task.update` and `task.schedule` refine it. None of them queues.
2. Approve: `task.approve` moves that draft to `queued`. A task that is already `planned` uses the same operation. There is no operation that creates the plan.
3. Execute: the resident supervisor (kept alive by `solar-system`) claims every eligible queued task the applied policy has room for and executes each in its own process group.
4. Complete: success sets `completed`, recurrence may requeue, failure sets `error`.

For user-facing work, approval ends the conversational agent's execution role. The system runtime owns actual execution.

Use this workflow for:

- Multiprovider review of a plan or proposal, where child tasks may target specific providers and the parent synthesizes results;
- External provider execution that may require network, auth, keychain, browser, or MCP resources;
- Long-running analysis where unavailable providers should be recorded as errors without blocking synthesis from available results.

If the user asked for review before final edits, write a proposal or result artifact and wait for approval before modifying the final target file.

## Execution Consent

**Prepare ≠ queue.** A draft is preparation. `task.approve` moves that draft to the queue and is A2 only for the declared object, scope and effect, bound to the version the approver saw. An A3 mandate cannot approve.

Queued or active tasks are already approved to execute their declared body and write declared artifacts/output paths.

### Deterministic local executor

Approved recurring operations that must run in the host context instead of an AI
provider may declare:

```yaml
executor: local
local_command: bash planets/<planet>/skills/<skill>/scripts/approved.sh
local_timeout: 300
```

The command is tokenized without a shell (`shlex`), runs with `cwd=SOLAR_WORKSPACE`,
and the primary script must resolve under an allowlisted tree:

- `planets/<planet>/skills/<skill>/scripts/…`
- `solar/core/skills/<skill>/scripts/…` (or `core/skills/<skill>/scripts/…`)

Paths such as `planets/*/operations/scripts/…` are refused. Arbitrary binaries,
paths outside the workspace, or scripts outside those trees are refused
(`local_command_unauthorized`) and the status becomes `error`.

Exit codes treated as success:

| Code | Meaning |
|---|---|
| `0` | Success (work applied or OK) |
| `10` | Success with no changes (caller convention; e.g. calendar-sync `NO_CHANGES`) |

Any other exit, missing `local_command`, invalid `local_timeout`, or unauthorized
path sets the status to `error` with the real command output (fail-closed).

Still request **A2 formal** approval for:

- external sends (never A2-implicit; apply domain gates such as ECG),
- deletions,
- credential changes,
- irreversible actions,
- writes outside the declared task scope.

See `references/execution-consent.md` and `solar-router/references/authority-gate.md`.

## Task Body Authoring

The task body is the instruction set executed by the provider.

Use `## Result` in the task file when:

- the task is a child task whose parent will read its output,
- the body does not define a concrete output path.

Do not append `## Result` when the task writes a dedicated artifact such as a plan, report, message draft, or recurring run output. In that case, the artifact is the result.

`## Result` is never what the origin chat receives. A gateway parent ends its reply with a `<delivery>` block, the worker copies it into the task body as `## Delivery`, and the notification sends that section — see `references/runtime-operations.md`. `## Result` stays the full account, for the parent reading its children.

Read a task with `solar_search` (`scope=tasks`). The status is a column. Do not search `async-tasks/` for a markdown file.

## Parent Tasks With Subtasks

Use parent tasks when final output depends on approved independent child reviews. Independence alone does not grant concurrency; production capacity remains 1 and reader profiles are disabled.

Rules:

- Execution 1 **declares** children in a `<subtasks>` block and stops. The provider never writes into the queue: the worker materializes only exact templates and inputs covered by the parent's approved `subtask_policy`.
- The worker records them in `subtask_ids` (durable) and requeues the parent with `blocked_by_task_ids` (the wait's traffic light).
- `start_next.sh` skips the parent until child tasks are terminal.
- `completed`, `archived`, `cancelled`, and `error` are terminal for dependency purposes.
- Execution 2 reads `## Subtask results`, including failures, and starts one recorded synthesis attempt. An uncertain interrupted attempt requires explicit recovery.
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

The status is a column on the task row:

- `draft`: captured, not executable.
- `planned`: ready for review, not executable.
- `queued`: approved and eligible for execution.
- `active`: currently executing.
- `completed`: finished successfully.
- `error`: failed and requires manual fix/requeue.
- `archived`: historical or max-run recurring tasks.
- `cancelled`: stopped before or during execution.

Only `queued` is worker input. Execution logs live in `<runtime root>/task-logs/`. Resource hooks and lock files stay under `<runtime root>/async-tasks/hooks/` and `.locks/`.

## Validation

After modifying this skill:

```bash
uv run --project core/tests pytest core/tests/skills/solar-async-tasks -q
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-async-tasks /tmp
```

After any `core/skills/` change, run:

```bash
solar client sync
```

## Cancellation

Request cancellation with `task.cancel`. An active task stays active until the worker stops it.
The executor confirms `cancelled` only after process-group termination and cleanup.
Voice OS D9 may queue explicit, bounded local preparation through the Host; the original request supplies authority, not the acknowledgement.
