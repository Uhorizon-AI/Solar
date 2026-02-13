# Contributing to Solar

Thanks for helping improve Solar.

## Contribution Goals

Solar is an open-source project maintained by Uhorizon AI. We welcome:

- Bug fixes.
- Documentation improvements.
- Reusable framework improvements.
- New ideas discussed through issues before implementation.

## Scope Boundaries

Solar follows strict architecture boundaries:

- `core/` is versioned framework code and documentation.
- `sun/` and `planets/` are user runtime workspaces and are gitignored.
- Contributions in this repository should focus on `core/` and shared files.

Primary references:
- `AGENTS.md`
- `core/AGENTS.md`
- `core/orchestration-blueprint.md`

## Language Policy

- `core/` content must be in English.
- Runtime/planet-specific content can follow user language preferences outside framework scope.

## Before You Start

1. Check if an issue already exists.
2. Open an issue for non-trivial changes.
3. Confirm design alignment before large PRs.

## Branch and Commit Workflow

1. Create a focused branch from `main`.
2. Keep changes small and reviewable.
3. Use clear commit messages describing intent and impact.
4. Update docs/contracts when behavior changes.
5. Update `CHANGELOG.md` for notable framework changes.

## Pull Request Requirements

Each PR should include:

- Problem statement.
- Scope and files changed.
- Behavior impact.
- Validation steps performed.

Checklist:
- [ ] Scope matches Solar boundaries.
- [ ] `core/` updates are in English.
- [ ] No secrets or private user data.
- [ ] Documentation updated when needed.
- [ ] `CHANGELOG.md` updated when relevant.

## Creating a Release

**Maintainers only:** Solar uses semantic versioning for framework releases.

To create a release:
```bash
bash core/scripts/create-release.sh [--push]
```

The script will:
1. Analyze commits since last release (using Conventional Commits)
2. Propose a version bump (MAJOR/MINOR/PATCH)
3. Generate CHANGELOG.md entry
4. Ask for confirmation
5. Create tag and commit (push with --push flag)

**Commit message format:**
- `feat(scope): description` → MINOR version bump
- `fix(scope): description` → PATCH version bump
- `feat(scope)!: description` or `BREAKING CHANGE:` → MAJOR version bump

See [core/commands/solar-create-release.md](core/commands/solar-create-release.md) for full details.

## Skill and Template Rules

- Add a skill to `core/skills/` only if reusable across domains.
- Keep domain-specific logic out of framework scope.
- Add templates only when they are clearly cross-domain reusable.

## Review Expectations

Maintainers prioritize:

- Correctness and architecture alignment.
- Backward compatibility of contracts.
- Security and privacy safety.
- Clarity of documentation.

## Code of Conduct and Security

- Community behavior rules: [`./CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- Security reporting process: [`./SECURITY.md`](./SECURITY.md)
