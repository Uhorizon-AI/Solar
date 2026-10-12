# Console task context

Date: 2026-10-12
Status: pending_review

## Objective
Expose recorded task responsibility, checkpoint and stored schedule in the console on demand, without changing execution or approval.

## Scope
Read-only task-detail endpoint, shared checkpoint parsing, selected-task presentation and synthetic regression tests. Based on main v0.39.1; preserve the native compact approval implementation.

## Acceptance
- Task and MCP/state regressions pass, including invalid checkpoints.
- Selected-task rendering escapes input and preserves execution history.
- No installation update, live task mutation or publication of business data.

## Validation
Combined solar-app/state/MCP suites: 522 passed; one route-list assertion initially failed because this split omitted the new expected route. After correcting that test, all three console UI tests passed. Skill packaging, JS syntax and whitespace checks passed. Visual acceptance remains pending; no installation or client sync performed.
