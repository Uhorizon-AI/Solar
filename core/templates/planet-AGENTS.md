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
bash ../../core/scripts/sync-clients.sh
```

**What it does:**
- Syncs planet resources to AI clients (`.claude/`, `.cursor/`, `.codex/`)
- Planet resources are **always prefixed** with `<planet-name>:` (e.g. `my-planet:my-skill`); only `core/` resources remain unprefixed

**When to sync:**
- After creating/editing agents, commands, or skills
- After updating `AGENTS.md`
- Before testing in new AI session

See `../../AGENTS.md` for full protocol. See `../../core/templates/planet-structure.md` for structure and examples.
