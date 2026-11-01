# Task spec: one-command release requests

**Triage level:** standard
**Date:** 2026-11-01
**Status:** completed

## Objective

A maintainer requests a version once; native GitHub gates integrate its PR and CI publishes the exact tested integrated SHA.

## Scope

- Release script/controller, Test suite workflow, offline tests, command/installation/contribution docs, changelog.
- Excluded: changing repository settings, integrating this implementation PR, creating a real release, client updates/deployments, old partial-release recovery and the existing release/v0.60.15 branch.

## Acceptance criteria

- One explicit request prepares, pushes and opens a release PR with protected native auto-merge.
- Missing auto-merge/required checks refuses before preparation; required reviews remain authoritative.
- Committed intent and merged PR provenance distinguish releases from ordinary changes.
- Both suite jobs gate an exact-SHA main publisher, with installer acceptance and immutable tags.
- Predecessor/version validation and queued serialization stop racing releases from overtaking.
- Local preparation and idempotent submission/publication recovery remain documented.

## Checks to run

- Shell syntax and git diff whitespace checks.
- `uv run --project core/tests pytest core/tests/scripts/test_release_automation.py -q`
- `bash core/tests/scripts/test_create_release_gate.sh`
- `bash core/tests/skills/solar-client/test_install_solar_client.sh` against committed revision.
- Existing Test suite in GitHub CI on the published branch.

## References

- Policy: CONTRIBUTING.md
- Issue: https://github.com/Uhorizon-AI/Solar/issues/122
- Authorization: Louis requested updating #122 and preparing its corresponding implementation PR after selecting a one-command automated lifecycle.

## Implementation notes

Use the maintainer's GitHub CLI to create the PR and request native auto-merge; no bot merge or privilege override. Main's Test suite publishes in a dependent write-scoped job, without a token-generated event chain. GitHub auto-merge is currently disabled; this implementation reports the prerequisite but does not change it.

## Completion evidence

- Release controller tests: 48 passed, 0 failed, offline fixtures/doubles; covers ordinary commits, metadata-only requests, provenance, squash/rebase, advanced main, predecessor identity, repository prerequisites, duplicate/resumed submission, guarded auto-merge and workflow gates.
- Existing publisher regression suite: 74 passed, 0 failed. Source-level preparation fixtures explicitly use local-only mode; command-level tests verify default check/prepare/submit ordering and no remote calls in local mode.
- Shell syntax, YAML parsing and git diff whitespace checks passed.
- Installer E2E: 28 passed, 0 failed on the committed implementation; includes isolated client sync for the changed command catalog.
- Native auto-merge is disabled in the live repository. No setting is changed by this PR. Until explicitly enabled by the maintainer after review, default release submission refuses safely.
- Real auto-merge and release publication are not exercised: that would integrate/publish a version and is outside the current implementation-PR authorization. GitHub CI on the draft PR remains the full-suite gate; code reviewed locally, no new external review verdict claimed.

## Local validation follow-up

- Louis authorized updating issue #122 and PR #123 with an optional candidate phase before stable publication.
- `--candidate` uploads a base-qualified branch with stage=candidate and creates no PR/auto-merge/tag/Release. It can be retried with `--resume` and does not require auto-merge configuration or a free stable-publication slot.
- `--promote --tested-sha` requires the exact clean tested checkout and unchanged main base, records tested SHA and creates the final release request. Code differences after local validation prevent publication.
- New candidates from corrected main may reuse the intended version on a new base-qualified branch. Existing candidate history is not rewritten.
- Pipeline rejects candidate-stage intents. Direct automatic submission remains available; local acceptance is explicit, not an automatically inferred success.
- General cancellation/supersession after a request has merged is not implemented. Documentation distinguishes candidate abandonment, pre-merge native-auto-merge cancellation and separate post-merge recovery; it does not promise atomic revocation of an active publisher. Failed integrated predecessors still require recovery before another stable publication.
- Updated tests: 48 controller cases and 74 publisher/command checks pass. Installer E2E is repeated against the follow-up commit before push.
