---
review_pass: pending
design_frozen: false
last_review: none
---

# Task spec: launch each client with its own sandbox on

**Date:** 2026-11-05
**Status:** implemented on branch `feat/respect-native-cli-sandbox`; Antigravity not verified; independent reviews pending
**Base:** `c861306` (main)
**Issues:** #133. This replaces the design of confining the worker with a Solar-owned profile (`sandbox-exec` on macOS, `bwrap` on Linux).

## Outcome

Solar starts a task as a terminal would start the client: real `HOME`, real login, the workspace as the working folder, and the client's own sandbox turned on. Solar does not add a profile, a private `HOME` or copied credentials, and it does not need a per-client matrix of where each client keeps its state.

## Why the Solar-owned confinement was dropped

A dry run on macOS (Codex 0.165, Claude 2.1.318, Cursor `agent` 2026.10.22) showed the Solar profile worked, but each client needed its own treatment of `HOME` and credentials: Claude loses its login with a private `HOME` (the credential is in the keychain), Codex needs a writable private `CODEX_HOME` with a copied `auth.json`, Cursor needs a private `HOME`, short paths and a prepared credential, and Antigravity asked to log in again. The Solar MCP could not write its audit log inside the profile. Three independent opinions (one per client) reached the same view: keep the clients' own limits instead of replacing them.

## Verified baseline

Same conditions for every row: real `HOME`, a throwaway git workspace, writes attempted from the client's shell and from its edit tools.

| Behavior | Codex `workspace-write`, approvals `never` | Claude `acceptEdits` + `sandbox.enabled` | Cursor `--sandbox enabled`, no `-f` |
|---|---|---|---|
| Write `AGENTS.md`, `skills/`, `.solar/` inside the workspace | allowed | allowed | allowed |
| Write `.git/hooks`, `.git/config` | denied | denied | denied |
| Write outside the workspace (shell and edit tools) | denied | denied | denied |
| Network from the shell | denied | denied; domain list possible | denied; `.cursor/sandbox.json` list possible |
| Own folder (`.codex/`, `.claude/settings.json` and `skills`, `.cursor/mcp.json`) | protected | protected | protected |
| Another client's folder | writable | writable | writable (`.claude/settings.json` was also denied) |
| Hard link in the workspace to an outside file | writes the outside file | same | same |
| Symlink to an outside file | denied | denied | denied |
| Solar MCP (`solar_search`, `solar_docs`) | works | works with `mcp__solar` allowed | works with `--approve-mcps` |
| Start Chrome or run `ps` from the shell | fails | fails | fails |

What the previous defaults did: Claude ran with `bypassPermissions`, where Write and Edit created and edited files outside the workspace (the shell sandbox only covers the shell); Cursor ran with `-f`, which ran all nine probe writes, including the network call, outside its sandbox. Codex already used `--sandbox workspace-write`.

## Changes

1. `providers/claude.py`: the default command is `claude -p --permission-mode acceptEdits --settings <json> --no-session-persistence`. The settings enable `sandbox.enabled`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands: false` and `failIfUnavailable: true` (without it, Claude on Linux without `bubblewrap` or `socat` only warns and runs the shell unconfined), and allow `mcp__solar`, `WebSearch`, `WebFetch` and reading the framework root (a headless run cannot ask for them). The streaming path now builds the same command as the blocking path.
2. `providers/agent.py`: the default command drops `-f` and adds `--sandbox enabled`.
3. `diagnose_router.sh --dry-run` asks each adapter for its default command instead of keeping its own copy, so the diagnosis cannot drift again.
4. Documentation: new section "How Solar launches each client for a task" in `docs/solar-scope-and-enforcement.md` (the source for claims about control), plus `README.md`, `solar-router/SKILL.md`, `references/routing-policy.md` (its Codex line still named the removed `--full-auto`), `diagnose_router.sh` and `core/docs/execution-reservations.md`.
5. Tests: the launch tests assert the sandbox flags and the absence of `bypassPermissions`, `-f`, `--force`, `--yolo`; the sandbox settings are parsed back from the command; `stream()` is run against a simulated `Popen` and its command is compared with the blocking one; the framework read rule is pinned as `Read(//<root>/**)`; an env override still replaces the whole command.

## Not in this change

- Codex keeps its current command. Its `approval_policy` is not forced to `never` for tasks; an automatic approvals reviewer in the user's config can still escalate. That needs its own measurement because tasks may rely on it.
- Antigravity keeps `--dangerously-skip-permissions`. Its account quota was exhausted when this was measured (about 76 hours), so its `--sandbox` flag is not verified. The documentation tells the reader to treat it as unprotected.
- `task.authorize_run` is unchanged: a task is not exempted from approval because a client sandbox is on.
- The hard-link gap is documented, not closed. Closing it needs a check of link counts before a task starts.
- No Linux run: the sandboxes were measured on macOS only. Pending on the VPS: that Claude refuses to start without `bubblewrap`/`socat` and the router shows the cause, and Cursor's exact command (`agent -p --sandbox enabled --approve-mcps --trust --workspace <root>`, version 2026.10.22 measured) applying an in-workspace edit on disk and denying one outside. Cursor's documentation says a non-interactive run without `--force` only proposes edits; on macOS 2026.10.22 they were applied.
- Measured with Codex `approval_policy = "never"` and without extra allow rules in the user's settings. Claude keeps the user's `Edit(...)` rules and `additionalDirectories`, and Codex tasks inherit the user's approval policy.

## Risks and how to roll back

- A task that needs network from the shell, or that edits outside the workspace, now fails in Claude and Cursor. The fix is the client's own allow list (Claude `sandbox.network.allowedDomains`, Cursor `.cursor/sandbox.json`), or `SOLAR_ROUTER_CLAUDE_CMD` / `SOLAR_ROUTER_AGENT_CMD` with the previous command.
- Any other MCP server a task uses with Claude must be allowed in the client's settings; only `solar` is allowed by default.
- Chrome has to be started before the task (`ensure_browser.sh --start`); a shell inside the sandbox cannot start it.

## Acceptance

- The default commands contain the sandbox flags and none of `bypassPermissions`, `-f`, `--force`, `--yolo`.
- With the default Claude command in a throwaway workspace: Write inside the workspace works; Write and shell writes outside are refused; `solar_search` works; reading the framework root works. (Measured on 2026-11-05.)
- The full `core/tests` suite passes.
