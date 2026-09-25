# Reference: Detached Subtasks (Fire & Forget)

> **Retired pattern.** It relied on the provider creating queue files itself and on the
> worker discovering new tasks by diffing the queue before and after an execution. The
> provider runs sandboxed and cannot write into `SOLAR_TASK_ROOT`, and that diff was
> withdrawn: the worker now creates the children it was asked for, from a `<subtasks>`
> declaration, and always waits for them. `detach_subtasks: true` no longer has any
> effect. Dispatching without waiting would need a new mechanism; what follows is kept
> as the record of how this used to work.

A task that creates children and completes **immediately** without waiting for their results. Children run autonomously. The parent does not synthesize or resume.

## When to use this pattern

- Children are independent and do not need centralized synthesis
- Each child produces its own complete artifact
- The parent acts as an orchestrator/dispatcher, not a synthesizer
- Child results do not block the user or the system

## Key difference vs `task-with-subtasks`

| | Task with subtasks | Detached subtasks |
|---|---|---|
| Parent waits for children | Yes (re-queued) | No (completes immediately) |
| Centralized synthesis | Yes (execution 2) | No |
| Each child is self-contained | Partial | Fully |
| Use case | Multi-AI review with synthesis | Independent parallel delegation |

## How to enable detached mode

Add `detach_subtasks: true` to the parent frontmatter:

```yaml
---
id: "<uuid>"
title: "<title>"
created: "<ISO8601>"
status: queued
priority: normal
detach_subtasks: true    # ← worker skips await_subtasks.sh
---
```

With `detach_subtasks: true`, `execute_active.sh` does not treat newly created tasks as blockers — the parent completes as soon as `execute_active.py` returns success.

## Body structure

```markdown
# <Title>

Act as <agent>. Goal: dispatch the following tasks autonomously.

## Tasks to create

Do not follow this pattern. A new task is `solar_task_create` with `queued: true`. Children that must be waited on are declared in `task-with-subtasks.md`, not dispatched from here.

## Result

When done, find this task file by Task ID inside `<runtime root>/async-tasks/`
and list the created tasks under `## Result`:
  TASK_FILE=$(grep -rl "id: \"<task_id>\"" <runtime root>/async-tasks/ | head -1)
```

## Notes

- Each child must be fully self-contained: context, instructions, and deliverable path in its own body
- Do not use this pattern if you need to aggregate or contrast child results — use `task-with-subtasks.md` instead
- If a child fails, the parent is unaware — design children to be resilient or add explicit notification in their body
- Child execution order is determined by the worker (priority + FIFO); do not assume ordering
