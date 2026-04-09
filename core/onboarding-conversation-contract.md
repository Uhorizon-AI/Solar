# Onboarding Conversation Contract

This contract defines how Sun conducts onboarding with any user.

## Principles
1. Ask for one field at a time.
2. Confirm and persist each answer before asking the next field.
3. Allow corrections at any point without restarting the flow.
4. If the user updates previous context, overwrite with the newest valid value.
5. Keep interaction lightweight and conversational, not form-heavy.
6. Never create a planet before a confirmation checkpoint.

## Required Order
1. User name.
2. How user wants to be addressed.
3. Assistant name.
4. Preferred language.
5. Preferred tone.
6. Working preferences.
7. Constraints.
8. Current focus.

## Turn Protocol
- Sun asks exactly one question per turn.
- Sun stores answer in the onboarding profile.
- Sun confirms the stored value in one short line.
- Sun asks the next question.

## Pre-Planet Checkpoint (required)
- Before creating `planets/<planet-name>/`, Sun must show:
  - Captured identity and working preferences summary.
  - Baseline constraints summary.
  - Proposed planet name and objective.
- Sun must ask for explicit confirmation: `Do you want to create this planet now?`
- Planet creation starts only after a clear yes.

## Identity Data Isolation Rule (required)
- **Never** write user names, assistant names, or model names into `sun/MEMORY.md` or any planet MEMORY file.
- Identity fields belong exclusively in `sun/preferences/profile.md`.
- Patterns and learnings in MEMORY.md must be written generically (e.g., "the user", "the assistant") — never referencing actors by name.
- Rationale: names in MEMORY.md become stale references when the user updates their identity in profile.md.

## Profile Update Protocol (required)
When the user changes their name or the assistant name:
1. Update `sun/preferences/profile.md` with the new values.
2. Scan `sun/MEMORY.md` and any `planets/*/MEMORY.md` for stale name references.
3. Replace any hard-coded names with generic references (e.g., "the user", "the assistant") or remove them.
4. Confirm the update to the user in one short line.

## Correction Protocol
- If user says "I was wrong" or provides a replacement:
  - Update the relevant field immediately.
  - Confirm the new value.
  - Continue from the latest onboarding state.

## Completion Criteria
Onboarding is complete when all required identity fields and minimum working context are filled:
- Identity handshake (5 fields).
- Response format.
- Decision style.
- Time constraints.
- Top 1 current focus.
- Pre-planet summary validated by user.
