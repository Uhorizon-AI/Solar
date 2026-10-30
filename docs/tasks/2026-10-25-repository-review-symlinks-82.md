# Task spec: repository review internal symlinks

**Triage level:** standard
**Date:** 2026-10-25
**Status:** completed

## Objective

Allow committed internal documentation aliases in repository reviews without weakening snapshot isolation, and identify paths that cannot be reviewed safely.

## Scope

- Repository snapshot construction and MCP error reporting.
- Router and MCP regression tests, repository review contract and changelog.
- Exclude provider configuration, production rollout policy and unrelated local changes.

## Acceptance criteria

- Safe internal file aliases no longer prevent review preparation.
- Absolute, escaping, cyclic, missing and excluded targets remain rejected.
- Effective snapshot content is fixed to the approved Git commit, never the mutable checkout.
- Rejections identify the offending path and reason.
- Existing regular-file snapshots remain compatible.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-router core/tests/skills/solar-mcp -q
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-router /tmp
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-mcp /tmp
solar client sync
```

## References

- Repo policy: CONTRIBUTING.md and core/AGENTS.md.
- Issue: https://github.com/Uhorizon-AI/Solar/issues/82
- Contract: core/docs/repository-readonly-review.md.

## Implementation notes

- Safe aliases are omitted from the disposable copy, without duplicating target files. Their metadata and resolution are bound to approval and listed for the reviewer.
- Original repository aliases remain unchanged. Directory links and unsafe targets remain rejected.
- User clarified that linked content should not be duplicated in the review copy.

## Completion evidence

- Focused repository-review and native review-preparation tests: 145 passed.
- Router and MCP skill package validation: passed.
- `git diff --check`: passed.
- `solar client sync`: passed against the installed framework; this PR is not installed or deployed.
- Broad run (Router, MCP and derived-child state), excluding `test_task_wait.py`: 1,178 passed, 3 skipped, 10 subtests passed. `test_task_wait.py` alone: 21 passed on this branch and 21 passed on base 308bb3a, so the transport stall seen in an earlier run did not reproduce and is not caused by this change.
- Real website PR #232 preflight reaches the independent existing size limit: 792 tracked blobs, 46,281,724 bytes (44.14 MiB), versus 32 MiB. This PR deliberately does not change that policy or claim to unblock full website review.
