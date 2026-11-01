# Task spec: independent SHA tests and one-command release publication

**Triage level:** standard
**Date:** 2026-11-01
**Status:** completed

## Objective

Keep local SHA testing independent of versioning, and publish a deliberately authorized fixed code base through protected GitHub CI with controlled failure recovery.

## Scope

- Release script/controller, Test suite workflow, offline tests, release/installation/contribution docs and changelog.
- Remove candidate/promote/tested_sha interfaces and states; preserve ordinary updater-by-SHA without new client mutations.
- Excluded: repository configuration, merging this PR, real releases/client updates, old partial-tag recovery and release/v0.60.15.

## Acceptance criteria

- Default release preview freezes SHA/version/destination, prepares metadata PR and requests protected native auto-merge; no second post-green command.
- Final code matches the authorized base plus validated metadata; drift and unrelated PR publication are rejected.
- One main publisher writes tags/Releases after both suites and installer acceptance; public recovery reruns that exact request remotely.
- Live pause/omissions registry is strict and append-only; predecessor omission permits a higher correction without publishing defective code.
- Exceptional freeze/reconcile/omit/unfreeze requires explicit operator evidence and completed runs/all job attempts; uncertain outcomes stay blocked. No atomic cancellation claim.
- All three plan reviewers must approve the same issue body before implementation; final code review and tests are separate gates.

## Checks to run

- `uv run --project core/tests pytest core/tests/scripts/test_release_automation.py -q`
- `bash core/tests/scripts/test_create_release_gate.sh`
- Shell/Python syntax, workflow YAML parse and whitespace checks.
- Real publisher with disposable bare Git and fake GitHub services: merge -> installer failure before writes -> retry -> matching tag/Release -> idempotent repeat.
- Installer E2E with isolated client sync on committed implementation.
- Full GitHub PR CI; live activation is separate.

## References

- Policy: CONTRIBUTING.md
- Issue: https://github.com/Uhorizon-AI/Solar/issues/122
- Plan approval: https://github.com/Uhorizon-AI/Solar/issues/122#issuecomment-6557420512
- Exact plan revision4 body SHA256: db20ed68c266fd9610a4acae71935e9a86bad8f0157d0ff442b13a5422246754.
- Codex, Cursor and Antigravity each returned OK PARA IMPLEMENTAR for that body before code changes.
- Authority: Louis explicitly requested this issue -> three-OK -> PR update sequence; it does not authorize settings, merge or release.

## Implementation notes

The existing updater already reports nominal version and installed commit in its current/complete messages. No updater code or runtime was changed. Omission evidence is an operator attestation supplemented by API identity/status checks, not a machine proof of resolved accepted requests. Token expiry after completed jobs does not undo accepted writes; uncertainty keeps recovery paused.

## Review checkpoint

Independent local Codex review found two blockers (first-parent retry selection and missing check/PR read permissions) and a minor omitted-resubmission admission issue. They are corrected with focused assertions. Second static Codex delta review returned Aprobado, confirming the corrections and explicit operational limits; it did not execute tests or authorize merge/publication.

## Completion evidence

- 61 controller tests pass, including strict append-only registry, unresolved writer/outcome rejection, partial/published/conflicting states, omission-aware predecessor acceptance and exact first-parent remote retry.
- 75 shell/publisher tests pass, including fixed preview/command behavior, no local writer, stable Release identity and public bootstrap verification.
- Controlled lifecycle test executes the real shell/controller using bare Git and fake GitHub services: installer failure before writes, retry to success and idempotent repeat. Its installer is a stub; this is not a live GitHub permissions/branch-protection test.
- Shell/Python syntax, workflow YAML parsing and whitespace checks pass.
- Installer E2E is repeated on the committed implementation before push; it runs isolated client sync for the changed release command.
- No repository settings, live merge/release/client update or legacy-tag recovery was performed. Native auto-merge remains a prerequisite to enable deliberately after review. Full GitHub CI on the new PR SHA and controlled real-environment activation remain separate evidence.
