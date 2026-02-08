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
