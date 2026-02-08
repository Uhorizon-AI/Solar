# Contributing to solar.ai

Thanks for contributing.

## Scope and Architecture

Before opening a change, align with the Solar architecture:

- `core/` is the versioned framework (contracts, templates, governance, reusable skills).
- `sun/` and `planets/` are local runtime workspaces and are gitignored by default.
- Keep `core/` reusable across users and domains.

Primary references:
- `core/AGENTS.md`
- `core/orchestration-blueprint.md`
- `core/onboarding-conversation-contract.md`

## Language Rules

- All content in `core/` must be in English.
- Planet-specific files may use the user's preferred language.

## Skills Contribution Rules

- Put a skill in `core/skills/` only when it is reusable (2+ planets or 3+ repeated uses).
- Keep planet-specific skills inside `planets/<planet-name>/`.
- Avoid external dependencies when a Solar-owned implementation is possible.

## Templates Contribution Rules

- Do not add templates by default.
- Add to `core/templates/` only when the artifact is truly cross-planet reusable.

## Workflow

1. Create a focused branch.
2. Make small, reviewable changes.
3. Update related docs/contracts when behavior changes.
4. Validate local changes.
5. Update `CHANGELOG.md` for notable changes.
6. Open a PR with clear intent, files changed, and impact.

## Pull Request Checklist

- [ ] Change matches Solar architecture boundaries (`core` vs runtime).
- [ ] `core/` changes are in English.
- [ ] No secrets or sensitive customer data are committed.
- [ ] Docs/contracts updated if behavior changed.
- [ ] `CHANGELOG.md` updated when relevant.

## Changelog Policy

This repository follows Keep a Changelog style:
- Add entries under `Unreleased` while work is in progress.
- Move entries to a versioned section at release time.
- Include only notable framework-level changes.
