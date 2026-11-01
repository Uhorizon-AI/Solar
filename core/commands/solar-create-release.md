---
name: solar-create-release
description: Request a release once; GitHub integrates, tests and publishes it
---

# Solar Release Creation

## Normal operation: one command

From clean main synchronized with origin/main:

```bash
bash core/scripts/create-release.sh --version vX.Y.Z
# Omit --version to review a Conventional Commits version proposal.
```

The preview includes the version, changelog, bootstrap pin and full external effect.
Confirmation requests a branch push, release PR, native auto-merge and subsequent
CI publication of that version. Deliberate `--yes` confirms the same bounded effect;
it is not just a local preparation flag in default mode. An agent needs explicit
authority for this complete effect before executing the default command.

The command commits metadata and `.github/solar-release.json`, pushes only the
release branch, opens its PR and requests auto-merge with a matching head SHA.
It returns the PR link; the terminal and maintainer computer can be closed.
GitHub waits for required checks/reviews. It does not bypass branch protection,
self-approve reviews or use an administrator override.

After integration, the Test suite workflow runs both suites on the exact push
SHA. Its dependent publisher validates the committed request and merged PR,
runs installer acceptance, and publishes only that SHA's tag and GitHub Release.
An ordinary PR or later main commit inheriting the same request does not publish.

Follow the PR and its post-merge Test suite Actions run. Merge, tests and
publication are separate outcomes. A green PR or a merged request does not mean
publication succeeded; the publisher's verified result and job summary do.
Notifications follow the user's GitHub notification settings.

## One-time repository prerequisites

- GitHub CLI authenticated as the maintainer, with repository permissions for
  branch push, PR creation and requesting auto-merge. Do not submit with an
  Actions GITHUB_TOKEN: token-generated events have different triggering behavior.
- `origin` points to `SOLAR_RELEASE_REPO` (default `Uhorizon-AI/Solar`).
- Repository Settings permits **Allow auto-merge** and merge commits.
- Main requires both `Suite (ubuntu-latest)` and `Suite (macos-latest)` checks.
  Any required human review still applies and can pause native auto-merge.

The script checks prerequisites and refuses rather than editing settings. Installing
this implementation or merging its PR does not enable settings or request a release.
Legacy release branches without committed intent do not start automatic publication.

## Local preparation and recovery

```bash
# Preparation only: branch, metadata, intent and commit; no remote effects or tag
bash core/scripts/create-release.sh --local --version vX.Y.Z

# From the prepared release branch: reuse/open the PR and request auto-merge
# Also resumes an interrupted default submission, without creating another commit.
bash core/scripts/create-release.sh --resume

# Controlled manual publication of an integrated, checked HEAD
bash core/scripts/create-release.sh --publish --version vX.Y.Z

# Existing remote tag but missing Release; fetch the tag if absent locally
git fetch origin tag vX.Y.Z
bash core/scripts/create-release.sh --publish --retry --version vX.Y.Z
```

`--resume` and manual publication need explicit external-effect authority, just as
default submission does. A conflicting existing release PR head must be inspected,
not overwritten. If a GitHub response is uncertain, inspect the existing branch/PR
and resume it; do not start another version.

For failed post-merge CI or publication, correct the cause and re-run the failed
Actions jobs on the **same SHA**. Use manual publication only as deliberate recovery.
If tests need code fixes, integrate them and make an explicit new release/recovery
decision; never pretend the original failed commit has passed.

`--publish` requires clean HEAD integrated into origin/main (local branch name is
irrelevant), matching SOLAR_VERSION, green exact-commit suites and matching local/
remote tag identities. It runs the installer E2E, pushes only the requested tag
with automatic tag following disabled, creates the Release with `--verify-tag`
and verifies the API/bootstrap URL. Release notes come from the target commit's
changelog. `--retry` resolves the existing local tag and repeats integration,
suite and remote identity checks without recreating or moving it.

`--urgent "reason"` is available only with manual `--publish`: it bypasses only
the suite gate and requires separate explicit, recorded authorization. Automatic
publication never uses it. Integration, version and tag identity remain mandatory.

## Request integrity and release order

The committed intent records schema, requested version and preparation base SHA.
Validation checks the CLI version, changelog, README bootstrap pin, metadata-only
changes and the matching same-repository merged release PR. The publisher checks
out the immutable event SHA, including after squash/rebase, not a later main tip.
Deleted request branches are inspected through their persistent GitHub PR refs.

One release request may be open/unpublished at a time. A new request must wait
for its predecessor's non-draft stable Release and matching tag. Race conditions
are also checked after merge: a stale or unpublished predecessor fails visibly.
Publishers use a non-cancelling concurrency group with `queue: max`; ordering
comes from predecessor/version checks, not an assumption of merge-order scheduling.
If a racing later request fails while its predecessor publishes, rerun its jobs
once the predecessor is verified. Never advance or replace a published tag.

Only the dependent main publisher receives write permissions. It completes
publication in that same workflow, without depending on tag/release events created
by GITHUB_TOKEN triggering another workflow. No client update or deployment is run.

## Legacy partial publications

An old release may have pushed a tag while main was rejected (GH006). No mode
rewrites it or bypasses integration. Inspect history and integrate the original
commit while preserving its identity, or make a separate recovery decision/new
version. Existing v0.60.14 is not repaired automatically.

## Options and identity

- `--version vX.Y.Z`: exact requested version; otherwise propose a semantic bump.
- `--yes`, `-y`: confirm the displayed mode and its effects without a prompt.
- `--local`, `--resume`, `--publish`: separate modes.
- `--retry`: only with `--publish`; complete an existing tag's Release.
- `--push`: deprecated alias for manual `--publish`.
- `SOLAR_RELEASE_REPO`: selects checks, Release operations and bootstrap URLs;
  does not change origin.

Tag/Release uses `vMAJOR.MINOR.PATCH`; CLI uses `MAJOR.MINOR.PATCH`; bootstrap
pin and intent use the same tag. Install/update defaults still resolve the latest
stable GitHub Release. Exit 0 means the selected operation succeeded; submitted
requests still need their later CI/publication result. Exit 1 is a failed gate or
operation; exit 2 is a usage/pre-flight error. Releases remain grouped unless an
urgent fix justifies going outside the maintainer's cadence.
