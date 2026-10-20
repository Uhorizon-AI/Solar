# Solar MCP: from nine tools to three

The Solar MCP server publishes exactly three tools. Every function of the previous
catalog is still available; it is reached through a different call. Nothing was
removed, and no authority was added.

| Public tool | Authority | Purpose |
|---|---|---|
| `solar_search` | A0 | Find capabilities, documents, operations, resources and tasks; read one task |
| `solar_docs` | A0 | Read documentation, contracts and references, whole or by section |
| `solar_execute` | per operation | Run one registered operation with its own strict arguments |

Operations: `task.create`, `task.update`, `task.schedule`, `task.approve`,
`task.return_to_draft`, `task.cancel`, `task.requeue`, `task.wait`, `task.archive`,
`telegram.send`, `action.run`.
Find them with `solar_search scope=operations`; read a contract with
`solar_docs id=operation:<name>`.

## Mapping

| Previous tool | New call | What changed |
|---|---|---|
| `solar_capability_search` | `solar_search` `scope=capabilities` | Same arguments and results |
| `solar_capability_describe` | `solar_docs` | Same arguments and results. `id` also accepts `core-doc:<name>` and `operation:<name>` |
| `solar_task_status` (no id) | `solar_search` `scope=tasks` (`query`, `state`, `limit`) | Rows carry `status` (not `drafts`), `row_version` and the schedule. Planned and archived tasks are listed. The console-state view stays in the `solar://tasks` resource |
| `solar_task_status` (`task_id`) | `solar_search` `scope=tasks` `task_id` `view=detail` | Identity and `continuity_checkpoint` are unchanged. An unknown id is `task_not_found`, no longer an empty list. More views: `instructions`, `config`, `status`, `result`, `error`, `history` |
| `solar_task_create` | `solar_execute` `task.create` | `description` is now the required `instructions`. `queued` is gone: create always stores a draft and `task.approve` queues it |
| `solar_task_approve` | `solar_execute` `task.approve` | Requires `expected_row_version`: approval binds the exact stored task |
| `solar_task_cancel` | `solar_execute` `task.cancel` | Requires `expected_row_version` |
| `solar_task_requeue` | `solar_execute` `task.requeue` | Requires `expected_row_version` |
| `solar_telegram_send` | `solar_execute` `telegram.send` | `chat_id` is always required; there is no implicit default chat |
| `solar_action_run` | `solar_execute` `action.run` | The mandate comes from the registration: a skill registered without one is refused, and a caller-supplied mandate must equal the registered one |
| (none) | `task.update`, `task.schedule`, `task.archive` | New task management, below |
| (resources) | `resources/list`, `resources/read` and `solar_search` `scope=resources` | Unchanged |

## Task management

- `task.update` edits a draft or planned task. A planned task returns to draft.
- `task.schedule` sets time, ISO weekdays, an IANA zone and recurrence. A schedule needs an explicit
  zone (`Europe/Madrid`): the hour is read in that zone, so it holds across daylight-saving changes.
  A recurrence interval that would skip an occurrence after a clock change is refused.
- `task.approve` is the only operation that queues. Editing or scheduling never queues a task.
- Approved (queued), active and finished tasks keep what was approved. To change one, create a
  draft revision with `task.create` and `revises_task_id`; the source is untouched. The revision
  cannot be approved while the task it replaces can still run: archive or cancel that one first.
- `task.archive` keeps the row, the body and every event. A queued recurrence is cancelled and
  archived in one step; an active task, a task others wait on, or a task with running subtasks is refused.
- A revision keeps the source's execution restrictions (`origin_channel`), notification destination (`origin_chat_id`) and resource hooks; request/thread ids are not copied.
- Every mutation of an existing task carries `expected_row_version` (from `solar_search`). A stale
  value is refused as `task_changed`; read the task again.

## Transition for clients on the previous catalog

1. The first release with three tools lists only `solar_search`, `solar_docs` and `solar_execute`.
2. A call to a previous name is **not executed**. It returns an error with `code=tool_renamed`,
   `executed=false`, the replacement tool, and a pointer to this document. It is recorded in the
   gate audit (`solar://gate`) as `tool_renamed`, so an operator can see which clients still call it.
3. These answers are kept for two minor releases after the first three-tool release, then removed;
   a previous name is then an ordinary `unknown_tool`. There is never a second public catalog.
4. `solar client` discovery verification accepts either catalog during the same window.
5. Approvals granted before the upgrade name the previous tools and do not apply. They are single-use
   and short-lived; grant again with the operation name (`mcp_approve.py grant task.approve --args ...`).
6. Clients that cached `tools/list` should reconnect once; the server instructions describe the new tools.
