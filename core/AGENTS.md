# Core Governance

## Scope (required)

`core/` is the versioned, multi-user framework layer. It owns: contracts, templates, shared skills, bootstrap scripts, and framework docs. `sun/` and `planets/` are user-owned runtime workspaces — never track them in the framework repo, never store user-specific artifacts in `core/`. Changes to `core/` must be backward-compatible, use small reviewable commits, and never include secrets or personal data.

## Docs scope (required)

`core/docs/` is for framework reference only (architecture, contracts, protocols). User-specific plans and design docs go in `sun/plans/`. When in doubt, default to `sun/plans/` unless the artifact is meant for multi-user reuse.

## Onboarding (required)

Order: identity handshake → user preferences → baseline context → planet creation. Use `core/onboarding-conversation-contract.md`: one question per turn, accept corrections at any moment, confirm before creating any planet. Use `core/orchestration-blueprint.md` for routing, execution, reporting, and persistence.

## Template policy (required)

Create a file in `core/templates/` only if it will be reused ≥3 times or needed by ≥2 planets. Keep templates small, stable, and cross-planet.

## Language policy (required)

Everything in `core/` must be in English. Planet-specific files and skills may use the user's preferred language.

## Memory protocol (required)

Solar uses AI-agnostic filesystem memory accessible by any AI client.
- `sun/MEMORY.md` (required, max 200 lines): global operational learnings and cross-planet patterns.
- `planets/<name>/MEMORY.md` (optional, max 100 lines): domain-specific learnings.
- MEMORY.md is for **operational learnings only** — not configuration, not identity data. Identity data belongs exclusively in `sun/preferences/profile.md`.
- Free-form structure. Only stable, confirmed patterns. Eliminate outdated info. Prioritize "what to do" over "what happened".
- Update when discovering recurring patterns, fixing repeatable mistakes, or making architectural decisions.
- **First-run:** load `sun/MEMORY.md` only at L2 or L3 session level. See `core/docs/token-budget-protocol.md`. If missing when required, delegate to setup protocol.

## Runtime interaction ownership (required)

First-run trigger and user-facing conversation are owned by root `AGENTS.md`. `core/AGENTS.md` defines setup and sync execution rules only when root delegates.

## Profile Sync Protocol (required)

Invoked when root detects an explicit user update to personal operating context. Update `sun/preferences/profile.md` first, then `sun/MEMORY.md` only if a stable operational pattern emerges. Confirm changes back to the user. See `core/docs/profile-sync-protocol.md` for full steps and guardrails.

## Setup Protocol (required)

Invoked when `sun/MEMORY.md` or `sun/preferences/profile.md` are missing. Offer three options: configure now (`bash core/bootstrap.sh`), already configured (re-read profile), or show help. See `core/docs/setup-protocol.md` for full menu and post-setup handoff.

## Core self-management rule (required)

`core/` must be operated autonomously. The agent may execute any script under `core/**` when needed by the active workflow. Do not ask non-technical users to run bash commands for normal `core/` operations — ask only for required secrets, blocked permissions, or high-risk actions.

## Workspace doctor policy (required)

Doctor runs are on-demand only. Git checks are opt-in: `bash core/scripts/sun-workspace-doctor.sh --check-git`. Missing `.git` in `sun/` or `planets/*` is not a blocking issue unless git validation was explicitly requested.

## Environment block policy (required)

Skills in `core/` that read/write `.env` must use a compact skill-scoped block: header comment identifying the skill, variables grouped contiguously with no blank lines inside the block, preserve existing values unless user requests overwrite.

## Host availability note policy (required)

Skills that expose long-running local endpoints must include a short `Laptop runtime note` in their SKILL.md: host sleep can stop the runtime; only the active host should serve the same public route. Do not add this note to skills that are not runtime-host dependent.

## Planet management rule (required)

- Create planets: `bash core/scripts/create-planet.sh <planet-name>` (AGENTS.md template + CLAUDE.md/GEMINI.md symlinks).
- See `core/templates/planet-structure.md` for structure reference and sync best practices.
- After adding or modifying resources in `planets/*/skills/`, `planets/*/agents/`, or `planets/*/commands/`, run `bash core/scripts/sync-clients.sh`. Planet resources are prefixed `<planet-name>:<resource-name>`; only `core/` resources remain unprefixed.

## Client sync rule (required)

After any change to `core/skills/`, `core/agents/`, or `core/commands/`, run `bash core/scripts/sync-clients.sh` before considering the change complete.

## Changelog policy (required)

Root `CHANGELOG.md` is for Solar framework-level changes only (`core/`, root config, shared protocols). Never include planet-specific logic or `sun/` context. Planet-specific changes go in the planet's own workspace.

## Skill governance rule (required)

All changes to `core/skills/` are governed by `solar-skill-creator`, not `solar-code`. `solar-code` applies exclusively to planet repos.

## Skill validation rule (required)

After modifying any skill under `core/skills/`, validate before marking complete:
`python3 core/skills/solar-skill-creator/scripts/package_skill.py <skill-path> /tmp`. Do not use `--no-validate` in normal flow.

## Core skills tests policy (required)

Do not add `tests/` inside `core/skills/<name>/` — keep skill packages lean. Add tests under `core/tests/skills/<skill-name>/` using `unittest` or `pytest`. Each test folder may include a `conftest.py` to add the skill's scripts to `sys.path`. Run tests before considering a skill change complete: `uv run --project core/tests pytest core/tests/skills/<skill-name> -q`.
