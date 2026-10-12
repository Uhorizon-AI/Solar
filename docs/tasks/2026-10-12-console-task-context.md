# Task spec: console task detail (curated context, schedule, optional complete record)

**Triage level:** standard
**Date:** 2026-10-12
**Status:** pending_review

Supersedes the earlier "complete task detail" revision of this file. PR B (reports, channels, Continuity retirement) is specified separately in its own task spec on another branch and does not touch the task-detail route.

## Objective

When a task is selected in the console, show a curated "Context and follow-up" block (recorded checkpoint, owner, next check, wait, decision, stored schedule configuration) read on demand by task id, with one checkpoint parser shared with the MCP task views; offer the complete stored record (including the Markdown instructions) only on an explicit click.

## Why (decision record)

- Source: `sun/plans/2026/10/2026-10-09_console-contexto-en-tareas-y-canales.md` asks for a curated block, on demand by id, one shared parser, MCP contract intact. It does not ask for a dump of the record.
- Minimal version that solves most of the problem: the curated block. The complete record is an addition from the first revision of this PR; it is kept only as an opt-in behind one cut point (see "Open decision for Louis").
- The console is loopback-only and validates Host/Origin, so exposure is local. The record still holds free-text instructions and every column, including columns added later without review, and the MCP already reads one task under its own authority and approval rules. The console has no such approval layer, so the full record is never loaded by default.

## Response shape (single, final)

`GET /api/console/task-detail?task_id=<id>[&full=1]`

| Status | Body |
|---|---|
| 400 | `{"error": "A bounded task_id is required"}` (missing or longer than 200 chars) |
| 404 | `{"error": "Task not found"}` |
| 503 | `{"error": "Task detail unavailable", "refused": true}`; fixed text for any unexpected read or decode failure, never the exception text |
| 200 | `{"id", "context", "context_error", "configuration"}` |
| 200 with `full=1` (exactly the string `1`) | the same keys plus `"record"` and `"body_html"` |

- `context`: object or `null`. Keys present only when stored: `workspace_id`, `agent`, `planet`, `responsibility`, `agent_contract`, `continuity_checkpoint` (the object decoded by the shared parser).
- `context_error`: `null` or a stable code: `checkpoint_invalid` (checkpoint is not a JSON object) or `frontmatter_unreadable` (stored frontmatter cannot be decoded). When set, `context` is `null`; `configuration` is still returned when it can be read, else `{}`.
- `configuration`: `scheduled_time`, `scheduled_weekdays`, `scheduled_timezone`, `recurring`, `recurring_min_interval`, `recurring_max_runs`, `resources`, `cleanup_required`, `cleanup_timeout`; only keys that are stored.
- `record` (only with `full=1`): the complete solar-state row, including columns added in the future; if the frontmatter cannot be decoded, the raw row with the frontmatter as stored text.
- `body_html` (only with `full=1`): sanitized HTML derived only from `record["body"]`, `null` if the body is not a string.
- Read-only: no write session, no event, no queue, no verification of any recorded effect.
- MCP is unchanged: three tools, same schemas, same `checkpoint_invalid` refusal. MCP only reuses the shared parser.

## What the user sees

1. Selecting a task shows, below the existing detail, a section "Context and follow-up" (Spanish: "Contexto y seguimiento") with the curated fields and the stored schedule (time, IANA zone or "host timezone, no stored zone", ISO weekdays, maximum runs, reserved resources). Execution history, subtasks and approvals are unchanged.
2. With no recorded context: "No recorded context. Execution state and history remain available."
3. With an invalid checkpoint or unreadable frontmatter: a localized message for that task only; the schedule and history stay visible.
4. A note states that reading the record does not verify an effect nor authorize retrying it.
5. A button "Complete record" (Spanish: "Registro completo") loads `full=1` on click only, and shows every column, every frontmatter pair (including unfamiliar fields and malformed entries) and the instructions as safe Markdown.

## Scope

Files to modify:

- `core/skills/solar-state/scripts/runtime_views.py` — `task_checkpoint`, `task_context_fields`, `task_configuration_fields`, `console_task_detail(store, task_id, full=False)`.
- `core/skills/solar-mcp/scripts/task_views.py` — `_checkpoint` reuses `runtime_views.task_checkpoint`; same refusal code and message.
- `core/skills/solar-app/scripts/console_data.py`, `app_http.py` — the route and the fixed 503.
- `core/skills/solar-app/scripts/task_markdown.py` — fixes below.
- `core/skills/solar-app/assets/app.js` — curated block plus on-click complete record.
- `core/skills/solar-state/SKILL.md`, `core/skills/solar-app/SKILL.md`, `CHANGELOG.md`.
- Tests under `core/tests/skills/solar-app/`, `solar-state/`, `solar-mcp/`.

Out of scope: Continuity retirement, Channels, Reports (PR B); any MCP schema, tool or authority change; task mutation or scheduling; router, install, sync.

## Markdown fixes (carried from the review of the first revision)

- Underscore emphasis is not supported (`task_id and user_id`, `__init__` stay text). `*`/`**` emphasis needs a non-space right after the opening mark, a non-space right before the closing mark, and no letter or digit touching the outer sides (`1 * 2 * 3`, `2*3*4` stay text).
- Links: only `http`, `https`, `mailto`. Relative, empty-scheme, protocol-relative, `javascript:`, `data:` and entity-encoded schemes (`java&#x73;cript:`) are not links, while entity-like query text (`?a=1&copy=2`) stays a link because the destination is judged as literal text; the label stays as text and no `<a>` without a safe `href` is emitted.
- Consecutive `> ` lines form one blockquote.
- `---`, `***`, `___` (optionally spaced) on their own line become `<hr>`.
- The 503 never echoes exception text and covers any unexpected failure.
- Unsupported by design (documented in the solar-app skill): link destinations containing parentheses and `|` inside table cells.

## Acceptance criteria

- [ ] Default response contains no `record` and no `body_html`; the UI does not request `full=1` until the button is clicked.
- [ ] Shared parser: MCP and console return the same decoded checkpoint; MCP still refuses `[]`, `null`, broken JSON and `None` with `checkpoint_invalid`.
- [ ] Invalid checkpoint or unreadable frontmatter does not hide configuration (when readable) or history.
- [ ] Complete record shows future columns and malformed frontmatter; unsafe HTML, attributes, images and link schemes stay inert.
- [ ] Reads open no write session and change no row or event.
- [ ] The UI test checks concrete fixture content (not `!includes`) for the curated block, the absence of the record before the click, the record after it, and the stored history.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q
node --check core/skills/solar-app/assets/app.js
python3 -m py_compile <changed .py files>
git diff --check
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/<skill> <dir outside repo>
```

## Open decision for Louis

Should the complete task record (instructions included) be viewable from the console at all? Recommendation: keep it only as the on-click option, local only, and ship it behind this one cut point. If the answer is no, delete `task_markdown.py`, its tests, the `full=1` branch of `console_task_detail` and the route, and the button with its renderer in `app.js`. The curated block, the response keys `id/context/context_error/configuration`, the shared parser and every other test remain valid without change, so PR A stays shippable.

## References

- Repo policy: `CONTRIBUTING.md`; plan: `sun/plans/2026/10/2026-10-09_console-contexto-en-tareas-y-canales.md`.
- Reviewed first revision: PR 23 (branch `feat/console-task-context`).

## Completion evidence

- Baseline on PR 23 head: 527 passed. After the change: 548 passed (solar-app, solar-state, solar-mcp) with a loopback test port. Three tests (`test_cutover` and two in `test_mcp_cli`) need `ps` and a writable `$HOME`; with them the count is 548 passed.
- Review follow-up: the recurring interval is shown (`24 h`), open state is kept per task id, UI strings live in the dictionaries, `import runtime_views` is at module level in the MCP task views.
- Known debt: `console_task_detail` decodes the frontmatter itself instead of sharing a row-to-task helper with `console_tasks`. It reads the raw row on purpose so an undecodable frontmatter can be reported instead of raising, and `console_tasks` goes through `task_list`; unifying them would change that path for a small gain.
- `node --check` on app.js, `py_compile` on changed Python, and `git diff --check`: passed. solar-app, solar-state and solar-mcp validated and packaged outside the repository.
- Public MCP unchanged (three tools); only the checkpoint parser is shared.
- Not verified: installed visual acceptance (no install, sync or update performed).
