# Reference: Task with Subtasks

A task that delegates work to child tasks, waits for their execution, and synthesizes their results upon resumption. This is the **same task** across two executions — not two separate tasks.

## When to use this pattern

- You need to run the same work in parallel with different providers or configurations
- The final result depends on aggregating or contrasting child outputs
- Children are independent from each other

## Flow

```
Execution 1 (parent)
  └─► Creates child tasks via create.sh --queued
  └─► execute_active.sh detects new IDs in queued/
  └─► await_subtasks.sh re-queues the parent with blocked_by_task_ids
  └─► Parent waits in queued/, blocked

Worker processes children (by priority order)
  └─► Each child writes its ## Result into its own task file

Execution 2 (same parent, unblocked once all children complete)
  └─► Reads ## Result from each child task file
  └─► Synthesizes and writes the final artifact
  └─► Writes ## Result into the parent task file
```

## Detecting which execution you are in

The body must distinguish execution 1 from execution 2. The simplest signal is checking whether the expected output artifact already exists:

```bash
# Example: check if an output file for this task ID already exists
TASK_SHORT="<first-8-chars-of-task-id>"
EXISTING=$(ls <output/path/> | grep -v template | grep "$TASK_SHORT" | head -1)

if [[ -z "$EXISTING" ]]; then
  echo "Execution 1 — create subtasks"
else
  echo "Execution 2 — synthesize results"
fi
```

> The full Task ID is injected into the prompt as `Task ID: <uuid>`. Use it to build `TASK_SHORT`.

## Execution 1 — create child tasks

Child tasks **must** write their result under `## Result` in their own task file — the parent reads from there during execution 2. This is the primary case where `## Result` is required.

```bash
# 1. Write the child prompt once
cat > /tmp/child-prompt.md <<'BODY'
<instructions for the child task>

When done, find this task file by Task ID inside sun/runtime/async-tasks/
and write your response under ## Result:
  TASK_FILE=$(grep -rl "id: \"<task_id>\"" sun/runtime/async-tasks/ | head -1)
BODY

# 2. Get available providers, excluding the current one
OTHERS=$(bash core/skills/solar-router/scripts/list_providers.sh \
  --exclude <current-provider> --format csv)

# 3. Create one child per provider using solar-async-tasks
for PROVIDER in $(echo "$OTHERS" | tr ',' ' '); do
  bash core/skills/solar-async-tasks/scripts/create.sh \
    --queued \
    --provider "$PROVIDER" \
    --body-file /tmp/child-prompt.md \
    "Review ${PROVIDER}: <doc>"
done

# 4. Stop here — the worker detects the children and pauses the parent automatically
```

**Critical rules:**
- Do not write the final artifact in execution 1 — results are not available yet
- Do not call `run_router.py` directly — it bypasses the worker and providers fail without auth
- Do not touch any gate or state file in execution 1

## Execution 2 — synthesize

Children have completed and their results are in their task files:

```bash
# Child task files are in completed/ with ## Result appended
TASK_FILE=$(grep -rl "id: \"<child_task_id>\"" sun/runtime/async-tasks/ | head -1)
cat "$TASK_FILE"  # includes the ## Result section written by the child
```

With results read:
1. Write the final artifact to the intended path
2. Write `## Result` into the parent task file (find it by Task ID)

## Full body schema

```markdown
# <Title>

## Execution detection

[instruction to check for output artifact by task ID short]
- Not found → Execution 1
- Found → Execution 2

## Execution 1 — Create subtasks

[instructions to write /tmp/child-prompt.md]
[create.sh calls per provider]
Stop here. Do not write artifacts or modify any state.

## Execution 2 — Synthesize

[instructions to read ## Result from each child]
[instructions to write final artifact]
[instruction to write ## Result into this task file by Task ID]
```

## Frontmatter

```yaml
---
id: "<uuid>"
title: "<title>"
created: "<ISO8601>"
status: queued
priority: normal
recurring: false        # or true for a periodic loop
---
```

## Notes

- `blocked_by_task_ids` is managed automatically by `await_subtasks.sh` — do not set it manually
- `start_next.sh` removes `blocked_by_task_ids` from the frontmatter before activating the parent in execution 2
- The log for each child (`logs/<slug>.log`) contains execution metadata; the result goes in the task file under `## Result`
