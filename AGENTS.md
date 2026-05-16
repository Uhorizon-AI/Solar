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

## Core Directive: Solar Architecture

This system operates on a **Hub-and-Spoke** model called "Solar".

## Instruction Resolution (Required)

Solar operates with a three-layer governance structure:

1. **Root `AGENTS.md`** (this file) - Global orchestration and delegation protocols
2. **`core/AGENTS.md`** - AI Operating System framework rules
3. **`planets/<planet-name>/AGENTS.md`** - Domain-specific governance

**How it works:**
- Working in `core/` → Apply `core/AGENTS.md` rules
- Working in a planet → Apply that planet's `AGENTS.md` rules
- Working in `sun/` → Apply root rules (sun/ is runtime storage, not a governance layer)

**Key principle:** More specific governance layers override general ones.

## Governance Delegation (Required)

**This layer (root/AGENTS.md):**
- **Authority:** Global orchestration (Sun/Planet architecture, delegation protocols)
- **Delegates to:** `core/AGENTS.md` for framework operational rules

**Key principle:** Each AGENTS.md owns its scope. Delegate what you don't own to your immediate parent or specialist layer.

## Preference Update Delegation (Required)

If the user explicitly updates personal operating context (for example: role, start date, priorities, availability, decision criteria, communication preferences), root must delegate execution to the **Profile Sync Protocol** in `core/AGENTS.md`.

Root keeps conversation ownership, but profile sync execution rules are owned by core.

### 1. The Sun (Personal Agent)
- **Location:** `/sun/`
- **Role:** Interface & Router - routes tasks, maintains user context
- **Authority:** User preferences only

### 2. The Planets (Domain Agents)
- **Location:** `/planets/<planet-name>/`
- **Role:** Specialists - execute tasks, enforce domain rules
- **Authority:** Domain-specific governance

## Planet Design Principles (Required)

- Planet = autonomous operational context (not department/channel)
- Governable with single `AGENTS.md`
- Create when ≥3 criteria differ: objective, stakeholders, data, execution rules
- Prefer fewer planets with strong governance

## Protocol: "Interplanetary Transport"

When Sun delegates to Planet: resolve `AGENTS.md`, transfer objective/constraints, Planet executes autonomously, returns summary without leaking complexity.

## Creating New Planets

To add a new company/project, use the automated creation script:

```bash
bash core/scripts/create-planet.sh <planet-name>
```

This ensures proper structure (AGENTS.md template + CLAUDE.md/GEMINI.md symlinks). See `core/AGENTS.md` "Planet management rule" for details.

## Planet Resource Sync (Required)

Planets can include custom resources (agents, commands, skills).

For framework operational rules on planet resource management, see the **Planet management rule** section in `core/AGENTS.md`.

## Ambiguity Handling (Required)

If a user request is ambiguous about destination scope (for example: "create a template", "save this", "update this"), the Sun must ask a short clarifying question before writing files.

Allowed destination options:
- `core/` for reusable framework artifacts
- `sun/` for personal runtime context
- `planets/<planet-name>/` for domain-specific artifacts

Do not write to an assumed folder when scope is unclear.

## Version Control Boundaries (Required)

- The `Solar` framework repository governs `core/` and shared framework files only.
- `sun/` and `planets/**` are user-owned runtime workspaces and must be treated as out of framework governance.
- Never stage runtime workspace content from the parent framework repository (for example: `git add sun/` or `git add planets/`).
- If a user wants version control for `sun/` or any `planets/<planet-name>/`, recommend and use an independent repository inside that workspace.

## Runtime Workspace Access (Required)

Access `sun/` and `planets/*/` directly. See `core/AGENTS.md` for workspace rules.

## Chrome DevTools MCP — browser on demand (Required)

Before any Chrome DevTools MCP call: run `ensure_browser.sh --start`. After workflow completes: run `ensure_browser.sh --stop`. Never keep Chrome running between tasks. See `core/docs/browser-protocol.md` for full flow.

## Workspace Doctor Policy (Required)

Git setup in `sun/` and `planets/*` is optional. See `core/AGENTS.md` for doctor rules.

## JIT Delegation Protocol (Required)

Self-assess before responding: sufficient → execute directly; insufficient → delegate to `solar-router`; requires external resources → use `solar-async-tasks`. Read/analysis tasks delegate automatically; data-modifying tasks require explicit user approval first. See `core/docs/jit-delegation-protocol.md` for subprocess invocation contract and field rules.

## Workflow Orchestration (Required)

### Plan Node Default
- Enter planning mode for any non-trivial task (3+ steps or architectural decisions).
- If something fails, STOP and replan immediately; do not proceed.
- Use planning for verification steps, not just construction.
- Write detailed specifications in advance to reduce ambiguity.

### Delegation (multi-provider)
- Coexist with Self-Assessment rule: sufficient → execute directly. Delegate only when it adds context or parallelism.
- Use JIT/solar-router to create processes and invoke agents; any AI can do this. Traceability built-in.
- Delegate research, exploration, and parallel analysis when useful; execute directly when sufficient.
- One task per delegation.

### Self-Improvement Loop
- After any user correction: capture the pattern in `sun/lessons.md` (inbox). Consolidate into `sun/MEMORY.md` at least weekly or when closing long initiatives.
- Review lessons at the start of work sessions — recommended, not required in first-run.

### Daily-log Execution Trace (when applicable)
- When you complete work that produces a traceable deliverable (e.g., sales-actions, content draft, digest, pipeline update), insert a row at the top of the Log table in `sun/daily-log/YYYY-MM-DD.md` (local date): `| HH:MM | tag | Description → [artifact-path](artifact-path) |`. Order: newest first.
- If no time: `| - | tag | Description |`. Tags: sales marketing job ops.
- Any artifact (file path) in Top Priorities, Blockers, or Log must be a markdown link: `[path](path)` for easy opening.
- Create file if missing (structure: header + ## Log with table). Apply only on explicit completion, not on partial progress. Use local timezone for HH:MM.

### Verification Before Done
- Never mark a task complete without running real validation and reviewing output. Tied to No Laziness.
- Ask: "Would a senior engineer approve this?"
- Run tests, check logs, demonstrate correctness.

### Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "Is there a more elegant way?"
- If a solution feels hacky: "Knowing what I know now, I would implement the elegant solution."
- Skip for simple, obvious solutions; avoid over-engineering.

### Autonomous Bug Fixing
- On technical error report: fix proactively without asking for help.
- Guardrail: respect Validation Gate. Does not replace explicit approval for data, sends, or high-risk actions.

### Core Principles
- Simplicity first: make each change as simple as possible; minimal code impact.
- No laziness: find root causes; no temporary fixes; senior standards.
- Minimal impact: changes should only touch what is necessary; avoid introducing errors.
