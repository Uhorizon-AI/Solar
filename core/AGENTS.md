# Core Governance

## Purpose
`core/` is the versioned framework layer of Solar.
It defines contracts, templates, and operational rules shared by all users.

## What belongs in core
- Transport and reporting contracts.
- Onboarding conversation contract.
- Orchestration blueprint.
- Cross-planet reusable skills.
- Reusable templates for onboarding and planets.
- Bootstrap and maintenance scripts.
- Documentation about architecture and governance.

## What does NOT belong in core
- User-specific memory or preferences.
- Runtime task history.
- Sensitive business data from a specific planet.
- User-specific execution artifacts (for example: migration maps, audit snapshots, temporary plans).

## Local-first policy
- `sun/` and `planets/` are local runtime workspaces, must remain outside framework governance, and must stay ignored by the parent framework repo.
- The framework repository must stay clean and reusable for multiple users.
- Never propose tracking `sun/` or `planets/` in the parent framework repository.

## Scope ownership model (required)
- `core/` is multi-user and reusable by design.
- `sun/` is user-specific runtime context and outputs.
- `planets/<planet-name>/` is project/company/workspace-specific context and outputs.
- Never store user-specific execution artifacts in `core/`.

## Change rules
1. Keep changes backward-compatible when possible.
2. Update docs/checklists when contracts or templates change.
3. Prefer small, reviewable commits with explicit intent.
4. Do not commit secrets or personal data.

## Onboarding order (required)
1. Identity handshake.
2. User operating preferences.
3. Baseline context.
4. Planet creation and governance.

## Onboarding interaction rule (required)
- Use `core/onboarding-conversation-contract.md`.
- Ask one question per turn.
- Accept corrections at any moment and continue from the updated state.
- Show a pre-planet summary and ask explicit confirmation before creating any planet.

## Orchestration rule (required)
- Use `core/orchestration-blueprint.md` for routing, execution, reporting, and persistence.

## Template policy (required)
- Do not create a template for every new artifact.
- Create a new file in `core/templates/` only if:
  1. It will be reused at least 3 times, or
  2. It is needed by 2 or more planets.
- If an artifact is specific to one planet, keep it inside that planet workspace.
- Keep `core/templates/` small, stable, and cross-planet by design.

## Language policy (required)
- Everything in `core/` must be written in English for cross-user reuse.
- Planet-specific files may use the user's preferred language.
- Planet skills may use the user's preferred language.

## Documentation scope policy (required)
- `core/docs/` and `core/*/docs/` are for **framework documentation only**:
  - Architecture, contracts, API reference
  - How-to guides for framework features
  - Shared templates and blueprints
- User-specific documentation belongs in `sun/`:
  - `sun/docs/` for general user documentation
  - `sun/plans/` for implementation plans and design decisions
  - `sun/runtime/*/` for execution artifacts
- When creating design docs or plans for user-specific extensions, default to `sun/plans/` unless the change is meant to be contributed back to core framework.

## Memory protocol (required)
- Solar uses **AI-agnostic memory** stored in the filesystem, accessible by any AI (Claude, Gemini, etc.).
- Memory structure:
  - **`sun/MEMORY.md`** (required): Global operational learnings, cross-planet patterns, common pitfalls.
  - **`planets/<planet-name>/MEMORY.md`** (optional): Domain-specific learnings, project patterns, business context.
  - **Topic files** (optional): `debugging.md`, `patterns.md`, etc. for detailed notes (link from MEMORY.md).
- **Purpose** (CRITICAL):
  - MEMORY.md is for **operational learnings**, NOT configuration.
  - Configuration goes in: `AGENTS.md`, `sun/preferences/profile.md`.
  - `sun/MEMORY.md` is always created (bootstrap), planets create MEMORY.md only when domain is complex.
- **Concision rules**:
  - **`sun/MEMORY.md`**: Max 200 lines (truncated after). Keep concise.
  - **`planets/*/MEMORY.md`**: Max 100 lines per planet.
  - **Free-form structure**: Semantic, not chronological. No forced sections.
  - **Only stable patterns** confirmed across multiple interactions.
  - **Eliminate outdated** info when updating.
  - **Prioritize "what to do"** over "what happened".
- **When to update memory**:
  - When discovering recurring operational patterns.
  - When fixing mistakes that could be common.
  - When making architectural decisions during work.
  - When learning domain-specific context not captured in AGENTS.md.
- **First-run protocol**: On first interaction, silently read `sun/MEMORY.md`. If missing, delegate to setup protocol.

## Runtime interaction ownership
- First-run trigger and user-facing conversation are owned by root `AGENTS.md`.
- `core/AGENTS.md` defines setup execution rules only when root delegates.

## Governance delegation rule (required)

**This layer (core/AGENTS.md):**
- **Authority:** Framework operational rules (sync, templates, onboarding, validation)
- **Called by:** Root `AGENTS.md` for framework operations

**Key principle:** Core owns framework operations. Root owns global orchestration.

## Setup Protocol

This protocol is invoked by root `AGENTS.md` when `sun/MEMORY.md` or `sun/preferences/profile.md` are missing.

**Setup menu:**
1. `Configure now (Recommended)`
2. `I already configured it`
3. `Show help`

**Execution:**
- **Option 1:** Run `bash core/bootstrap.sh`, confirm completion, then start onboarding
- **Option 2:** Re-attempt to read `sun/preferences/profile.md`; if still missing, offer option 1 again
- **Option 3:** Explain what setup does and why it is needed

**Post-setup handoff:**
- Onboarding conversation remains governed by root `AGENTS.md`
- Apply `core/onboarding-conversation-contract.md` as the detailed conversation contract

## Core self-management rule (required)
- `core/` must be operated autonomously by the agent.
- The agent may execute any repository script under `core/**` when needed by the active workflow, including scripts inside skills (`core/skills/**/scripts/*`) and shared scripts.
- Script execution should follow skill trigger logic from `SKILL.md` frontmatter (`name` + `description`) and the skill body workflow.
- Do not ask non-technical users to run `bash ...` manually for normal `core/` operations.
- Ask users only for required inputs/secrets, blocked permissions, or high-risk actions.

## Workspace doctor execution policy (required)
- Default doctor runs are on-demand; do not run workspace doctors automatically unless requested by the user or explicitly required by the active task.
- Git checks in workspace doctors are optional and must be opt-in:
  - `bash core/scripts/sun-workspace-doctor.sh --check-git`
  - `bash core/scripts/planets-workspace-doctor.sh --check-git`
- Do not treat missing `.git` in `sun/` or `planets/*` as a blocking issue unless git validation was explicitly requested.

## Environment block policy (required)
- Any skill in `core/` that reads/writes `.env` must use a compact, skill-scoped block format.
- Each skill block must start with a header comment identifying the skill (example: `# [solar-telegram] required environment`).
- Variables for the same skill must be grouped contiguously with no blank lines inside the block.
- Scripts must preserve existing values unless user explicitly requests overwrite.
- New env-aware skills must follow this format from their first version.

## Host availability note policy (required)
- Apply this policy only to skills that expose long-running local runtime endpoints (for example: webhook, bridge, local server, tunnel).
- Those skills must include a short `Laptop runtime note` in their `SKILL.md`:
  - host sleep can stop the runtime,
  - this is an operational host concern (not a mandatory skill dependency),
  - if multiple laptops are used, only the active host should serve the same public route.
- Do not add this note to skills that are not runtime-host dependent.

## Planet management rule (required)
- Use `bash core/scripts/create-planet.sh <planet-name>` to create new planets (auto-creates AGENTS.md template + CLAUDE.md/GEMINI.md symlinks).
- Consult `core/templates/planet-structure.md` for planet structure reference, resource creation workflows, and sync best practices.
- When creating or modifying resources in `planets/*/skills/`, `planets/*/agents/`, or `planets/*/commands/`:
  - Run `bash core/scripts/sync-clients.sh` to sync planet resources to AI clients.
  - Planet resources are automatically discovered and merged with `core/` resources.
  - All planet resources are prefixed deterministically: `<planet-name>:<resource-name>` (only `core/` resources remain unprefixed).

## Client sync rule (required)
- If files are added or modified in `core/skills/`, `core/agents/`, or `core/commands/`, run:
  - `bash core/scripts/sync-clients.sh`
- This sync must be executed before considering the change operationally complete.

## Skill validation rule (required)
- If a specific skill under `core/skills/` is modified, validate that skill before considering the change complete.
- Validation command:
  - `python3 core/skills/solar-skill-creator/scripts/package_skill.py <skill-path> /tmp`
- Do not use `--no-validate` in normal flow.
- This rule is per-skill (only the skill being modified), not repository-wide.
