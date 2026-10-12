# Task spec: console reports, channels and Continuity retirement

**Triage level:** standard
**Date:** 2026-10-12
**Status:** pending_review

Based on `main` at v0.41.0 (after the task detail and the status filters); it ships after that release, under `[Unreleased]` in the changelog. Independent of the task-detail work (`docs/tasks/2026-10-12-console-task-context.md`). This change is based on `main` and does not touch the task-detail route, `runtime_views` or the MCP.

## Objective

Let the console open reports that each planet explicitly publishes, retire the global Continuity screen and its summary card, relabel External entry as Channels without promising conversation history, and rename the IDEs screen to Apps.

## Why (decision record)

- Source: `sun/plans/2026/10/2026-10-09_console-contexto-en-tareas-y-canales.md`: global Continuity says what Solar last held from Telegram, n8n or a task, but not what happens in the IDE, so it misleads; context belongs in the task detail. Reports answer "what needs my attention today?" from views each area already publishes.
- Minimal version: a read-only index and file server confined to paths a planet lists itself. No directory browsing, no copy into shared state, no mutation.
- `/api/console/continuity` is kept because it is a published read route; removing it would be a compatibility break with no benefit.

## Scope

- `core/skills/solar-app/scripts/operation_reports.py` (new): index, confinement, size limits, planet exclusions.
- `core/skills/solar-app/scripts/app_http.py`: `GET /api/console/reports` and `GET /reports/<planet>/<path>` with restrictive headers.
- `core/skills/solar-app/assets/app.js`, `app.css`: Reports screen (report cards styled with theme tokens); Continuity screen, navigation entry, summary card and helper removed; the IDEs screen becomes Apps (menu, title, question, tile and column headings in English and Spanish; id `ides` and route `/api/console/ides` unchanged; "IDE" stays only for literal IDE directories); External entry becomes Channels with the note "Entry diagnostics only. Conversation history is not available here."
- `core/skills/solar-app/references/operation-reports.md` (publication contract), `core/skills/solar-app/SKILL.md`, `CHANGELOG.md`.
- Tests: `core/tests/skills/solar-app/test_operation_reports.py`, `test_console_ui.py`.

Out of scope: task detail, MCP, solar-state, any mutation, router, install, sync. Unused translation strings left by the Continuity removal are not cleaned here.

## Acceptance criteria

- [ ] Only files listed in a planet's `operations/leadership/reports/index.json` are served; traversal, symlink escape, wrong suffix, oversize files and excluded planets fail closed.
- [ ] Served HTML carries a sandbox CSP without scripts or forms, `nosniff`, no-store, no referrer.
- [ ] The page no longer calls `/api/console/continuity`; the endpoint still answers.
- [ ] Navigation shows Reports and Channels (English and Spanish) and no Continuity entry or summary card.
- [x] The IDEs screen reads Apps in both languages and keeps its id and route.
- [ ] The test file does not depend on the task-detail PR.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q
node --check core/skills/solar-app/assets/app.js
python3 -m py_compile core/skills/solar-app/scripts/operation_reports.py core/skills/solar-app/scripts/app_http.py
git diff --check
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-app <dir outside repo>
```

## References

- Repo policy: `CONTRIBUTING.md`; plan: `sun/plans/2026/10/2026-10-09_console-contexto-en-tareas-y-canales.md`; earlier PR 24 (branch `feat/console-operation-reports`).

## Completion evidence

- Rebased onto v0.41.0. Conflicts: `CHANGELOG.md` (kept this change under `[Unreleased]` above the released sections) and `app_http.py` (both imports kept: `operation_reports` and `task_markdown`). The Tasks, task detail and status filter code is unchanged from main.
- Full suites from the repository root: `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider` -> 564 passed (without `ps` and a writable `$HOME` three tests cannot run and the count is 561). `node --check`, `git diff --check`, `py_compile` of the changed Python files and solar-app packaging: passed.
- New: a test that `/api/console/continuity` still answers, and a CSS test for the report cards (the links were the browser's default blue on the dark theme).
- Looked at on a local console run from this worktree (loopback, spare port, read only): navigation shows Reports and Channels and no Continuity; the Summary has no Continuity card; Reports shows its empty state when the workspace publishes nothing (no planet has an index today) and, with a simulated response, cards with escaped titles, links only for `/reports/<planet>/operations/...` and an "index unavailable" line; Channels shows its note; Tasks, the detail and the filter bar are as on main.
- Apps rename seen on the local console: the menu reads Apps in English and Spanish (Spanish forced by rewriting the health response in the browser, no setting touched); the screen shows "What does each app see?" / "¿Qué ve cada app?", "Skills per app" / "Skills por app" and the four apps with their real counts; the internal id and route are unchanged.
- Not verified: installed acceptance, and a real published report served end to end outside the tests (no planet publishes an index yet).
