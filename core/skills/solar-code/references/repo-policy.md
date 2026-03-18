# Repo policy: <repo-name>

**Location of this file:** <planet path that operates this repo>
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
- Rollback: run `git restore <modified-files>` to discard only agent-touched files. Do not use `git checkout .` or `git restore .`.

## Required checks before marking valid

- [ ] Lint OK
- [ ] Tests OK
- [ ] Human review in IDE
