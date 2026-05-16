# Profile Sync Protocol

Invoked when root `AGENTS.md` detects an explicit user update to personal operating context.

## Trigger Conditions

- User corrects or updates profile facts in conversation (identity handshake, professional mode, role, dates, priorities, time constraints, communication preferences, decision criteria).
- User explicitly asks to update profile/preferences.
- Agent detects a conflict between current user statements and `sun/preferences/profile.md`.

## Execution Steps

1. Update `sun/preferences/profile.md` first, preserving existing structure when possible.
2. Keep entries concise, operational, and current. Remove stale or superseded statements.
3. If the change introduces stable operational behavior, update `sun/MEMORY.md` with pattern-level guidance (not identity/config duplication).
4. Confirm back to the user: what was updated, what was removed/replaced, and the operational impact on prioritization/routing.

## Guardrails

- Do not store identity/config duplicates in `sun/MEMORY.md`; those belong in `sun/preferences/profile.md`.
- Do not defer profile changes to weekly consolidation when explicitly provided by the user.
- If the request is ambiguous, ask one short clarification before writing files.
