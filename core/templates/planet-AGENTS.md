# Planet Guidelines

## Governance Delegation

**This layer (planet/AGENTS.md):**
- **Authority:** Domain-specific governance (scope, contracts, execution rules)
- **Delegates to:** `../../AGENTS.md` for global orchestration

## Scope
- Domain:
- In scope:
- Out of scope:

## Governance
- Required checks:
- Security/data rules:
- Operational limits:

## Context Sustainability

- Keep this `AGENTS.md` focused on active domain rules and routing.
- Store stable operational learnings in `MEMORY.md`, not here.
- Store historical work in plans/logs, not governance.
- Keep planet skills, agents, and commands concise; move long detail to nearby `references/`.
- Link or name canonical sources instead of duplicating long procedures.
- Prefer breadcrumbs that help Solar find detail on demand over always-loaded context.

## Chrome DevTools MCP Policy (Required when browser channels are used)

- Use shared runtime via `chrome-devtools-mcp --browserUrl` (do not require always-on Chrome).
- Agent lifecycle for browser workflows:
  1. `bash ../../core/skills/solar-browser/scripts/ensure_browser.sh --start`
  2. Reuse during the workflow.
  3. `bash ../../core/skills/solar-browser/scripts/ensure_browser.sh --stop` at natural completion.
- Safe stop semantics: block shutdown only when **other** MCP clients are active; use `--stop --force` only with explicit operational certainty.
- Never ask the user to keep Chrome/debugging on 24/7.
- Domain skills should keep browser prerequisites minimal and inherit lifecycle policy from this file + `../../AGENTS.md`.

## Code Repo Protocol (Optional)
- If this planet is a code repository, declare `solar-code` as the mandatory protocol for automated code changes.
- Set `CONTRIBUTING.md` as the repo policy file read before writing.
- Declare where task specs live, for example `docs/tasks/`.
- Keep governance split clear:
  - `AGENTS.md` = planet governance and routing rules
  - `CONTRIBUTING.md` = repo policy, checks, restrictions

## Input Contract (Sun -> Planet)
- Objective:
- Constraints:
- Context:

## Output Contract (Planet -> Sun)
- Status:
- Deliverables:
- Risks:
- Next steps:

## Planet Sync Rule (Required)

After creating or updating `agents/`, `commands/`, or `skills/`:

**1. Verify `AGENTS.md` is up to date:**
- **Agents** — Add entry if you created an agent; update description if the role changed
- **Commands** — Add entry if you created a command; update if the trigger/behavior changed
- **Skills** — Add row if you created a skill; update "when to use" if the purpose changed
- **Request Routing** (if present) — Add row if user requests should route to that resource
- **Ownership matrix** (if present) — Add row if the agent writes to a new area

**2. Sync command:**
```bash
solar client sync
```

**What it does:**
- Syncs planet resources to AI clients (`.claude/`, `.cursor/`, `.codex/`)
- Planet resources are **always prefixed** with `<planet-name>:` (e.g. `my-planet:my-skill`); only `core/` resources remain unprefixed

**When to sync:**
- After creating/editing agents, commands, or skills
- After updating `AGENTS.md`
- Before testing in new AI session

See `../../AGENTS.md` for full protocol. See `../../core/templates/planet-structure.md` for structure and examples.
