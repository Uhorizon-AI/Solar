# Task spec: <task-name>

**Triage level:** micro / standard / multi-repo
**Date:** YYYY-MM-DD
**Status:** planned / in_progress / blocked / completed

Use this document as the canonical structure for standard-or-higher `solar-code`
tasks. Keep intent, scope, checks, and completion evidence in separate sections.

## Objective

One sentence. What change and why.

## Scope

- Files to modify: <list>
- Files explicitly out of scope: <list>

## Acceptance criteria

- [ ] <criterion 1>
- [ ] <criterion 2>

## Checks to run

List only commands declared in the repo policy allowlist.

```bash
# example
<lint command>
<test command>
```

## References

- Repo policy: <path to CONTRIBUTING.md>
- RFC or context doc: <path or N/A>

## Implementation notes (optional)

- <decision, discovery, or constraint found during execution>

## Completion evidence (optional)

- Validation:
  - `<command>` -> pass / fail / not run
- Files changed:
  - `<path>`
- Notes:
  - <short review-oriented summary>
