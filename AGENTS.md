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

## Workspace Doctor Policy (Required)

Git setup in `sun/` and `planets/*` is optional. See `core/AGENTS.md` for doctor rules.

## JIT Delegation Protocol (Required)

When receiving a task, the AI must self-evaluate before responding:

### 1. Self-Assessment
Check if available agents, skills, and commands are sufficient for the task:
- **Sufficient** → execute directly.
- **Insufficient or uncertain** → delegate to `solar-router` as a subprocess.

### 2. Validation Gate
Before delegating to `solar-router`:
- Task is **read / analysis only** → delegate automatically.
- Task **modifies data or sends messages** → show the user which agent + skills will be used and wait for explicit approval before proceeding.

### 3. Subprocess Invocation
Call `solar-router` using the v3 contract via stdin:

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

**Field rules:**
- `provider`: specify the best LLM for the task. Omit to let the router use its priority order.
- `mode`: always `direct_only` in subprocess calls to prevent recursion.
- `metadata.agent`: use an existing agent from the planet's `agents/` if one fits, otherwise `null` (router creates JIT).
- `metadata.skills`: list relevant skills available in the planet or `core/`.
- `metadata.planet`: the planet that owns this task's domain.

### 4. When No Agent or Skill Exists
If no matching agent or skill exists, `solar-router` will generate one JIT to resolve the task. Frequently used JIT resources will be persisted to the correct planet and synced to all AI clients via `sync-clients.sh`.
