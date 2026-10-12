# Task spec: console task detail follow-up

**Triage level:** standard
**Date:** 2026-10-12
**Status:** pending_review

Follow-up to `docs/tasks/2026-10-12-console-task-context.md` (merged in v0.40.0). It fixes minor findings from the final reviews and changes no public contract.

## Objective

Close the remaining small gaps in the console task detail: link authority validation, one missing field, shape checks in the page, and a visible destination for the 503 warning.

## Scope

- `core/skills/solar-app/scripts/task_markdown.py`: port range 1 to 65535; bracketed IPv6 with optional port is a valid host; internationalized (non-ASCII) hosts are not linked. Decision: do not punycode-encode them. Encoding would show a link whose visible host differs from the real one (look-alike hosts), so the limitation is documented in the skill under "Not supported, by design"; the punycode form typed by the author is a normal link.
- `core/skills/solar-app/assets/app.js`: show `workspace_id` (English and Spanish); read `context` and `configuration` only when they are plain objects.
- `core/skills/solar-app/scripts/host_server.py`: `configure_logging()` at start. Finding: the host silenced request logs and configured no logging, so the `solar.app` warning would only reach Python's last-resort handler. A single idempotent stderr handler is added, matching how the host already reports errors.
- Layout and presentation after trying v0.40.0 in the browser (`app.js`, `app.css`):
  - `.split` is two equal columns and `.sticky` has no fixed width (it scrolls inside the viewport height); below 900 px the detail stacks under the list. The task list uses a responsive grid class; below 1600 px viewport width it keeps Status, Task and Created so the title stays readable at half width.
  - Field lists reuse `.kv` (label column in grey, value in normal colour, long values wrap) at 150 px label width.
  - `scheduled_weekdays` shows names (Mon..Sun / lun..dom), raw tokens for odd values. `recurring_max_runs` 0 shows as Unlimited: confirmed in `solar_state` (cap applied only when greater than 0) and in the async-tasks references (`0 = unlimited`).
  - "No recorded checkpoint" is shown when only a schedule exists; "No recorded context" only when nothing is recorded. The host-timezone fallback is shown only beside a configured time.
  - The task History is shown newest first (presentation only, `app.js`); the endpoint and solar-state order are unchanged and the newest event carries the highlight.
  - The complete record lists columns, then Instructions (own block, spacing above), then Frontmatter folded by default.
- `core/skills/solar-app/SKILL.md`, `CHANGELOG.md` (Unreleased, Fixed and Changed).
- Tests: `core/tests/skills/solar-app/test_task_detail.py`, `test_console_ui.py`.

Out of scope: MCP, solar-state, the reports and channels change, uppercase port notation (no change needed: ports are digits).

## Decision: shared frontmatter decoding helper (left as debt)

`console_task_detail` decodes the frontmatter in three lines from the raw row, tolerating undecodable JSON. `console_tasks` does not decode frontmatter at all (it reads columns), and `solar_state._task_dict` is strict by contract. A shared tolerant helper would add public API to solar-state for one caller and touch a module this follow-up otherwise does not need. Revisit if a second tolerant caller appears.

## Acceptance criteria

- [x] `:0`, `:99999`, `:65536` are not links; `:1`, `:65535`, `[::1]`, `[2001:db8::1]:8080` are.
- [x] `https://münchen.de` stays text; a test pins it.
- [x] `workspace_id` appears in both languages.
- [x] `context: []`, `configuration: "x"` and similar shapes leave the block, the history and the note intact.
- [ ] Installed acceptance of the layout and the new presentation: pending, outside this change. The visual measurements below come from a local console run from this worktree, not from the installed client.
- [x] The 503 warning reaches stderr with the exception class only; a test pins it.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider
node --check core/skills/solar-app/assets/app.js
python3 -m py_compile <changed .py files>
git diff --check
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/<skill> <dir outside repo>
```

## Completion evidence

- From the repository root: `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider` -> 555 passed (loopback port available). Without `ps` and a writable `$HOME`, three tests (`test_cutover`, two in `test_mcp_cli`) cannot run and the count is 552.
- `node --check`, `py_compile` of the five changed Python files and `git diff --check`: passed. solar-app, solar-state and solar-mcp validated and packaged outside the repository.
- Measured on a local console run from this worktree (loopback, spare port, read only on the real workspace):
  - 800 px: list and detail stacked, 673 px wide, no horizontal scroll.
  - 1280 px: list 490 px and detail 490 px; header shows Status, Task, Created; title cell 268 px.
  - 1440 px: list 570 px and detail 570 px; same three columns; title cell 348 px.
  - 2000 px: list 850 px and detail 850 px; all six columns; label/value lists side by side (150 px label column).
- Logging decisions: `configure_logging()` adds its stderr handler only when neither `solar.app` nor the root logger has one, and leaves propagation at its default. Findings: `solar.app` (used by `app_http.LOGGER` and the host) is the only logger in the framework scripts and nothing else under `solar.*` exists, so setting `propagate = False` would not have silenced any current warning; it would however have hidden them from any later root handler (including test capture). Trusting a configured root keeps one line per warning without that side effect. If a process configures the root after the console started, a warning can print twice (stderr handler plus root); that case is documented and accepted. The log lines are route-specific on purpose: the task-detail route logs `task-detail failed: <class>` and answers "Task detail unavailable"; every other console route logs `console route '<path>' failed: <class>` and answers "Console data unavailable". Neither carries the exception message.
- Link hosts: names must be LDH labels (1 to 63 characters, alphanumeric at both ends), bracketed hosts must be pure IPv6 (IPv4 literals and IPv4-mapped addresses are not links).
- Column threshold: at 1280 to 1440 px the list shows Status, Task and Created; the final choice of columns and of the 1600 px threshold belongs to Louis, who will judge it on the local console. The test parses the CSS, so changing the columns only requires updating it.
- Decisions in review: up to 1600 px of viewport the list keeps Status, Task and Created and hides Provider (usually "no provider"), Channel and Requester; a test reads the CSS and pins it. The frontmatter folds when the complete record closes and stays open across a refresh with a newer `updated_at`. A run limit that is an integer-valued zero shows as Unlimited; other values show as stored. Weekday tokens outside 1 to 7 show as stored. Other console routes answer a fixed message on unexpected read errors (`do_GET` in `host_server.py`); the existing tests do not depend on the old text.
- Not verified: installed acceptance (no install or sync performed).
