# AGENTS Validation Checklist

Use this checklist to validate that AGENTS rules are operational, not only documented.

## 1. Routing Smoke Test

Goal: ensure tasks are written in the correct layer.

- [ ] Prompt a framework task (contracts/templates/governance).
Expected: changes go to `core/`.
- [ ] Prompt a personal preference task.
Expected: changes go to `sun/`.
- [ ] Prompt a domain task for a specific planet.
Expected: changes go to `planets/<planet-name>/`.
- [ ] Confirm no cross-layer pollution in the same task.

## 2. Hierarchy Resolution Test

Goal: ensure nearest `AGENTS.md` wins.

- [ ] Define or identify a root rule and a different child rule (for example in `core/AGENTS.md`).
- [ ] Execute a task targeting the child folder.
Expected: child rule is applied over root default.
- [ ] Execute a task outside child scope.
Expected: root rule is applied.

## 3. First-Run UX Test

Goal: ensure non-technical first-run flow.

- [ ] Simulate fresh clone state and send "hello".
Expected: simple setup menu (configure now / already configured / help).
- [ ] Confirm there is no technical dump by default (missing files, shell debug).
- [ ] Select setup option and verify bootstrap guidance is clear.

## 4. Onboarding Flow Test

Goal: ensure onboarding behavior is consistent.

- [ ] After setup, verify identity handshake starts immediately.
- [ ] Verify one question per turn.
- [ ] Provide a correction ("I was wrong") and verify state is updated without restart.

## 5. Ambiguity Handling Test

Goal: avoid writing to wrong folder on vague prompts.

- [ ] Send ambiguous prompt like "create a template".
Expected: asks clarifying question for destination (`core`, `sun`, or `planet`).
- [ ] Send "save this" without scope.
Expected: asks scope before writing.

## 6. Pass Criteria

Mark validation as passed only if all are true:

- [ ] Correct routing in all smoke tests.
- [ ] Child-over-root hierarchy works reliably.
- [ ] First-run UX is simple and non-technical.
- [ ] Onboarding starts and progresses correctly.
- [ ] Ambiguous prompts request scope before writing.

## 7. Failure Handling

If any check fails:

1. Update the relevant `AGENTS.md` (root or child scope).
2. Re-run only failed section.
3. Re-run full checklist before merging governance changes.
