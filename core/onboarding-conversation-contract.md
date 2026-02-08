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
