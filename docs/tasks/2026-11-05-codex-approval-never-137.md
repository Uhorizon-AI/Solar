---
review_pass: pending
design_frozen: false
last_review: none
---

# Task spec: Codex tasks never ask for approval

**Date:** 2026-11-05
**Status:** implemented on branch `fix/codex-approval-never-137`; Linux not verified; independent reviews pending
**Base:** `ee87d9b` (main, after #135)
**Issues:** #137. Follows `2026-11-05-native-client-sandbox-133.md`.

## Problem

Solar launched Codex tasks with `--sandbox workspace-write` and left `approval_policy` to the user's `~/.codex/config.toml`. That file has `approval_policy = "on-request"` and `approvals_reviewer = "guardian_subagent"`, so a write outside the sandbox is approved by an automatic reviewer. Measured on 2026-11-05 with a real task run through Solar on the installed `ee87d9b`:

| Step (Codex task, real config) | Result |
|---|---|
| Patch tool writes a file in the workspace | ok |
| Patch tool writes `$HOME/solar-133-home-tool-codex.txt` | **written** |
| Shell `echo > $HOME/...` | denied |
| Shell write in `/tmp` | allowed |
| Network from the shell | denied |
| `solar_search` | ok |

The same probe on the other clients (same day, same install): Claude denied the outside write in `/tmp`, Cursor allowed `/tmp` and denied `$HOME` (shell and edit tool); both had no network and a working Solar MCP.

## Change

1. `providers/codex.py`: the default command adds `-c 'approval_policy="never"'`, reusing `WRITE_GUARD_OVERRIDE`, which already protects Codex questions. A command-line `-c` wins over `config.toml`.
2. `test_providers.py`: the default command keeps `workspace-write`, passes `approval_policy="never"` and contains neither `danger-full-access` nor `--dangerously-bypass-approvals-and-sandbox`.
3. Documentation: the table and conditions in `docs/solar-scope-and-enforcement.md` (Codex approval, `/tmp` writable in Codex and Cursor), `README.md`, `routing-policy.md`, `CHANGELOG.md`, and the notes in the previous spec.

## Verified

Same real `~/.codex/config.toml`, the exact command printed by the adapter, run from the workspace: file inside the workspace written; patch outside the workspace rejected (`patch rejected: writing outside of the project; rejected by user approval settings`); shell outside denied; `solar_search` works. Router tests: 836 passed; the only failure, `test_cursor_project_path_matches_the_installed_cli`, also fails on main.

## Not in this change

- `/tmp` stays writable in Codex and Cursor: it is each client's rule and Solar only documents it.
- Hard links, Cursor's project path check (#139), Antigravity (#136) and the Linux runs are unchanged and still open.
- Reading the framework root from Cursor was not probed.

## Risks and rollback

A Codex task that needed the automatic reviewer to leave the sandbox now fails. Set `SOLAR_ROUTER_CODEX_CMD` in the workspace `.env` to the previous command (`codex exec --skip-git-repo-check --sandbox workspace-write -C <workspace> --`).

## Acceptance

- The default Codex command contains `--sandbox workspace-write` and `approval_policy="never"`.
- With a config that has `on-request` and an automatic reviewer, a patch outside the workspace is rejected and the Solar MCP still works. (Measured on 2026-11-05.)
- The router tests pass.
