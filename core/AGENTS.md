# Core Governance

## Purpose
`core/` is the versioned framework layer of Solar.ai.
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

## Local-first policy
- `sun/` and `planets/` are local runtime workspaces and are gitignored by default.
- The framework repository must stay clean and reusable for multiple users.

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

## Runtime interaction ownership
- First-run conversational behavior is owned by root `AGENTS.md`.
- Keep `core/AGENTS.md` focused on framework governance only.

## Core self-management rule (required)
- `core/` must be operated autonomously by the agent.
- The agent may execute any repository script under `core/**` when needed by the active workflow, including scripts inside skills (`core/skills/**/scripts/*`) and shared scripts.
- Script execution should follow skill trigger logic from `SKILL.md` frontmatter (`name` + `description`) and the skill body workflow.
- Do not ask non-technical users to run `bash ...` manually for normal `core/` operations.
- Ask users only for required inputs/secrets, blocked permissions, or high-risk actions.

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
