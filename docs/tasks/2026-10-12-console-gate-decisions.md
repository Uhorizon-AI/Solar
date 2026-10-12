# Task spec: console gate decisions count only decisions

**Triage level:** micro
**Date:** 2026-10-12
**Status:** pending_review

## Objective

Make the Autonomy screen's "Latest decisions" count and list only gate decisions, not the outcome rows the MCP writes after execution.

## Cause

The MCP gate audit (`runtime/mcp/audit.jsonl`) holds two rows per call: `kind: "decision"` (with `allowed`) from `mcp_gate.record`, and `kind: "outcome"` (`ok`, `code`, no `allowed`) from `mcp_gate.record_outcome`. `console_data._gate_decisions()` treated every row as a decision, so the total was inflated and each outcome (no `allowed`) was drawn as "Denied" beside its own "Allowed" decision.

## Scope

- `core/skills/solar-app/scripts/console_data.py`: `_is_gate_decision` and its use in `_gate_decisions()`. A row is a decision when `kind == "decision"`, or when it has no `kind` and a boolean `allowed` (rows written before `kind` existed). Everything else, including corrupt lines, is ignored. Output stays `{total, allowed, last}`.
- `core/skills/solar-app/SKILL.md`, `CHANGELOG.md` (Fixed), `core/tests/skills/solar-app/test_gate_decisions.py`.
- `app.js` needed no change: `renderMandates` derives denied as `total - allowed` and reads `allowed` as truthy, which is correct once only decisions arrive.

Decision not taken: attaching the associated outcome (by `trace_id`) to each listed decision. It would be a few lines, but nothing in the page would show it yet, so it is left out until a screen needs it.

Out of scope: the audit writer, the MCP contract, the state machine.

## Acceptance criteria

- [x] Decision allowed, decision denied, outcome ok, an old row without `kind`, a corrupt line, a row with neither `kind` nor `allowed`, and an unknown kind: only the decisions count.
- [x] No false "Denied" and no Allowed/Denied pair with the same timestamp from one call.
- [x] Only the last 20 decisions are listed; a missing or empty audit gives zeros.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider
git diff --check
python3 -m py_compile core/skills/solar-app/scripts/console_data.py
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-app <dir outside repo>
```

## Completion evidence

- Real audit on this machine (about 72 KB, no row touched): 241 rows = 137 old rows without `kind` + 56 decisions + 48 outcomes. Total before the fix 241, after 193 (137 + 56); allowed stays 164. In the last 20 rows the false "Denied" went from 11 to 0 and the same-time Allowed/Denied pairs from 9 to 0; the 2 remaining non-allowed rows are real `approval_required` decisions, shown as "Asks for approval".
- Seen on a local console run from this worktree (loopback, read only): Autonomy shows 193 decisions, 164 allowed, 29 not allowed; the latest list has 18 Allowed, 2 Asks for approval and no Denied.
- From the repository root: `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider` -> 562 passed (without `ps` and a writable `$HOME` three tests cannot run and the count is 559). `git diff --check`, `py_compile` and solar-app packaging: passed.
- Not verified: installed acceptance.
