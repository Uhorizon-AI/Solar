# Repo policy: <repo-name>

**Location of this file:** <planet or skill path that owns this repo>
**Last updated:** YYYY-MM-DD

## Command allowlist

| Action | Allowed command |
|--------|----------------|
| Lint   | <command>      |
| Tests  | <command>      |

## Restrictions

- Do not touch: <paths or areas>
- Do not run: <prohibited commands>

## Worktree rules

- Before writing: run `git status`; do not overwrite unrelated human changes.
- Rollback: human decides `git checkout` or `git restore` to discard.

## Required checks before marking valid

- [ ] Lint OK
- [ ] Tests OK
- [ ] Human review in IDE
