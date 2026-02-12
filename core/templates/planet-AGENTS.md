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

## Planet Sync Rule

This planet supports custom resources (agents, commands, skills).

For planet resource creation and sync protocols, see the **Planet management rule** section in `../../AGENTS.md` (root governance).

Quick reference:
- Run `bash ../../core/scripts/sync-clients.sh` after creating/updating resources
- See `../../core/templates/planet-structure.md` for detailed structure and examples
- Name conflicts are resolved with npm-style prefixing: `<planet-name>:<resource-name>`
