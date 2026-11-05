---
review_pass: pending
design_frozen: false
last_review: none
---

# Task spec: launch Antigravity with its own sandbox on

**Date:** 2026-11-05
**Status:** implemented on branch `fix/agy-native-sandbox-136`; Linux not verified; independent reviews pending
**Base:** `032a66d` (main)
**Issues:** #136. Follows `2026-11-05-native-client-sandbox-133.md` and `2026-11-05-codex-approval-never-137.md`.

## Problem

Solar launched Antigravity (`agy` 1.5.1) with `--dangerously-skip-permissions`, which approves every tool call. Measured on macOS as a real Solar task: shell and edit tool wrote in `$HOME`, the shell wrote in `/tmp` and had network (HTTP 200); the Solar MCP worked. No protection.

## Change

1. `providers/agy.py`: the default command is `agy --sandbox --mode accept-edits --settings <json> --add-dir <workspace>`. The settings are `toolPermission: "proceed-in-sandbox"` and `permissions.allow` with `mcp(solar/solar_search)` and `mcp(solar/solar_docs)`. There is no `command(*)` rule: Antigravity documents it as allowing a command inside or outside the sandbox, and `--sandbox` does nothing where the system cannot provide it, so it could run a command with no protection.
2. Tests: no `--dangerously-skip-permissions`, `--sandbox` kept, `--mode accept-edits`, the settings JSON parsed and compared with the adapter function, the JSON reaches `get_cmd` as one argument before `--print`, and a `-p`/`--print` inside the `--settings` value is not stripped.
3. The `client doctor` and `client upgrade` warnings no longer suggest the skip flag as an override (they would replace the whole command and drop the protection).
4. Documentation: the table in `docs/solar-scope-and-enforcement.md`, `routing-policy.md`, `README.md`, `CHANGELOG.md`, and the two migration/onboarding messages that suggested the skip flag as an override.

## Verified (macOS, Antigravity 1.5.1, real `HOME`, CLI run from the workspace)

| Probe | Result |
|---|---|
| Edit tool inside the workspace | ok |
| Edit tool creating a file in `$HOME` | denied (`write_file` permission cannot be prompted in headless mode); not created |
| Shell write in `$HOME` | denied (`operation not permitted`) |
| Ask the agent to retry outside the sandbox | not executed; the run stops, no file created |
| Shell write in `/tmp` | allowed |
| Shell write in `.git/hooks` and `.git/config` of a repository inside the workspace | **allowed** (unlike Codex, Claude and Cursor) |
| Edit tool (`write_file`, `edit_file`) in `.git/hooks` and `.git/config` | **allowed** (`edit_file` cannot create a file; `write_file` created it) |
| Shell and edit tool in `~/.gemini/antigravity-cli` | denied (`Matches hardcoded system protection boundary rule` for the edit tool; `operation not permitted` for the shell) |
| Network from the shell | blocked (local 403) in the measured configuration |
| `solar_search` | ok; the MCP audit log shows the call |
| Sandbox forced to fail (nested Seatbelt: `sandbox_apply: Operation not permitted`) | fails closed: command not run, no file created |

Measured with the exact command printed by the adapter, in a throwaway git repository inside the workspace. The same probes with `--dangerously-skip-permissions` (the previous default, as a Solar task): everything allowed. With `command(*)` instead of `proceed-in-sandbox`, shell commands ran in the sandbox on macOS but that rule was rejected for the risk above.

## Not in this change

- `.git/hooks` and `.git/config` stay writable with Antigravity's sandbox. Closing that is outside what Solar can set from the command line; the limit is documented in the table.
- Linux: not verified. Antigravity's documentation says `--sandbox` has no effect where unprivileged user namespaces are blocked. What must be checked there: with the sandbox unavailable, a command is refused, not run.
- A user-level `~/.gemini/antigravity-cli/settings.json` with a looser `defaultMode` or allow rules was not tried; the real one of the maintainer did not change the result.
- `mcp(solar/solar_execute)` is not allowed and was not probed.
- The edit tool is held back by a permission rule, not by the OS sandbox, as in Claude and Cursor. `/tmp` is writable, as in Codex and Cursor.
- Questions (`ask`) are unchanged: they use `--mode plan` and only the binary of the default command.

## Risks and rollback

A task that needs network from the shell, or to write in `$HOME`, now fails. `SOLAR_ROUTER_AGY_CMD` in the workspace `.env` restores the previous command (`agy --dangerously-skip-permissions --add-dir <workspace>`).

## Acceptance

- The default command keeps `--sandbox`, `--mode accept-edits` and `proceed-in-sandbox`, has no skip flag and no `command(*)` rule.
- Edit in `$HOME`, shell in `$HOME` and network from the shell are refused; `.git/hooks`, `.git/config` and `/tmp` are writable and documented as such; `solar_search` works. (Measured on 2026-11-05.)
- The new tests pass and the router suite adds no failure relative to main; the known exception is `test_cursor_project_path_matches_the_installed_cli` (#139).
