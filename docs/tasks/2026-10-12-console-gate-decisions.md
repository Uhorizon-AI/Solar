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

- [x] Decision allowed, decision denied, outcome ok, an old row without `kind`, an explicit `kind: null` on an old row, a corrupt line, a row with neither `kind` nor `allowed`, a row with a non-boolean `allowed` (`"true"`, `1`, `null`), and an unknown kind: only the decisions count.
- [x] No false "Denied" and no Allowed/Denied pair with the same timestamp from one call.
- [x] Only the last 20 decisions are listed; a missing or empty audit gives zeros.

## Checks to run

```bash
# Repository root, with `ps` available and a writable $HOME (loopback binds itself; no port to set).
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider
git diff --check
python3 -m py_compile core/skills/solar-app/scripts/console_data.py
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-app <dir outside repo>
```

## Completion evidence

- From the repository root, with `ps` available and a writable `$HOME`: `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider` -> 577 passed. `git diff --check`, `py_compile` of the changed Python and solar-app packaging: passed.
- Review follow-up: the spec keeps the criteria and the validation commands; the machine-specific audit figures (row breakdown, totals, and the before/after false-"Denied" count on a real audit) live in the PR description as evidence, not as a contract.
- Not verified: installed acceptance.
