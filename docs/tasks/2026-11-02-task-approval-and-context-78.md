---
review_pass: complete
design_frozen: true
last_review: 2026-11-02 Cursor Aprobado (ejecutabilidad)
---

# Task spec: approval recovery and execution context

**Date:** 2026-11-02
**Status:** implementation ready for PR #127 review, including external feedback corrections; not installed
**Base:** `7732a11` (v0.61.1)
**Issues:** #78; diagnosis of #101. The 26 October async-context plan supplies the prompt boundary requirements.

## Outcome

Recover the exact stored task without a native confirmation that is already known to be unusable. Keep approved instructions distinct from generated context. Preserve the existing authorization of unchanged recurring tasks instead of introducing another permission registry.

This is the first delivery of the approval, iterative review and proactive-agent initiative. Provider session reuse, broader multi-SHA authorization and new delegated-authority semantics are subsequent deliveries, not implicit permissions introduced here.

## Verified baseline

| Evidence | Current behavior |
|---|---|
| `core/skills/solar-state/scripts/solar_state.py:2421` | `task_authorize_run` checks queued state, row version and approval coverage inside its transaction. Unchanged recurrence retains `run_authorized_digest`. |
| `core/skills/solar-mcp/scripts/operations.py:907` and `mcp_server.py:491` | `task.authorize_run` has no `pre_confirm` hook; detectable prerequisite failures reach state validation after native elicitation. |
| `solar_state.py:2372,2446,2631` | Approval accepts draft/planned; return-to-draft accepts queued; requeue accepts error. Error-to-draft is absent from the transition table. |
| `core/skills/solar-mcp/scripts/task_views.py:256` | Detail/status expose execution-consent waiting but not a structured content-approval recovery route. |
| `core/skills/solar-async-tasks/scripts/execute_active.py:242,247,1068` | Ordinary execution places the whole stored body under task instructions, after subtask preparation. |
| `solar_state.py:1058,1071` | `runtime_tail` and `current_definition` already implement the canonical boundary. Reuse them, not another Markdown parser. |
| `mcp_server.py:569,626` | Elicitation already waits for its correlated response; several failures collapse to `not_accepted`. The cause of #101 in the actual client is unverified. |

## Changes to implement

1. **One readiness contract in solar-state.** Read queued state, row version, content approval (`valid/absent/legacy/mismatch`) and execution-consent requirements through the state owner. Reuse that validation before elicitation and inside the authorization transaction. No approval or audit mutation from a read-only preflight.
2. **Preflight before the native form.** Wire readiness into `task.authorize_run.pre_confirm`. Missing task, stale version, wrong state or invalid content approval returns a structured reason and a valid next operation without a form or grant. Still revalidate inside the write transaction after acceptance: concurrent edits must refuse safely.
3. **Explicit recovery through existing operations.** A queued task with invalid approval follows `return_to_draft → approve → authorize_run`; the client can carry out those local preparation operations from the explicit recovery request, subject to host permission. For a high-risk task, only the final native form grants execution consent; a verified confined task needs no execution-consent form. Never silently approve on requeue or let a mandate approve/authorize a task.
4. **Direct recovery of a failed task.** Extend `task.return_to_draft` to `error → draft` transactionally, with a forward migration registering the transition. Preserve id, definition boundary, body/errors/results, schedule and run counters; withdraw old approval and consent with existing audit. This avoids `requeue → return_to_draft`. Keep valid unchanged requeue behavior intact. Refuse active/completed/cancelled/archived tasks.
5. **Actionable views and confirmation text.** Add content-approval state and next allowed operation with current row version to detail/status. Preserve existing fields. State the stored effect, effective recurrence and persistence of consent in the form; display the canonical definition as instructions, keeping generated context distinct. Diagnose accept/decline/cancel/expiry/disconnect/client-error separately without treating an error or a retry as consent. Do not claim #101 fixed without client evidence.
6. **Ordinary execution prompt boundary.** Build an immutable instruction block from the canonical current definition; put generated results, delivery and errors in a separately labelled, non-authoritative context block. Read through solar-state, after subtask preparation and under the existing execution claim. This is prompt organization, not a security boundary or an injection defense; authority remains in the state gate and effective host confinement. For this delivery preserve generated context conservatively: no historical pruning or claimed token saving. Current child results must reach parent synthesis; retries retain diagnostics. Ambiguous imported boundaries must be explicit and must not silently lose content.

## File ownership and boundaries

| Files | Intended change |
|---|---|
| `core/skills/solar-state/scripts/solar_state.py` | Readiness validation, canonical prompt-context accessor, error-to-draft transition/migration, transactional recovery. No new digest version or authority store. |
| `core/skills/solar-mcp/scripts/operations.py` | Pre-confirm hook, recovery contract and additive operation metadata. |
| `core/skills/solar-mcp/scripts/task_views.py` | Structured approval reason and next valid operation. |
| `core/skills/solar-mcp/scripts/mcp_server.py` | Preserve structured preflight refusals; distinguish confirmation outcomes without weakening response correlation. |
| `core/skills/solar-mcp/scripts/approval_text.py` | Recovery and recurrence wording, English default and existing language mechanism. |
| `core/skills/solar-async-tasks/scripts/execute_active.py` | Separate definition and generated context; keep restricted and deterministic-local paths unchanged. |
| `core/docs/task-approval-contract.md`, relevant state/MCP/async skill references, `CHANGELOG.md` | Correct recovery instructions and document the new transition and prompt contract. Keep skill indexes lean. |
| `core/tests/skills/solar-state/`, `solar-mcp/`, `solar-async-tasks/` | Regression cases below, using temporary owned runtimes and provider doubles. |

## Acceptance tests

- Missing/legacy/mismatched approval, wrong state and stale version: no elicitation and no grant; advertised recovery is executable in the advertised state.
- Legacy queued recovery: same id, definition, schedule, counters and history; high-risk work needs one accepted native form, while verified confined work needs none, then it is executable. No manual approval IDs or prescribed conversational phrases.
- Error-to-draft: no intermediate queued state observable by a worker; history preserved, old authority withdrawn, stale-version and competing-claim attempts refuse safely. Existing and freshly migrated databases accept the transition.
- Valid queued task: form works as before. Decline, cancellation, expiry, malformed response and disconnected client never grant consent; acceptance binds the exact arguments and approved task.
- Content changes while a form is open: final transactional validation refuses the stale request. Preflight is not a lock held across human interaction.
- Unchanged recurring task and valid retry: authorization persists. Material edit withdraws it; recovery never backfills derived-child provenance or bypasses `refuses_mandate`.
- Prompt fixtures: normal run, recurrence with old result, parent with successful/failed children and error retry. Instructions match the canonical definition; generated context remains available outside it.
- A definition containing fenced `## Result`, runtime headings inside a generated result and an imported task without a reliable snapshot preserve content and expose uncertainty. Approval digest is unchanged by prompt formatting.
- Restricted repository reviews and deterministic-local execution remain unchanged. No second synthesis or duplicate child execution after recovery.
- #101: deterministic delayed-response protocol test records the actual outcome. Real client reproduction is a separately recorded acceptance check; pending evidence remains pending, not an inferred fix.

## Validation and delivery

1. Run focused regression files, then `uv run --project core/tests pytest core/tests/skills/solar-state core/tests/skills/solar-mcp core/tests/skills/solar-async-tasks -q` in isolated test runtimes.
2. Package-validate the three modified skills; run `git diff --check`. Run `solar client sync` when skill sources change; record which installation was synchronized, without claiming this checkout is deployed.
3. Full required CI suites on the final PR head; independent review is a pre-check and the maintainer performs the merge review. No commit, push, merge, release, live-task mutation or external notification is authorized by this spec.

## Explicit exclusions

- No credential copying, provider flags/session implementation, `ask_lite`, Code Mode or new scheduler.
- No blanket multi-SHA authorization, new A3 mandate approval path, changes to `MATERIAL_KEYS` or the `v2:` digest.
- No automatic expiry/revocation mechanism beyond the current contracts; wider flow lifetimes require separate design.
- No #75/#79 update cleanup unless a demonstrated blocker requires it; #104 real-client validation stays separate. #94/#96 are already closed.
- No implementation of business alerts, watcher lists or the weekly cycle. PR #91 must rebase against any shared state/operation changes and revalidate its notification contract.

## Preparation evidence

- Reviewed the base implementation and the existing approval/recovery/context contracts. This document changes no framework code.
- Existing baseline: 123 state/MCP cases passed; all 9 approved-worker cases passed on an isolated rerun with explicit support-module paths and process-table access (132 distinct cases total). Seven worker cases initially failed because the restricted environment denied `ps`; the first standalone retry also exposed missing import paths. No provider inference or live task mutation was used. These results validate the baseline, not the proposed behavior.

## Backlog de revision

- 🟡 The verification reviewer could not rerun the 132 baseline cases in its read-only sandbox; the preparation results remain author-provided evidence, not an independent rerun. Non-blocking; do not reopen in later passes.

- 🟡 Claude, form content: use the canonical definition in approval_text.py, not the full historical body. Incorporated into change 5; no repeat review.
- 🟡 Claude, trust boundary: labels do not confine an AI client or prevent injection. Incorporated into change 6; no repeat review.
- 🟡 Claude, confined recovery: zero execution-consent forms for verified confined tasks; one for high-risk work. Incorporated into change 3 and acceptance; no repeat review.
- 🟡 Claude, clients without elicitation: retain transactional validation and the existing trusted-host path; add a no-elicitation regression case. Preflight UI support is not assumed universal.
- 🟡 Antigravity, imported boundaries: make boundary uncertainty explicit without inventing a new parser, silently dropping content or claiming that an inferred split is a verified instruction boundary.
- 🟡 Antigravity, post-confirmation race: return a structured stale-state/recovery reason from the transaction; distinguish it from a user's refusal or the not_accepted transport outcome.
- 🟡 Antigravity, recovery invalidation: explicitly test removal of run_authorized_digest with all previous approval and consent fields on error-to-draft.


## Implementation evidence

- Branch: `fix/task-approval-context-78`, based on `7732a11`; separate PR publication requested by the maintainer after local review.
- State/MCP/async suites plus client update-sequence migration tests: **1,454 passed, 1 skipped** in 597.20 s. Tests use temporary owned runtimes and provider doubles.
- After independent review corrected approved reviewer declarations being placed after generated context: focused state/MCP/form/worker regressions **95 passed** in 16.83 s. These include real executor prompt capture in declaration and synthesis phases, without provider inference.
- Three skill packages validate; `git diff --check` passes. Client sync completed through the existing global installation at the existing `SOLAR_ROOT`, which excludes this checkout from planet resource discovery. This branch was not installed and production state was not upgraded to schema v9.
- The delayed-form transport test passes; real-client #101 reproduction remains pending. Valid `task.requeue` retains its existing error-body trimming behavior; direct error-to-draft recovery preserves diagnostic context.
- Independent code review by Claude: initial feedback corrected; final delta review accepted with no remaining findings. Required remote CI and maintainer merge review remain future PR checks.


## External review follow-up

- Valid failed work advertises requeue and retains consent; invalid approval advertises draft recovery. Covered consent produces no second native form, and non-queued states do not claim executable authorization.
- New definition provenance is checked through state; fresh drafts/plans have empty generated context, while imports without snapshots remain explicitly ambiguous. Executor coverage preserves authored content without silently promoting history to authority.
- Decline/cancel replies may omit content. All domain pre-confirmation errors use an audited tool-error envelope with linked decision/outcome traces, without granting consent or executing the handler.
- Focused feedback regressions: **128 passed**. Complete state, MCP, async and entire client suites: **1,762 passed, 3 skipped** in 709.25 s. Modified skill packages validate and whitespace checks pass.
- This follow-up does not install the branch, migrate production, merge or publish a release; real-client reproduction of #101 remains pending.
