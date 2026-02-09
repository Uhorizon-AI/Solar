# Onboarding Checklist

## Repository Setup
- [ ] Add `.gitignore` according to your stack.
- [ ] Create first commit with base architecture.

## Identity Handshake (Required First)
- [ ] Run onboarding as conversation (one field per turn).
- [ ] Accept and apply corrections without restarting.
- [ ] Fill user name.
- [ ] Fill how user wants to be addressed.
- [ ] Fill assistant name.
- [ ] Fill preferred language.
- [ ] Fill preferred tone.

## Sun Setup
- [ ] Fill `core/templates/onboarding-profile.md` first (identity handshake + preferences).
- [ ] Fill `sun/preferences/profile.md`.
- [ ] Fill `sun/memories/baseline.md`.
- [ ] Create `sun/daily-log/YYYY-MM-DD.md` only if needed by current user interaction (daily planning/follow-up).

## Pre-Planet Validation (Required)
- [ ] Show a summary of captured onboarding data.
- [ ] Show proposed planet name and objective.
- [ ] Ask explicit confirmation before creating the first planet.

## Planet Setup
- [ ] Create `planets/<planet-name>/`.
- [ ] Copy `core/templates/planet-AGENTS.md` into the new planet.
- [ ] Copy `core/templates/planet-memory.md` into the new planet.
- [ ] Define governance and boundaries in the planet `AGENTS.md`.

## Execution Readiness
- [ ] Use `core/transport-contract.md` for Sun -> Planet requests.
- [ ] Use `core/report-template.md` for Planet -> Sun reports.
- [ ] Run one pilot task end-to-end and refine governance.
