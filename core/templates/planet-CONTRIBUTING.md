# Contributing to `<planet-name>`

This repository is a code-first planet operated under Solar.

## For Human Contributors

- Follow the repo architecture and conventions described in `AGENTS.md`.
- Run the required validation commands before considering a change complete.
- Keep changes scoped and reviewable.

## AI Agent Policy (Managed by `solar-code`)

This repository uses `core/skills/solar-code/SKILL.md` as the mandatory execution protocol for automated code changes.

### Required operating rules

- Load `CONTRIBUTING.md` before writing files.
- If the change is `standard` or higher, write a task spec before implementation.
- Keep task specs under `docs/tasks/` unless the repo declares a different location in `AGENTS.md`.
- Run only the checks allowlisted in this file.
- Stop on failed required checks and report the failure instead of continuing.

### Checks allowlist

Replace the commands below with the real validation commands for the repo.

| Check | Command | Purpose |
|-------|---------|---------|
| Lint | `<lint-command>` | Static quality validation |
| Tests | `<test-command>` | Regression protection |
| Build | `<build-command>` | Production compilation or packaging |

### Repo-specific rules

- Architecture:
- Testing expectations:
- Release notes / changelog expectations:
- Security or data handling constraints:

---
This file is the official repo policy for `solar-code` in this planet.
