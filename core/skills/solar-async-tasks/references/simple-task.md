# Reference: Simple Task

A single-execution task. The worker activates it, the AI follows the instructions, writes the artifact and result, and the status becomes `completed`.

## When to use this pattern

- The task produces a single artifact (draft, analysis, summary, etc.)
- No dependency on other tasks
- No human validation required between runs

## Body structure

```markdown
# <Task title>

Act as <agent>. Goal: <concrete objective in one sentence>.

## Context

Read before executing:
- `<path/relevant-file.md>`
- `<path/other-file.md>`

## Instructions

1. <step 1>
2. <step 2>
3. <step 3>

## Deliverable

Write the output to `<path/final-artifact.md>`.

**Path rules:** Artifacts must never go inside `<runtime root>/`. Correct paths by type:
- Sales → `planets/<planet>/operations/sales/`
- Content → `planets/<planet>/operations/marketing/content/`
- Research → `planets/<planet>/operations/marketing/research/`
- Plans → `sun/plans/YYYY/MM/`
```

Because this task is queued/active, writing the declared deliverable path is
already approved. Do not request extra approval just to write that artifact.
Still request explicit approval for external sends, deletions, credentials,
irreversible actions, or changes outside the task body scope.

> **When to add `## Result`:** Only include a `## Result` section in the task body if this task has **no defined output path** above (i.e. the response text itself is the deliverable, not a file). If the body already specifies where to write the artifact, skip `## Result` — the artifact is the output. Never use `## Result` on recurring tasks; it would accumulate across runs. Read the task with `solar_task_status`. Do not search the runtime for a markdown file.

## Minimal frontmatter

```yaml
---
id: "<uuid>"
title: "<title>"
created: "<ISO8601>"
status: queued
priority: normal        # high | normal | low
recurring: false
---
```

## Notes

- The worker changes the status: `queued` → `active` → `completed`
- The Task ID is injected automatically into the prompt by `execute_active.py`
- The log at `logs/<slug>.log` records timing, provider, and errors — the artifact and `## Result` belong in the task file
