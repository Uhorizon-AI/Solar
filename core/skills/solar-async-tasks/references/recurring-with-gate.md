# Reference: Recurring Task with Gate

A recurring task that requires human validation between each execution. The gate prevents the loop from running indefinitely without review — each iteration waits for explicit approval before the next one.

## When to use this pattern

- The task produces a diagnostic or artifact that a human must review before the next cycle
- The output of each run informs the next execution
- Explicit control over cadence is needed beyond `recurring_min_interval`

## Flow

```
Run N
  └─► Reads state file → gate: open → executes
  └─► Writes artifact to iterations/ (or equivalent)
  └─► Sets gate: locked in state file
  └─► complete.sh re-queues the task (recurring: true)

Human reviews the artifact
  └─► Sets gate: open in state file

Run N+1 (when scheduled_time is met)
  └─► Reads state file → gate: open → executes
  └─► ...
```

If the gate is `locked` when the worker activates the task, it completes in 1–2 sentences without producing a new artifact.

## Body structure

```markdown
# <Title>

## 0. Read gate

1. Open `<path/state.md>`.
2. If `gate: locked`: respond in one or two sentences stating that an iteration is
   pending human validation and how to unblock it. Include `<solar_summary>` with
   `blocked_pending_validation`. Do not write any new artifact.
3. If `gate: open`: continue to §1.

## 1. Execute

<task instructions>

## 2. Write artifact

<instructions for writing the result to the correct path>

Do **not** append `## Result` to this task file — it is recurring and re-enters the queue
after each run. Write the output to the dedicated artifact path defined above instead.

Writing the dedicated artifact path is covered by the queued task approval. Do
not request extra approval for that write. Still request explicit approval for
external sends, deletions, credentials, irreversible actions, or changes outside
the declared recurring task scope.

## 3. Close the gate

Update `<path/state.md>`:
- Set `gate: locked` with a reference to the artifact just produced.

The human will review the artifact and set `gate: open` to authorize the next run.

## 4. Summary

Include `<solar_summary>` on a single line with the run status.
```

## State file reference

```markdown
# <Loop name> state

gate: open
last_validated_run:
```

- `gate: open` → next run executes fully
- `gate: locked` → next run only notifies and completes without artifact
- `last_validated_run` → reference to the last artifact validated by the human

## Frontmatter

```yaml
---
id: "<uuid>"
title: "<title>"
created: "<ISO8601>"
status: queued
priority: normal
recurring: true
recurring_min_interval: 86400    # minimum seconds between runs (86400 = 1 day)
recurring_max_runs: 0            # 0 = unlimited
scheduled_time: "09:00"          # ±15 min window in host local time
scheduled_weekdays: "1,2,3,4,5" # ISO: 1=Mon … 7=Sun
---
```

## Notes

- The gate is independent of `recurring_min_interval` — both must be satisfied for a run to produce an artifact
- Do not use the gate as an emergency pause mechanism; instead move the file to `planned/` or set a far `scheduled_time`
- If the task also uses subtasks (see `task-with-subtasks.md`), the gate must only be closed in the synthesis execution (execution 2), never in the child-creation execution (execution 1)
