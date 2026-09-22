---
name: solar-state
description: >
  What is in the runtime state: tasks, the router audit, cross-channel
  continuity and the events of A3 mandates, in one SQLite base that only this
  skill opens. `solar-paths` says where; this says what. Use when a component
  needs to read or change shared runtime state — never by opening the files or
  the base directly.
---

# Solar State

`solar-paths` answers **where** runtime state lives. This skill answers **what
is there**, and is the only thing that reads or writes the state more than one
component uses.

**Status: foundation.** The base, its API and its guards exist and are tested.
No component uses them yet, and no runtime has been moved onto them: the
cutover (`migrate` / `rollback`), the import of the existing files, the checks
in every entry point, the move of each reader and writer, and the MCP verbs are
later steps of the plan. Until then every runtime is on `STATE_FORMAT=files`
(or unset), and this skill refuses to open it.

## Required MCP

None

## What lives here

| In the base | What it is |
|---|---|
| `tasks` | One row per async task: status, the frontmatter as an ordered list, the body |
| `transitions` | Every allowed status move. A move not in the table fails |
| `task_links`, `task_events` | Parent–child relations; every status change, with who made it |
| `audit` | The router audit, one JSON line per row, verbatim |
| `continuity` | The cross-channel intention, one JSON document |
| `delegation_events` | The `events` and `shadow` streams of each A3 mandate |

Not here, on purpose: the mandates themselves (YAML that Louis writes in
`sun/delegations/`), execution logs (files; a task keeps the path), and state
only one component reads (router conversations, `gateway/`, `host/`, `mcp/`).

## How to use it

Python:

```python
_STATE_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "solar-state" / "scripts"
if str(_STATE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_STATE_SCRIPTS))

import solar_state  # noqa: E402

with solar_state.session() as state:
    task_id = state.task_create([("title", '"Review the plan"'), ("priority", "normal")],
                                body="# Review the plan\n", status="queued")
    if state.task_claim(task_id, worker="worker-1"):
        ...
```

Bringing existing state in, verbatim (for the cutover):

```python
state.task_import(document_text, status="queued")   # the pairs, untouched
state.audit_import_line(line)                        # the JSON line as written
state.delegation_event_import_line(mandate, "events", line)
state.continuity_import_text(text)
```

and back out: `task_export`, `audit_lines`, `delegation_event_lines`,
`continuity_text`.

Bash, through the CLI (JSON out; exit 2 on a refusal, 3 on a lost claim):

```bash
python3 "$SCRIPT_DIR/../../solar-state/scripts/solar_state.py" task claim "$TASK_ID" --worker "$$"
python3 "$SCRIPT_DIR/../../solar-state/scripts/solar_state.py" task show "$TASK_ID"
python3 "$SCRIPT_DIR/../../solar-state/scripts/solar_state.py" status   # says why it would refuse
```

## The rules that keep it the owner

1. **Only this skill opens `state.sqlite`.** Nobody else writes SQL against it.
2. **It imports nothing but `solar-paths`.**
3. **Every operation holds the shared lock from start to finish**; a cutover
   holds it exclusive. Nobody checks before and writes after.
4. **This code only speaks `STATE_FORMAT=sqlite`.** Any other value, a missing
   base or an older schema refuses with `StateUnavailable`. It never falls
   back to reading the old files.
5. **Schema migrations run only inside a cutover**, with a copy of the base
   first. A session never upgrades under other readers.
6. **What comes in verbatim goes out verbatim.** A task's frontmatter is
   stored as `[key, text after the colon]` in order, and the columns are a
   projection of it, rewritten in the same transaction. Audit lines, mandate
   events and the continuity document are stored as the text they were.
7. **One id per task.** A frontmatter `id` that differs from the one given, or a
   key that appears twice, is refused.

## Backups

- Before each schema migration: `state-backups/pre-migration/`, never rotated.
- Daily: `state-backups/daily/`, 7 kept. Taken when a session opens and the
  newest copy is older than 24 h, so it does not depend on the orchestrator.
- `inspect_backup(path)` opens a copy read-only and reports schema, integrity
  and counts.
