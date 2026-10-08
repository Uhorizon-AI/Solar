# Task spec: record the capability-discovery experiment

**Triage level:** standard
**Date:** 2026-10-09
**Status:** completed

## Objective

Record in the repository that the reduced skill profile was measured in four fresh Codex rounds and did not lower session cost, so the same path is not repeated without a new hypothesis. This is documentation only; behavior is unchanged.

## Scope

- Files to modify: `core/skills/solar-client/references/discovery-profile.md`, `core/docs/capability-discovery-design.md`, `CHANGELOG.md`, this task spec
- Files explicitly out of scope: all code and tests, the profile default (`native`), Client settings, the installed runtime, `~/.codex`, `solar client update`, `solar client sync`, release

## Acceptance criteria

- [x] `discovery-profile.md` replaces the pending experiment section with the outcome (closed, opt-in, not enabled, not extended), the four-round table, the per-request catalog saving, the effect of the follow-up changes, the cause, what stays useful, and how to measure a future attempt
- [x] The numbers are the ones measured from the Codex session log (`token_count` events); the conversion from bytes to tokens is marked as having overstated the saving
- [x] `capability-discovery-design.md` no longer says the comparison is pending and points to the record
- [x] `CHANGELOG.md` has an Unreleased Documentation entry
- [x] No private workspace content, business facts, absolute paths of the user, or credentials

## Checks to run

Documentation only: `git diff --check`, and inspect that the local Markdown links in the two edited documents resolve. No runtime tests or sync are needed.

## References

- Repo policy: `CONTRIBUTING.md`
- PR comments with the same results: Uhorizon-AI/Solar#9 and Uhorizon-AI/Solar#14

## Completion evidence

- Four rounds, one session per mode and round, reduced profile against full catalog, from the Codex session logs: total input +24 %, -14 %, -10 %, +20 %; uncached +33 %, -28 %, +13 %, +68 %.
- Per-request catalog saving 4,186 to 4,235 tokens in the rounds that ran in the workspace folder.
- Round 4 had `full=true` on 0 of 6 `describe` calls, against 3 of 3 before the change.
