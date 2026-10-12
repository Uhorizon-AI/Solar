# Task spec: console task status filters

**Triage level:** standard
**Date:** 2026-10-12
**Status:** pending_review

## Objective

Replace the eight per-status chips of the Tasks screen with a compact, accessible filter toolbar built from groups of the eight stored statuses, without changing data, the state machine or any endpoint.

## Why (decision record)

- The eight chips plus a recurring counter on each repeat what the row pills already say. The earlier derived "Attention" chip mixed failed work with work that was only scheduled or running (`error`, `queued`, `active`, `planned`), so it is removed.
- The design comes from the owner's visual specification, reviewed in the browser; this document records the final definition.

## Definition

Order and members:

| # | Group | Statuses | Visibility |
|---|---|---|---|
| 1 | Errors | error | never hidden; at 0 shows a green check and a good-news panel |
| 2 | Running | active | only when some task is active (or selected) |
| 3 | Drafts | draft | hidden at 0 unless selected |
| 4 | Queue | planned, queued | hidden at 0 unless selected |
| 5 | Done | completed | hidden at 0 unless selected |
| 6 | Closed | cancelled, archived | hidden at 0 unless selected |
| 7 | All | every task, including an unknown status | always |

A real "Recurring" checkbox sits apart on the right. It intersects the selected group, and every chip count follows it. There are no per-chip recurring counters.

- Default filter: the first non-empty of Errors, Running and Drafts; if all three are empty, All. Decided at each opening, never remembered between sessions. The selection may live in the URL hash (`#tasks/<group>`, with `+recurring`), which seeds only the first opening of a page load and is cleared otherwise.
- Selected Errors at 0: "No tasks in error" / "Nothing needs retrying." with a link to the next pending group (Running, Drafts or Queue, in that order); no link when nothing is pending. With the Recurring switch on, the same panel says "No recurring tasks in error" / "Nothing recurring needs retrying.", so it never claims there are no errors when only none are recurring.
- Within any group, active tasks sort first, then by status rank and recency.
- Row pills show all eight states with glyph and text: error ▲ red, active ▶ blue, draft ◌ dashed, planned ◷, queued ≡, completed ✓ neutral, cancelled ⊘ and archived ▭ muted. A recurring task carries a "↻" mark (labelled "Recurring") after its id; it is not a pill.
- Visual: Errors, Running and Drafts are filled; a 1 px separator; Queue, Done, Closed and All are unfilled; the selection keeps the console's amber border, tint and 2 px underline with `aria-pressed`; counts use tabular numerals, muted unless selected. Red is only for Errors (glyph, count with N > 0) and the error pill, blue only for Running and the active pill, green only for the zero-errors check.
- A parent row's "N subtasks" counts every child, filtered or not; the detail lists them all. A parent drawn only as context for a matching child is dimmed and is not a member of the group (it does not count in "Showing N of M").
- Responsive: one bar over both columns (chips never grow; one row at 1280 px). Below 900 px, two rows at 40 px touch height: Errors, Drafts, Running and the checkbox first, the rest below; no horizontal scroll. The checkbox lives inside the toolbar box (its sibling is the chips, ahead of the `.fbreak`), and the toolbar keeps its box (no `display:contents`) so `role="toolbar"` stays exposed.
- Accessibility: `role="toolbar"` labelled "Filter tasks by status"; roving tabindex (arrows, Home and End move; Enter and Space select); each chip labelled with its count; "Showing N of M" announced by a stable `aria-live="polite"` region outside the repainted block, the only status region (the empty-state panel does not add a second announcement, and an empty group announces its own title instead of "Showing 0 of 0"); 2 px focus ring in the text colour (not amber). A repaint that rebuilds the toolbar keeps the focused control, so keyboard navigation continues.

## Scope

- `core/skills/solar-app/assets/app.js`, `core/skills/solar-app/assets/app.css`.
- `core/skills/solar-app/SKILL.md`, `CHANGELOG.md` (Changed), `core/tests/skills/solar-app/test_console_ui.py`.

Out of scope: data, state machine, endpoints, the task detail, and the summary headline in `console_data.attention_line` (a different concept based on errors and drafts).

## Decisions and open points

- The Recurring checkbox sits at the right end of the bar. From 1840 px of viewport the bar is as wide as the list column, so the checkbox lines up with the list's right edge; below that the list is too narrow for seven chips plus the checkbox, so the bar spans both columns and the checkbox sits at the far right.
- On narrow widths the first row is Errors, Drafts and Running (Running shares Drafts' `order:2`), then the rest; the keyboard order stays Errors, Running, Drafts, ... Arrow keys follow the logical order.
- On a phone-width screen the second row can wrap into a third; it never scrolls horizontally.

## Acceptance criteria

- [x] Groups, order and members as defined; empty groups hide; Running only with active tasks.
- [x] Default filter in the four cases (errors, only running, only drafts, all empty) and no memory between openings.
- [x] Recurring checkbox intersects the group and drives the counts; the hash restores selection and checkbox after a reload.
- [x] Active first; Closed is cancelled plus archived; every row keeps its status pill.
- [x] Toolbar semantics, roving tabindex, keyboard and count labels; English and Spanish.
- [ ] Installed acceptance: pending, outside this change.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider
node --check core/skills/solar-app/assets/app.js
git diff --check
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-app <dir outside repo>
```

## Completion evidence

- From the repository root: `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider` -> 558 passed (loopback port available; without `ps` and a writable `$HOME` three tests cannot run and the count is 555).
- `node --check`, `git diff --check` and the solar-app packaging check: passed.
- Looked at on a local console run from this worktree (loopback, spare port, read only on the real workspace; today's counts: Errors 2, Drafts 1, Queue 2, Done 99, Closed 31, All 135, no active task, so no Running chip):
  - 800 px: two rows at 40 px (Errors, Drafts, Running and the checkbox, then Queue, Done, Closed, All), detail stacked, no horizontal scroll.
  - 1280 px: one row of 36 px chips, the checkbox at the far right.
  - 2000 px: chips keep their width in one row; the checkbox lines up with the list's right edge.
  - Zero errors, simulated by rewriting the response in the browser (no data touched): Errors shows a green check and 0; the default moves to Drafts; selecting Errors shows the good-news panel with "Next pending: Drafts (1)". Reloading with `#tasks/errors` reopens Tasks with that filter.
- Not verified: installed acceptance (no install or sync performed).
