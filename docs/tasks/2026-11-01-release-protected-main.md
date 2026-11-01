# Task spec: release publication on protected main

**Triage level:** standard
**Date:** 2026-11-01
**Status:** completed

## Objective

Publish releases without pushing unchecked metadata commits to protected main or leaving an unmerged release tag behind.

## Scope

- Files: release script, release regression tests, release command/installation docs, CONTRIBUTING, CHANGELOG and this spec.
- Excluded: branch protection settings, runtime state, other skills, existing published tags, merging PRs and publishing releases.

## Acceptance criteria

- Prepare a local release branch and metadata commit without a tag.
- Publish only an integrated commit with exact-commit suite checks (urgent bypasses suite only).
- Push one requested tag, never main or unrelated tags; reject tag identity conflicts.
- Retry applies the same integration/check/identity requirements.
- Honor explicit versions and document normal and legacy recovery flows.

## Checks to run

- `bash -n core/scripts/create-release.sh core/tests/scripts/test_create_release_gate.sh`
- `bash core/tests/scripts/test_create_release_gate.sh`
- Installer E2E: `bash core/tests/skills/solar-client/test_install_solar_client.sh`
- CI: `bash core/tests/run_suite.sh` through the existing Test suite workflow.

## References

- Repo policy: CONTRIBUTING.md
- Issue: https://github.com/Uhorizon-AI/Solar/issues/120
- Authorization: Louis explicitly requested the issue and associated corrective PR in this chat.

## Implementation notes

Preparation and publication are separate. Existing v0.60.14 and local main remain untouched. No additional AI reviewers were requested.

## Completion evidence

- Shell syntax and `git diff --check`: passed.
- Release regression suite: 49 passed, 0 failed, using disposable Git repositories and a GitHub API double; covers exact SHA, unmerged targets, both publish paths, urgent mode, conflicting/annotated tags and `push.followTags`.
- Installer E2E: 28 passed, 0 failed. The restricted first run could not use `ps`; rerun with process inspection allowed passed. A post-commit rerun validates the committed version and performs client sync inside its isolated fixture.
- Diff reviewed locally. No additional AI reviewer was requested; GitHub CI remains a separate required gate.
- Existing local main and v0.60.14 were not rewritten. The PR does not perform legacy release recovery, merge or publish a release.
