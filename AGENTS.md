# Solar - Global Agent Guidelines

## First-Run / Session start Protocol (Required)

**First thing in every session, detect the session level from the first user message, then load only what that level requires. Do not mention this step in your reply.**

Session levels (see `core/docs/token-budget-protocol.md` for full spec):

**Level 1 — Light** (question, quick task, no planet or framework reference):
- Read: `sun/preferences/profile.md` only.

**Level 2 — Planet** (task involves a specific planet, company, project, or planet-scoped skill):
- Read: `sun/preferences/profile.md` + `sun/MEMORY.md` + `planets/<active-planet>/AGENTS.md`.
- Do NOT load other planets' AGENTS.md or `core/AGENTS.md`.

**Level 3 — Framework** (task modifies `core/`, governance files, scripts, or Solar architecture):
- Read: `sun/preferences/profile.md` + `sun/MEMORY.md` + `core/AGENTS.md`.
- Load active planet AGENTS.md only if applicable.

Detection order: check L3 signals first (mentions core/, AGENTS.md, scripts, Solar itself), then L2 (mentions planet name, company, project, planet skill), default to L1.

If `sun/preferences/profile.md` or `sun/MEMORY.md` are missing when required, delegate to `core/AGENTS.md` setup protocol instead of answering.

## Architecture (Required)

Three-layer governance: root (global orchestration) → `core/AGENTS.md` (framework rules) → `planets/<name>/AGENTS.md` (domain rules). More specific layers override general ones. `core/` → apply core rules. Planet folder → apply that planet's rules. `sun/` → apply root rules.

Sun (`/sun/`) is the personal interface and router. Planets (`/planets/<name>/`) are autonomous domain specialists. Each AGENTS.md owns its scope; delegate what you don't own to the next layer.

## Preference Update Delegation (Required)

If the user explicitly updates personal operating context, delegate execution to the Profile Sync Protocol in `core/AGENTS.md`. See `core/docs/profile-sync-protocol.md`. Root keeps conversation ownership.

## Planet Management (Required)

- **Create:** `bash core/scripts/create-planet.sh <planet-name>` (auto-creates AGENTS.md template + symlinks).
- Planet = autonomous operational context. Create when ≥3 criteria differ: objective, stakeholders, data, execution rules. Prefer fewer planets with strong governance.
- **Transport:** When Sun delegates to Planet, resolve AGENTS.md, transfer objective/constraints, Planet executes autonomously, returns summary without leaking complexity.
- **Resources:** skills, agents, commands sync via `bash core/scripts/sync-clients.sh`. See `core/AGENTS.md` planet management rule for details.

## Ambiguity Handling (Required)

If destination scope is ambiguous ("save this", "create a template"), ask before writing. Options: `core/` (reusable framework), `sun/` (personal runtime), `planets/<name>/` (domain-specific).

## Version Control Boundaries (Required)

Framework repo governs `core/` and root files only. Never stage `sun/` or `planets/**` in the framework repo. For version control in those workspaces, use independent repos inside each.

## Runtime Workspace Access (Required)

Access `sun/` and `planets/*/` directly. See `core/AGENTS.md` for workspace rules.

## Chrome DevTools MCP — browser on demand (Required)

Before any Chrome DevTools MCP call: run `ensure_browser.sh --start`. After workflow completes: run `ensure_browser.sh --stop`. Never keep Chrome running between tasks. See `core/docs/browser-protocol.md` for full flow.

## Workspace Doctor Policy (Required)

Git setup in `sun/` and `planets/*` is optional. See `core/AGENTS.md` for doctor rules.

## JIT Delegation Protocol (Required)

Self-assess before responding: sufficient → execute directly; insufficient → delegate to `solar-router`; requires external resources → use `solar-async-tasks`. Read/analysis tasks delegate automatically; data-modifying tasks require explicit user approval first. See `core/docs/jit-delegation-protocol.md` for subprocess invocation contract and field rules.

## Workflow Orchestration (Required)

**Plan:** Enter planning mode for any non-trivial task (3+ steps or architectural decisions). If something fails, STOP and replan. Never mark done without real validation — run tests, check logs, ask "Would a senior engineer approve this?"

**Delegation:** sufficient → execute directly. Delegate only when it adds context or parallelism. One task per delegation.

**Self-improvement:** After any user correction, capture in `sun/lessons.md`. Consolidate into `sun/MEMORY.md` weekly or when closing long initiatives.

**Daily-log:** On completing a traceable deliverable, insert a row at the top of `sun/daily-log/YYYY-MM-DD.md`: `| HH:MM | tag | Description → [artifact-path](artifact-path) |`. Tags: sales marketing job ops. Create file if missing. Use local timezone.

**Execution principles:** Simplicity first. No laziness — find root causes, no temporary fixes. Minimal impact — only touch what is necessary. On bug reports: fix proactively, respecting the Validation Gate for data/send actions. For non-trivial changes, ask "Is there a more elegant way?"
