---
name: solar-create-release
description: Request a version once; protected GitHub CI integrates and publishes it
---

# Solar Release Creation

## Test code independently

Use ordinary branches/PRs and, when local acceptance is useful:

```bash
solar client update --ref <full-remote-SHA>
```

No new version, release branch or release intent is required to test a commit.
The updater changes the selected installation/runtime; it is not a sandbox and
cannot promise rollback of migrations. Use an appropriate test installation and
workspace. Its current/complete messages report the installed commit separately
from the nominal version. A retained old version number does not mean old code
is installed. Local acceptance covers only the SHA and environment actually tested.
Normal updates still resolve the latest stable GitHub Release.

Correct and review code in ordinary PRs, then integrate into main. If squash,
rebase or base changes alter the content tested, test the integrated SHA when
that local acceptance is needed. CI always validates the integrated result.

## Request publication: one command

From clean main synchronized with origin/main:

```bash
bash core/scripts/create-release.sh --version vX.Y.Z
# Omit --version to review a Conventional Commits version proposal.
```

The preview fixes the full authorized base SHA, version, repository, changelog and
bootstrap pin. Confirmation/intentional `--yes` authorizes preparation, branch push,
version PR, native protected auto-merge and CI publication of that displayed scope.
The command refuses if the checkout changes after preview. Agents need authority
for the complete external effect before executing default mode.

Preparation changes only release metadata: CLI version line, changelog, README
bootstrap block and `.github/solar-release.json` (schema, version, full base SHA).
It commits on `release/vX.Y.Z`, pushes only that branch, opens/reuses its PR and
requests native auto-merge pinned to its head SHA. Once submission succeeds, the
maintainer computer can close. Required reviews/checks remain authoritative.

After integration, both suite jobs test the exact main-push SHA. The dependent
publisher verifies merged-PR provenance and allowed transformations against the
frozen base, runs installer acceptance, then publishes/verifies that SHA's tag and
stable GitHub Release. Main advancing does not authorize extra code: drift stops
publication and requires a fresh explicit request. Ordinary PRs do not request or
republish versions. Merge, passing checks and verified publication are separate
outcomes; follow the PR and its post-merge Test suite run/job summary.

No release-specific candidate/promotion interface is needed. The request does not
assert that every maintainer locally tested its base, or treat an earlier local
SHA as acceptance of the transformed final release. A bootstrap pin to a future
tag is checked textually before publication; the public URL is verified afterward.

## Prerequisites

- Maintainer GitHub CLI/git authentication with repository permissions to push,
  open PRs, request auto-merge and request remote re-runs. No new secret is installed.
- Origin matches `SOLAR_RELEASE_REPO` (default `Uhorizon-AI/Solar`).
- Repository Settings explicitly enables native **Allow auto-merge** and merge
  commits. Main requires both `Suite (ubuntu-latest)` and `Suite (macos-latest)`.
  Required human reviews may pause a request. The script never changes settings,
  approves reviews or uses an administrator bypass.
- No publication-recovery freeze, other open release PR or unresolved predecessor.
  A predecessor can be verified published or explicitly omitted as described below.

Merging this implementation PR does not enable settings or request a real release.
Legacy branches lacking committed intent do not automatically publish.

## Local preparation and submission recovery

```bash
# Prepare branch/metadata/commit only; no remote writes or tag
bash core/scripts/create-release.sh --local --version vX.Y.Z

# From its release branch: reuse/submit the exact prepared request
bash core/scripts/create-release.sh --resume
```

An uncertain GitHub response is resolved by inspecting/reusing the existing PR;
do not prepare another commit/version by assumption. A changed existing PR head
or omitted version is refused before submission. PR/Actions preserve prepared,
integrated and published identities and outcomes; no separate task database is used.

## One remote publisher and retries

```bash
# Ask GitHub to retry the exact integrated request's main CI run
bash core/scripts/create-release.sh --publish --version vX.Y.Z
# Compatibility spelling for the same remote recovery
bash core/scripts/create-release.sh --publish --retry --version vX.Y.Z
```

These commands do not create tags/Releases on the Mac or require local tags.
They resolve the integrated request on main's first-parent history and re-run its
exact CI run. Active runs, recovery freezes and omitted requests are refused.
An unknown legacy request needs a separate recovery decision. `--urgent` cannot
skip checks in this remote recovery path.

The internal writer runs only under the verified main publisher context. Its
live omission/freeze guards run before tag and Release writes. The normal pipeline
uses only job-scoped GITHUB_TOKEN and a single non-cancelling concurrency group
with `queue: max`; no long-lived publisher token or token-event workflow chain is
introduced. Concurrency serializes; it does not cancel writes or guarantee merge
order. A matching tag/Release is reused, conflicting identities stop, and tags
are never moved/deleted/reused. A draft, prerelease, wrong tag or missing public
bootstrap URL is not reported as verified stable publication.

## Exceptional recovery: freeze, reconcile, omit, unfreeze

A temporary CI/network failure may be retried on the same SHA. A code defect uses
an ordinary corrective PR and a higher release version, after the failed request
is safely omitted. A matching tag without a Release can be completed only while
the request remains authorized. A published Release is recognized as published;
corrections use a higher version. Partial tags are retained as allocated versions.

Omission is an explicitly approved exceptional maintainer decision, not an instant
cancel/rollback command. Follow these steps in order:

1. Freeze admission in a normal protected PR by setting `paused: true` in
   `.github/solar-release-omissions.json`, preserving all old entries. Disable
   auto-merge on an affected open release PR and inspect whether it already merged.
2. Once that pause is integrated, inspect/cancel every run/attempt for the request
   and wait for all publisher jobs to finish. The normal job token expires at job
   completion; that does not undo an API request already accepted.
3. Reconcile remote tag/Release identity and all known write outcomes. If a process,
   credential, in-flight request or remote outcome remains uncertain, **stop**:
   omission and the next supported publication remain blocked. Do not infer safety
   just from cancel status, concurrency, a marker, a timeout or repeated API reads.
4. After operator reconciliation, submit a separate normal protected PR appending
   an omission entry while `paused` remains true. It is an explicit operator
   attestation; CI validates identity, prior freeze, all observed run IDs/attempt
   statuses, partial tag identity and absence of an already-published Release.
   CI cannot independently prove that an already-accepted API write has resolved.
5. After that omission is integrated, explicitly unfreeze through another protected
   PR preserving every entry. Old supported attempts/retries permanently reject the
   omitted version/SHA; a new higher version may skip that defective predecessor.

If no publisher job ever started, evidence can establish that no supported writer
received its job credential. If a writer did start, terminal status plus token
expiry is not alone proof of resolved write outcomes: the operator reconciliation
remains mandatory. If exclusion cannot be established, keep the pause. This protocol
does not control arbitrary old tools, human/admin writes outside the supported
mechanism, or revoke an API operation already accepted. No cross-service atomicity
is claimed. Do not activate this feature until the runbook is reviewed and its
limits accepted; never auto-merge an omission as a normal release side effect.

### Registry format

Missing registry means unpaused with no omissions. On first freeze create:

```json
{"schema": 1, "paused": true, "entries": []}
```

An appended entry has exactly these fields (replace placeholders with evidence):

```json
{
  "version": "vX.Y.Z",
  "request_sha": "<full integrated request SHA>",
  "reason": "Known defect; do not distribute this allocated version",
  "runs": [123456],
  "evidence": {
    "writers_stopped": true,
    "outcomes_reconciled": true,
    "notes": "Run/attempt evidence and reconciled remote outcomes; no credentials"
  }
}
```

Old entries are immutable and append-only. Run IDs must enumerate every observed
push/main Test suite run for that exact SHA. Each job/attempt must be completed.
False/unknown reconciliation evidence, mismatched partial tags, omitted identity
conflicts and an already-published Release block the decision. New omissions require
`paused` to have been true in a prior merged commit and remain true in the omission
commit; pausing/omitting/unpausing cannot be collapsed into one implicit action.
An omission PR does not trigger release publication.

## Legacy and scope

Existing v0.60.14 partial publication and release/v0.60.15 are not repaired or changed
by this feature. No installed-client update, deployment or repository configuration
change occurs when preparing this implementation. `SOLAR_RELEASE_REPO` selects
checks, Release API and bootstrap URLs; it never changes origin. The release tag
uses `vMAJOR.MINOR.PATCH`, CLI uses `MAJOR.MINOR.PATCH`; version is allocated when
publication is requested, not to test code.
