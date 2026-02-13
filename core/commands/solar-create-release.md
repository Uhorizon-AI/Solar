---
name: solar-create-release
description: Create a new Solar framework release with semantic versioning
---

# Solar Release Creation

Interactive command to create framework releases with automatic version calculation and changelog generation.

## Usage

```bash
bash core/scripts/create-release.sh [--push]
```

**Options:**
- `--push`: Automatically push tag and commit to remote after creation (optional)

**When to use:**
- After completing 2-3 significant framework features
- Before starting new major development (to establish baseline)
- When framework changes are ready for distribution

---

## Release Flow

### 1. Pre-flight Checks

The script validates:
- [ ] Working tree is clean (no uncommitted changes)
- [ ] Currently on `main` branch
- [ ] At least one commit since last release
- [ ] Previous release tag exists (or creates v0.1.0 for first release)

### 2. Commit Analysis

Analyzes commits since last tag using Conventional Commits:

```
📊 Analyzing commits since v0.1.0...
   - 3 feat commits  → MINOR bump
   - 2 fix commits   → PATCH bump
   - 0 BREAKING      → no MAJOR
```

**Bump precedence:**
- `MAJOR` (vX.0.0): Breaking changes (`type!` or `BREAKING CHANGE:` footer)
- `MINOR` (v0.X.0): New features (`feat:`) without breaking changes
- `PATCH` (v0.0.X): Bug fixes (`fix:`) or compatible changes

### 3. Human Confirmation Gate

```
📌 Proposed version: v0.2.0

CHANGELOG preview:
## [0.2.0] - 2026-02-13

### Added
- feat(memory): add AI-agnostic MEMORY.md protocol
- feat(release): add release infrastructure

### Fixed
- fix(doctor): validate MEMORY.md (uppercase)

Do you want to create this release? [y/N]:
```

**Single decision point:** Accept (`y`) or reject (`N`).

### 4. Automated Execution (if confirmed)

If you confirm, script executes all steps automatically:

```
✅ Creating release v0.2.0...
  1. Updating CHANGELOG.md...           ✅
  2. Creating git tag v0.2.0...         ✅
  3. Committing changes...              ✅
  4. Done! (push manually or use --push)

🎉 Release v0.2.0 created successfully!

Next steps:
- git push origin main --tags  (if not using --push flag)
- GitHub will auto-create release from tag (if configured)
```

---

## What Gets Modified

**Files updated:**
- `CHANGELOG.md` - New version entry prepended
- `.git/refs/tags/` - New git tag created

**Git operations:**
- Commit: `chore(release): vX.Y.Z`
- Tag: `vX.Y.Z`
- Push: Only if `--push` flag used

**NOT modified:**
- No VERSION file (Solar uses git tags as source of truth)
- No package.json or similar (Solar is not a package)

---

## Versioning Scope

**Framework only** (bumps version):
- `core/` (skills, scripts, templates, governance)
- Root files (`AGENTS.md`, `CHANGELOG.md`, `README.md`, `CONTRIBUTING.md`)

**Runtime excluded** (no version bump):
- `sun/` (user-specific runtime)
- `planets/*/` (project-specific workspaces)

---

## Success Criteria

- [ ] Release created in **< 3 minutes**
- [ ] Zero ambiguity about version bump rationale
- [ ] CHANGELOG.md accurate and well-formatted
- [ ] Git tag points to correct commit
- [ ] No manual editing required (unless rejecting proposal)

---

## Common Issues and Fixes

### Issue: "Working tree not clean"
- **Fix:** Commit or stash uncommitted changes before releasing

### Issue: "Not on main branch"
- **Fix:** `git checkout main` before running release

### Issue: Proposed version doesn't match expectations
- **Fix:** Check commit messages use conventional commits format:
  - `feat:` for new features (MINOR)
  - `fix:` for bug fixes (PATCH)
  - `feat!:` or `BREAKING CHANGE:` for breaking changes (MAJOR)
- **Option:** Reject proposal, fix commit messages, re-run

### Issue: CHANGELOG formatting looks wrong
- **Fix:** Review generated preview in confirmation step
- **Option:** Reject, manually edit CHANGELOG after release

### Issue: Want to create pre-release (beta, rc)
- **Fix:** Not supported in MVP - use manual git tag:
  ```bash
  git tag v0.2.0-beta.1
  git push origin v0.2.0-beta.1
  ```

---

## Exit Codes

- `0`: Release created successfully
- `1`: User rejected proposal
- `2`: Pre-flight validation failed (working tree, branch, etc.)

---

## Next Steps After Release

1. **If not using --push:** Push manually:
   ```bash
   git push origin main --tags
   ```

2. **GitHub Release (optional):**
   - GitHub will detect the tag
   - Manually create release notes from CHANGELOG.md
   - (Future: automation via GitHub Actions)

3. **Announce release:**
   - Update project README if needed
   - Notify users/collaborators
   - Document migration notes for MAJOR releases
