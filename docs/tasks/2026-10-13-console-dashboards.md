# Task spec: Console dashboard catalogs

**Triage level:** standard
**Date:** 2026-10-13
**Status:** completed

## Objective

Provide a read-only entry point for planet tools and reports after Tasks.

## Scope

Solar app assets, publication readers, HTTP routes, tests and documentation.
No installation, recurrence, external destinations, tool startup or mutations.
Runtime catalog and plan updates remain in their separate workspace repositories.

## Acceptance criteria

- Dashboards replaces Reports after Tasks, retaining internal id and Reports API.
- Versioned tool catalogs stay separate from generated report indexes.
- Tools declare access mode and copyable startup command.
- Only explicit loopback HTTP root URLs are allowed; exclusions and confinement apply.
- Links open safely in new tabs; Console never probes or starts tools.

## Checks to run

Use solar-app validation commands from SKILL.md, its package validator, and JavaScript syntax check.

## References

- CONTRIBUTING.md
- core/skills/solar-app/references/operation-reports.md

## Completion evidence

- `uv run --project core/tests pytest core/tests/skills/solar-app -q`: 87 passed, 16 subtests passed.
- JavaScript syntax and `git diff --check`: passed.
- solar-app skill package validation: passed.
- Separate worktree from main; pre-existing checkout changes preserved.
- Installation and human acceptance remain pending. Runtime catalog and personal plan are outside this framework PR.
