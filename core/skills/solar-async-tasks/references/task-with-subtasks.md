# Reference: Task with Subtasks

A task that delegates work to child tasks, waits for them, and synthesizes their results when it resumes. This is the **same task** across two executions — not two separate tasks.

The provider never writes into the task queue. It **declares** the children it wants and stops; the worker creates them, waits, and serves their results back. A provider running in a sandbox (codex) cannot write into `SOLAR_TASK_ROOT`, which is why declaring is the only supported path.

## When to use this pattern

- You need to run the same work in parallel with different providers or configurations
- The final result depends on aggregating or contrasting child outputs
- Children are independent from each other

## Flow

```
Execution 1 (parent)
  └─► Provider ends its reply with a <subtasks> block and stops
  └─► execute_active.py validates it, writes subtask_ids, creates the children,
      and exits 20 without touching the queue
  └─► execute_active.sh translates that into await_subtasks.sh
  └─► Parent waits in queued/, blocked

Worker processes children (by priority order)
  └─► Each child's result stays in its own log; it writes nothing into the queue

Execution 2 (same parent, unblocked once all children are terminal)
  └─► execute_active.py writes ## Subtask results into the parent
  └─► Provider reads them from its own task body, synthesizes, writes ## Result
```

## Detecting which execution you are in

`## Subtask results` in the task body means execution 2: the children are done and their results are right there. Without it, and without an output artifact for this task, this is execution 1.

> The full Task ID is injected into the prompt as `Task ID: <uuid>`.

## Execution 1 — declare the children

Close the reply with one block. Nothing else is needed, and nothing else is accepted:

```
<subtasks>
[
  {"title": "Review with claude", "body": "<full instructions for the child>", "provider": "claude"},
  {"title": "Review with agy", "body": "<full instructions for the child>"}
]
</subtasks>
```

Rules, all of them hard:

| Rule | Detail |
|---|---|
| Format | One JSON list. If several blocks appear, the last one wins |
| `title` | Required, text, up to 120 characters |
| `body` | Required, text, up to 8000 characters. Self-contained: the child sees nothing else |
| `provider` | Optional, one of `codex`, `claude`, `agy`, `agent`. Picks the model for that child |
| Any other key | Rejects the whole block |
| Cap | 5 children. A sixth rejects the whole block; it does not stop at five |
| Depth | One. A task that already has `parent_task_id` cannot declare children: its block is ignored |
| Second batch | A parent that already has `subtask_ids` cannot declare again: the block is ignored |

A malformed block, an unknown provider, a key that is not allowed or more than five children creates **nothing** and sends the task to `error/` with the reason named. Half a batch is never created.

**Critical rules:**
- Do not write anything into the task queue
- Do not write the final artifact in execution 1 — results are not available yet
- Do not call `run_router.py` directly — it bypasses the worker and providers fail without auth
- Do not touch any gate or state file in execution 1

## What the worker fixes, and what it takes from you

| Field of the child | Who sets it |
|---|---|
| `title`, `body`, `provider` | The provider, inside the contract above |
| `object`, `scope`, `effect` | The worker, inherited from the parent unchanged, in the frontmatter and as an `## Object` section at the top of the child's body — frontmatter is stripped before the prompt, so the section is what the child actually reads |
| `parent_task_id`, `subtask_key` | The worker, written in the same atomic write as the rest of the task |
| `priority` | The worker: the parent's |
| Origin and notification | The worker: **none**. Only the parent notifies the chat |
| `delivery_expected` | The worker: **no**. The delivery belongs to the parent |

## Execution 2 — synthesize

The children's results are already in this task, under `## Subtask results`, one section per child with its key, its status and its result (truncated at 4000 characters, marked when truncated). A child that failed appears with its status and its reason — it is never omitted.

With results read:
1. Write the final artifact to the intended path
2. Write `## Result` into the parent task file
3. Say in the delivery which part was not covered, if a child failed

**A failed child does not stop the parent.** It synthesizes with what it has, the same way the unblock already reactivates the parent whether a child ends well or in error.

## Frontmatter

```yaml
---
id: "<uuid>"
title: "<title>"
created: "<ISO8601>"
status: queued
priority: normal
recurring: false        # or true for a periodic loop
subtask_ids: "<key>=<child id>,<key>=<child id>"   # written by the worker
---
```

## Notes

- `subtask_ids` is the durable record of which children were this parent's, and it is never cleared. `blocked_by_task_ids` is the traffic light of the wait and is removed on unblock (`start_next.sh`) and on activate (`activate.sh`) — do not use it as the execution-2 signal, and do not set either by hand
- The declaration itself is kept beside the queue, in `subtasks/<parent id>.json`, so an interrupted creation can be resumed. On the next run the worker finishes creating what is missing and does not call the provider at all
- `subtask_key` is derived from the parent id, the position and a digest of title and body: the same declaration always produces the same key, which is what makes a retry idempotent
- Each child's result lives in its log (`logs/<slug>.log`), under `## Result` or `## Error`. Children do not write into their own task file and do not write into the parent's
