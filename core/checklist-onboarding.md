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
- [ ] Validate `sun/` workspace health on demand with `bash core/scripts/sun-workspace-doctor.sh`.
- [ ] Run optional `sun/` git checks only when needed with `bash core/scripts/sun-workspace-doctor.sh --check-git`.

## Pre-Planet Validation (Required)
- [ ] Show a summary of captured onboarding data.
- [ ] Show proposed planet name and objective.
- [ ] Ask explicit confirmation before creating the first planet.

## Planet Setup
- [ ] (Recommended) Use `bash core/scripts/create-planet.sh <planet-name>` for automated setup.
- [ ] (Alternative) Create `planets/<planet-name>/` manually.
- [ ] Copy `core/templates/planet-AGENTS.md` into the new planet (auto-done by create-planet.sh).
- [ ] Copy `core/templates/planet-memory.md` into the new planet.
- [ ] Define governance and boundaries in the planet `AGENTS.md`.
- [ ] (Optional) See `core/templates/planet-structure.md` for resource creation (agents/skills/commands) and sync workflows.
- [ ] Validate planet workspace health on demand with `bash core/scripts/planets-workspace-doctor.sh`.
- [ ] Run optional planet git checks only when needed with `bash core/scripts/planets-workspace-doctor.sh --check-git`.

## Execution Readiness
- [ ] Use `core/transport-contract.md` for Sun -> Planet requests.
- [ ] Use `core/report-template.md` for Planet -> Sun reports.
- [ ] Run one pilot task end-to-end and refine governance.
