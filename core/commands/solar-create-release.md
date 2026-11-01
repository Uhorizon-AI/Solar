---
name: solar-create-release
description: Prepare a release PR, then publish its integrated and checked commit
---

# Solar Release Creation

Release preparation and publication are separate steps. Required checks on protected
`main` apply to the exact commit being released, including release metadata changes.

## Usage

```bash
# From clean main: prepare metadata on a new local release/vX.Y.Z branch, no tag
bash core/scripts/create-release.sh [--yes] [--version vX.Y.Z]

# Push that branch and open a PR into main (requires explicit authority).
# After merge: check out the integrated commit and wait for its checks.
# Updating local main is recommended, but any clean checkout of that SHA works.
# Publish the checked HEAD; this never prepares another commit or pushes main.
bash core/scripts/create-release.sh --publish --version vX.Y.Z

# Recovery when the matching tag is already remote but its Release is missing
# If the tag is not available locally, first:
git fetch origin tag vX.Y.Z
bash core/scripts/create-release.sh --publish --retry --version vX.Y.Z
```

## Options and authority

- `--yes`, `-y`: skip the preparation confirmation prompt.
- `--version vX.Y.Z`: select the exact version; never silently replaced by a tag on HEAD.
- `--publish`: publish current HEAD after integration, version and suite checks.
  If `--version` is omitted, HEAD must already have an exact release tag.
- `--publish --retry`: use an existing local tag, verify its remote identity and
  complete the GitHub Release without pushing, rewriting tags or making commits.
- `--publish --urgent "reason"`: bypass only the suite gate for an urgent fix.
  The reason is printed. Integration and tag identity checks still apply.
- `--push`: deprecated alias for `--publish`.

Preparation makes a local branch and commit. Branch pushes, PR creation and
publication require explicit authority under the workspace policy. `--yes` is
not authority for external effects.

## Prepare

1. Require clean `main`; analyze commits since the last release or curated Unreleased notes.
2. Calculate and preview the version, changelog and README bootstrap URL; confirm.
3. Create local branch `release/vX.Y.Z` (fail if it already exists).
4. Update `CHANGELOG.md`, `SOLAR_VERSION` in the CLI and the README bootstrap pin.
5. Commit `chore(release): vX.Y.Z`, without creating a tag or sending anything.
6. Push the branch and open a PR when authorized. Merge only after its checks pass.

## Publish

1. Require a clean checkout and the selected version to match `SOLAR_VERSION` at HEAD.
   HEAD must be integrated into `origin/main`; the local branch name is immaterial.
2. Refuse an existing local tag pointing to a different commit.
3. Fetch `origin/main` without fetching tags. Require HEAD to be an ancestor of it.
4. Require `Suite (ubuntu-latest)` and `Suite (macos-latest)` green on **HEAD**, not its parent.
5. Refuse a remote tag pointing to a different commit; never rewrite it.
6. Run the local installer E2E; abort before tag creation/push if it fails.
7. Create the local tag if absent, and push **only that tag**, never `main` or unrelated tags.
8. Verify the remote tag commit, create the GitHub Release with `--verify-tag` if missing,
   then verify the Release API and bootstrap URL. Release notes come from the
   target commit's changelog, not the current working-tree file.

Squash/rebase merges can change the release commit SHA. Publish the integrated
commit after updating main, not the pre-merge release branch. Tags are created
only after integration, so there is no pre-merge tag to retarget.

## Retry and legacy partial publications

If the local tag is absent, run `git fetch origin tag vX.Y.Z` first.
Retry resolves the existing local tag, validates its version, fetches main and
requires that exact tag commit to be integrated with passing suite checks. It then
checks the remote tag points to the same commit before creating a missing Release.
An unavailable remote/API fails closed.

A legacy release may have pushed a tag while main was rejected (GH006). Neither
`--retry` nor `--urgent` bypasses integration, and no existing tag is moved
automatically. Inspect local/remote history and integrate the release commit
through a PR while preserving its identity, or obtain a separate recovery decision
if a squash/rebase would change the published tag's identity. Never force-push
main or silently replace a published tag to repair this condition.

`SOLAR_RELEASE_REPO` selects the repository for suite checks, Release creation, API
verification and bootstrap URLs (default `Uhorizon-AI/Solar`). The `origin` remote
must refer to that repository; this setting does not change the Git remote.

## Identity contract

| Artifact | Value |
|---|---|
| Tag / GitHub Release | `vMAJOR.MINOR.PATCH` |
| `SOLAR_VERSION` | `MAJOR.MINOR.PATCH` |
| README bootstrap pin | same `vMAJOR.MINOR.PATCH` |
| Install/update default | latest stable GitHub Release via API |

Preparation changes only release metadata, its branch and commit. It never modifies
runtime `sun/` or `planets/`, or creates a VERSION file. Releases remain grouped
unless an urgent fix justifies going outside the maintainer's cadence.

## Exit codes

- `0`: success.
- `1`: confirmation rejected or publication/check failure.
- `2`: usage or pre-flight failure.
