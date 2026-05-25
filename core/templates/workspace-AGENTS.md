# Solar Workspace — Global Agent Guidelines

## Scope (required)

This file governs the **workspace** opened as `SOLAR_WORKSPACE`. Framework code lives in the Solar install (`SOLAR_ROOT/core/`); only `.solar/manifest.json` is maintained by Solar Client in this tree.

## `.solar/` is read-only (required)

Do **not** edit files under `.solar/`. Only Solar Client (`solar client init`, `solar client update`) modifies that tree. Extend behavior in `sun/`, `planets/`, or propose changes upstream to the Solar framework repository.

## Architecture (required)

Three layers: this file (workspace root) → `planets/<name>/AGENTS.md` (domain) → skills and runtime under `sun/`. More specific layers override general ones.

## Personal context (required)

- `sun/preferences/profile.md` — identity and working preferences
- `sun/MEMORY.md` — stable operational learnings (not logs or secrets)
- `sun/plans/` — plans and RFCs for this workspace

## Client commands (required)

```bash
solar client sync    # publish skills/agents/commands to IDEs
solar status         # compact workspace health
solar paths          # resolvable paths for @ references
solar client doctor  # integrity checks
```

## Version control (optional)

Git in this workspace is optional. Never commit `.env` or secrets. Prefer `.solar/` in `.gitignore` when using git at workspace root.
