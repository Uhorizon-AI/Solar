# Task spec: cursor-restricted-review-99

**Triage level:** standard
**Date:** 2026-10-29
**Status:** completed

## Objective

Make a Cursor repository review able to create its project-state directory inside the write guard, and make `solar client doctor --probe-permissions` detect when that reader cannot start.

## Scope

- Files to modify: `core/skills/solar-router/scripts/repository_reviews.py`, `repository_cli_guards.py`, `cli_permissions.py`, `providers/base.py`, router skill and repository-review docs, `core/skills/solar-client/scripts/client_doctor.sh`, changelog, tests.
- Files explicitly out of scope: client configuration under `~/.cursor`, other open pull requests, releases.

## Acceptance criteria

- [x] A long macOS temp path no longer sends Cursor to `/tmp/.cursor`, which the write guard denies.
- [x] If that fallback would still happen, the failure names `cursor_project_path_outside_write_guard`.
- [x] `solar client doctor --probe-permissions` includes `restricted_reader`, stores it for `solar status`, and does not edit client configuration.
- [x] Tests cover the path rule and the probe with a fake client.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-router/test_repository_cli_guards.py core/tests/skills/solar-router/test_cli_permissions.py core/tests/skills/solar-router/test_repository_reviews.py -q
```

## References

- Repo policy: `CONTRIBUTING.md`
- Issue: https://github.com/Uhorizon-AI/Solar/issues/99

## Implementation notes (optional)

- Cursor CLI 2026.10 (`paths.kL`) keeps `CURSOR_DATA_DIR/projects` only when that base is ≤ 83 characters and the full path ≤ 91. Otherwise it mkdirs `/tmp/.cursor/<slug>`.
- The redacted log line `mkdir '/tmp/.[REDACTED]'` is that path after token-shaped redaction.

## Completion evidence (optional)

- Validation: `uv run --project core/tests pytest core/tests/skills/solar-router -q` on macOS → 729 passed, 3 skipped, 22 subtests. The OS write-guard mkdir ran (`sandbox-exec` is installed). Linux was not run here: no container runtime on this machine. `test_finish_cursor_launch_mkdirs_under_the_os_write_guard` skips where `sandbox-exec` and `bwrap` are both absent.
- Follow-up on review of `d5042e9`: probe compares the installed Cursor path function (`cursor_project_path_drift` / `cursor_project_path_unreadable`); a stored probe without `restricted_reader` is not a failure or an incomplete probe; review directories come from `tempfile`; agy and agent probe details differ; an `EPERM` mkdir of `/tmp/other` stays generic; command overrides are rejected by the probe and by launch.
- Not run from this tree: `solar client doctor --probe-permissions --client agent` and a live `review_batch` use the installed Solar, which does not yet contain this branch. Issue #99 stays open until that install is exercised.
- Files changed: see the commit.
