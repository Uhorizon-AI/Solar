# Task spec: Solar MCP in three tools

**Triage level:** standard
**Date:** 2026-10-11
**Status:** in review

## Objective

Reduce the public Solar MCP catalog from nine tools to three (`solar_search`,
`solar_docs`, `solar_execute`) without removing a function, widening a permission
or leaving old clients with a silent failure. Integrate task management (create,
edit, schedule, approve, cancel, requeue, archive) with history kept.

## Scope

- `solar-mcp`: tool catalog, operation registry with closed per-operation schemas,
  per-operation gate, audit outcome rows, bounded documents and contracts reader,
  non-executing transition answers for the previous names.
- `solar-state`: version-checked edit, approve and archive; approval digest;
  `scheduled_timezone`.
- Consumers: Client discovery verification, async-tasks / telegram / router docs.
- Not touched: the installed framework, `.solar/`, real tasks, mandates, credentials,
  operational data, releases.

## Acceptance criteria

- `tools/list` is exactly the three tools; resources are unchanged.
- Each previous function is reachable (mapping in `core/docs/mcp-tool-migration.md`).
- Approval binds the operation name and the exact arguments, including the task
  `row_version`; an edit after confirmation invalidates it.
- Editing, scheduling and preparing a revision never queue a task. Approved, active
  and finished tasks keep their instructions.
- A concurrent writer holding a stale version is refused; one of two simultaneous
  edits wins.
- Archiving keeps the row, body and events, and stops a recurrence; it refuses an
  active task, a task others wait on, and a task with running subtasks.
- A Friday 17:00 `Europe/Madrid` weekly task fires at 17:00 local on both sides of a
  clock change; an interval that would skip a run is refused.
- Synthetic acceptance: "Marketing: Weekly AI News" is found, read and a weekly
  editorial-close revision is prepared as an unapproved draft with Marketing /
  Research / Content Creator roles, a short HTML report with three proposals and no
  automatic publication. The source is byte-for-byte unchanged.
- The previous names answer `tool_renamed`, execute nothing and are audited.

## Checks

Per-skill pytest for `solar-mcp`, `solar-state`, `solar-async-tasks`, `solar-client`
and `solar-router`; the full `core/tests` suite; skill package validation for the six
touched skills; `git diff --check`.

## Relation to the local `solar_task_configure`

`task.update` and `task.schedule` are the only task edit routes in this change. A local,
uninstalled `solar_task_configure` exists outside the repository and was not available to
this work; before merging, compare it with these two operations and either adopt one, or
fold anything missing into them. Do not ship two edit routes.

The local planning draft `docs/tasks/2026-10-11-task-configuration.md` (not in this repository)
follows the same rule: recommended outcome is to retire it and absorb whatever it still needs into
`task.update`/`task.schedule`. The decision belongs to the maintainer and is not made by this PR.

Internal callers: nothing in `core/` invokes the `task.cancel`/`task.requeue` operations; the shell
and Python helpers (`requeue_from_error.sh`, `task_cancel.py`) call the `solar-state` session
methods, whose version check stays optional. Only `solar_execute` requires `expected_row_version`.

## Review follow-ups (PR 21)

- `action.run` pins the registered mandate; none registered is refused.
- `task.cancel` / `task.requeue` require `expected_row_version`.
- Frontmatter values come from one serializer; the digest ignores quoting.
- Revisions keep `origin_channel`, `origin_chat_id`, `resources`, `cleanup_*`, `notify_when`.
- `scheduled_time: now` is "no clock restriction".
- `view=result` reads the executor log (`result_path`/`log_path`) inside `task-logs/`, max 60 KB.
- Cases of the removed `test_task_detail.py` live in `test_task_views.py`: detail without repeating
  effects, summary listing never loading detail, malformed/valueless checkpoint refusals. Dropped as
  no longer meaningful: the "task disappears between two reads" race (one read session now) and the
  "empty list for an unknown id" behavior (now `task_not_found`).
- `scheduled_time: now` plus weekdays without an `HH:MM` is `schedule_invalid` (weekdays are never dropped).
- `_execution_result` uses the public `capability_registry.sections`; `log_path` branch and the 60 KB / confinement limits are tested.
