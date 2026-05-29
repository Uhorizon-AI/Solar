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

## OneDrive / multi-machine sync (required)

- **`.solar/manifest.json`** may live in a synced folder; do not edit it manually on multiple machines at once.
- **Default mode (`core_source: global`)** — secondary machines need `SOLAR_ROOT` on the same machine or network path; run `solar client update --check` then `solar client sync` only.
- **Portable mode (`core_source: workspace-snapshot`)** — opt-in via `solar client bundle create` on the **primary** machine after `solar client update`; secondary machines open the synced folder and run `solar client doctor` (no global install required).
- If the manifest has merge conflicts or invalid JSON, run `solar client update --repair` from the primary machine.
- Do not sync `.env` via cloud without encryption.

## Runtime source (`core_source`)

| Mode | Manifest | Requires `SOLAR_ROOT` | When to use |
|------|----------|----------------------|-------------|
| **global** (default) | `core_source: global` | Yes | Dev machine with framework install |
| **portable** (opt-in) | `core_source: workspace-snapshot` | No (uses `.solar/bundle/`) | OneDrive/USB secondary machines |

Do not edit `.solar/manifest.json` by hand to switch modes — use `solar client bundle create` or `solar client sync` (global).

## Version control (optional)

Git in this workspace is optional. Never commit `.env` or secrets. Prefer `.solar/` in `.gitignore` when using git at workspace root.
