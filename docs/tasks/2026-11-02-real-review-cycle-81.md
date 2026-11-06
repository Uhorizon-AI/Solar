# Task spec: real iterative review through the notification pilot

**Triage level:** standard
**Date:** 2026-11-02
**Status:** in_progress

## Objective

Demonstrate review, reproduced feedback, a bounded correction and a second SHA-labelled review through Solar MCP, without changing the active installation.

## Scope

- Existing issue #81 / PR #91 supplies the pilot; the delivery mechanism remains the objective.
- Carry PR #91 onto main f5f497b as a separate baseline; only CHANGELOG.md conflicts.
- Reproduce the failure sender killing the notifier before lock-timeout evidence is recorded; adjust its bounded deadline and regression coverage.
- Preserve snapshot, incremental diff, test output and feedback state for the second review by Codex, Claude, Cursor and Antigravity.
- Diagnose unavailable restricted authentication and session continuation without modifying credentials, permissions, active configuration or operational tasks.
- No push, new PR, merge to main, release, installation or live notification.

## Acceptance criteria

- [ ] A real notifier/supervisor regression fails before the correction and passes afterwards in a temporary runtime with a local sender.
- [ ] The correction remains bounded and supervisor shutdown still ends the process group.
- [ ] Relevant notification, supervisor, state and MCP checks pass on the reviewed version.
- [ ] A new SHA and incremental diff carry feedback IDs and explicit test evidence into round two.
- [ ] Four useful repository reviews are required for complete validation; unavailable providers remain explicit blockers.
- [ ] Real-client approval and provider resume are distinguished from protocol doubles and new-session summaries.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-async-tasks core/tests/skills/solar-mcp core/tests/skills/solar-state -q
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-async-tasks /tmp
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-mcp /tmp
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-state /tmp
git diff --check
```

Use the existing test virtualenv without dependency changes. All test tasks and senders are disposable fixtures. Client sync is deferred because the active configuration must remain unchanged.

## References

- CONTRIBUTING.md
- Issue #81, PR #91
- First review SHA: aa195e4249a36aabe0f76d5b40f908ac702517b5
- R1 tasks: b089eb6e-1804-4f63-9e5b-6257c5e862cd (Codex), 18bfe6a6-d4c5-45ed-891b-1d11f16f0094 (Claude), 6c840657-8906-407f-8a7e-810c3ebdda92 (Cursor), f6de3f6c-0882-4e60-811f-865e5b6e2541 (Antigravity; not_logged_in).

## Feedback ledger

| ID | R1 finding | State |
|---|---|---|
| F1 | Failure sender's 30 s deadline expires before the notifier's 150 s lock wait; evidence may be lost | Reproduced with real notifier and supervisor using shortened timings; corrected with separate bounded terminal deadline; R2 pending |
| F2 | Sender exit after queue.Empty can strand a notice | Appears addressed in PR #91; regression retained |
| F3 | Age-based lock reclamation has an ownership race | Pending assessment; not treated as resolved by changing a deadline |
| F4 | Restricted agy exits not_logged_in, while a normal ask answers | Reproduced; exact cause pending; no credential changes authorized |
| F5 | #101 first-call confirmation outcome in Claude Code | Requires the real human-facing Claude Code client; not established by provider execution |
| F6 | Restricted review resume with isolation | Current MCP schema has no resume input; ephemeral/no-persistence/private state prevents this path from demonstrating resume |

## Completion evidence

- Separate carry-forward baseline: 0fa7cc38f838dc4e175d9ccaafc74ac692d0c66b (main f5f497b plus PR #91; only conflict was changelog placement). This is a local integration baseline, not a new published PR or a claim of review of all intervening main changes.
- Red: the new real notifier/supervisor test failed before the correction with no notify_error recorded (1 failed, 1.37 s). Green: all 21 approval-notice tests passed, including the new lock-timeout and process-group deadline cases (14.01 s). The test uses two lock iterations and shorter independent supervisor deadlines; it does not claim a 150-second wall-clock soak.
- The pre-correction carry-forward focused run had 85 passes and two process tests failing under restricted process access. Those two passed when repeated with access to their own temporary processes (2 passed, 5.45 s); this is an environment limit, not a silently ignored baseline failure.
- Skill validation/package checks passed for async-tasks, MCP and state. Packages were written only to a temporary directory, not installed. Whitespace check passed.
- Live high-risk confirmation in Codex desktop: task 2129c4a0-4ae9-4898-a5c9-39554ec00a68 waited before authorization; first native confirmation accepted (trace 0d69dafbf086); provider Claude returned exactly SOLAR_APPROVAL_PROBE_OK. This establishes this client path, not Claude Code's human-facing path, denial behavior or persistent recurrence authority.
- Full affected suites and R2 pending. No claim of full acceptance or installed behavior. No active client sync, runtime configuration, credentials or operational tasks changed.
