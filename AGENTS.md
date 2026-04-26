# Solar - Global Agent Guidelines

## First-Run / Session start Protocol (Required)

**First thing in every session, before responding to the first user message:** read in this order:

1. **This file** (root `AGENTS.md`) in full.
2. **`sun/preferences/profile.md`** — so you know who you are talking to.
3. **`sun/MEMORY.md`** — so you have context and learnings to remember.

If `sun/preferences/profile.md` or `sun/MEMORY.md` are missing, delegate to `core/AGENTS.md` setup protocol instead of answering. Do not mention this step in your reply.

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

Goal: keep `browserUrl` shared for multi-agent stability, without keeping Chrome on all day.

**Required flow (no user prompt):**
1. Before first Chrome DevTools MCP call in a task (or after MCP connect error), run:

```bash
bash core/skills/solar-browser/scripts/ensure_browser.sh --start
```

2. Reuse the same runtime during the browser workflow (do not stop between MCP tool calls).
3. At natural completion of that browser workflow, run:

```bash
bash core/skills/solar-browser/scripts/ensure_browser.sh --stop
```

4. Never ask the user to keep Chrome/debugging running 24/7.
5. `--stop` should block only when **other** MCP clients are active (safe default assumes your current session). If blocked, do not force-close by default; use `--stop --force` only when you are sure no other active workflow should keep the shared runtime.

If sandbox blocks `ensure_browser.sh` (for example `ps: Operation not permitted`), re-run the same command with full permissions.

## Workspace Doctor Policy (Required)

Git setup in `sun/` and `planets/*` is optional. See `core/AGENTS.md` for doctor rules.

## JIT Delegation Protocol (Required)

When receiving a task, the AI must self-evaluate before responding:

### 1. Self-Assessment
Check if available agents, skills, and commands are sufficient for the task:
- **Sufficient** → execute directly.
- **Insufficient or uncertain** → delegate to `solar-router` as a subprocess.
- **Requires external resources** (internet, system binaries, MCPs, long-running operations) → create an async task via `solar-async-tasks` (create → plan → approve → queue). The system executes it automatically via the Solar LaunchAgent. Do NOT run `run_worker.sh` manually or attempt direct execution.

### 2. Validation Gate
Before delegating to `solar-router`:
- Task is **read / analysis only** → delegate automatically.
- Task **modifies data or sends messages** → show the user which agent + skills will be used and wait for explicit approval before proceeding.

### 3. Subprocess Invocation
Call `solar-router` using the v3 contract via stdin. Always use `mode: direct_only` and `channel: other` in subprocesses to prevent recursion:

```bash
echo '{
  "request_id": "<uuid>",
  "session_id": "<session_id>",
  "user_id": "<user_id>",
  "text": "<task description>",
  "channel": "other",
  "mode": "direct_only",
  "provider": "<claude|gemini|codex>",
  "metadata": {
    "agent": "<agent-name or null>",
    "skills": ["<skill-1>", "<skill-2>"],
    "planet": "<planet-name>"
  }
}' | python3 core/skills/solar-router/scripts/run_router.py
```

For full field rules, JIT protocol, metadata format, and invariants see `core/skills/solar-router/references/routing-policy.md`.

### 4. When No Agent or Skill Exists
Set `metadata.agent` to `null` — the router generates a role JIT. Frequently used JIT resources are persisted to the correct planet and synced via `sync-clients.sh`.

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
