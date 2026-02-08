# Core Governance

## Purpose
`core/` is the versioned framework layer of Solar.ai.
It defines contracts, templates, and operational rules shared by all users.

## What belongs in core
- Transport and reporting contracts.
- Onboarding conversation contract.
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
