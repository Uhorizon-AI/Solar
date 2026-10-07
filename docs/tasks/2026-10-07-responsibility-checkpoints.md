# Task spec: responsibility checkpoints (independent deferred draft)

**Date:** 2026-10-07
**Triage level:** standard
**Status:** deferred / in review

## Objective and prerequisite

Preserve the implementation separated from discovery without merging or
activating it prematurely. First demonstrate resumption of a representative
responsibility with existing tasks, results and continuity state. The maintainer
must identify the unmet recovery need and accept this extra schema before this
draft can proceed. Isolated test success does not satisfy that prerequisite.

## Scope

- Append SQLite schema v5 with bounded agent/responsibility checkpoint keys.
- Read and save through solar-state only, with expected-version conflict checks.
- Add only MCP checkpoint Get/Put. Keep existing seven verbs' validation.
- Load state only for explicit router identity; forward task-frontmatter identity
  during async dispatch. No automatic checkpoint persistence or work activation.
- Preserve the legacy file rollback refusal while checkpoint rows exist, because
  that format cannot export them. This is a deliberate deployment consequence
  requiring maintainer review, not an instruction to erase state.
- No Search/Describe, inventory changes, Client profile, production migration,
  per-agent databases, new permissions or model training is included.

## Acceptance and checks

Use isolated runtime ownership fixtures for State, MCP, Router and Async Tasks.
Check persistence across sessions, responsibility isolation, field/size bounds,
stale versions, exact-call approval, native confirmation with nested data,
router recovery and dispatch metadata. Validate all four changed skill packages,
run contained native Client sync, and check shell syntax, links and whitespace.

Maintainer must approve recovery evidence, checkpoint ownership/retention and
schema deployment/reversion strategy before merge or installation. Preserve the
existing SQLite runtime and backups if reverting framework code after writes.

## Review evidence

The code originates from the previously reviewed PR 9 and has been separated
onto a branch from main. Independent validation: **548 passed, 1 skipped, 10 subtests passed** across
State, MCP, Router and Async Tasks; all four skill packages, local links/fences,
whitespace checks and supported native Client sync in a temporary runtime passed.
This draft stays deferred even if all isolated code checks pass.
