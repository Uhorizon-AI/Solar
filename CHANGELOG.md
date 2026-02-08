# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- `CONTRIBUTING.md` with contribution scope, architecture boundaries, and changelog policy.
- `CHANGELOG.md` to track notable framework changes.
- `core/checklist-agents-validation.md` with practical tests for routing, hierarchy, first-run UX, onboarding, and ambiguity handling.
- `core/scripts/sync-clients.sh` to sync Solar core skills/agents/commands to local AI clients (`.codex`, `.claude`, `.cursor`).

### Changed
- Root `AGENTS.md` now defines instruction-resolution priority (`nearest child AGENTS.md` wins by path scope).
- Root `AGENTS.md` first-run protocol now uses non-technical UX with simple menu options (`configure now`, `already configured`, `help`).
- Root `AGENTS.md` now requires explicit scope clarification before writing when user requests are ambiguous.
- `core/AGENTS.md` now requires running `bash core/scripts/sync-clients.sh` after changes in `core/skills/`, `core/agents/`, or `core/commands/`.

## [0.1.0] - 2026-02-08

### Added
- Core governance file and onboarding identity template.
- Conversational onboarding contract with one-question-per-turn flow and correction handling.
- Pre-planet confirmation checkpoint in onboarding flow.
- Orchestration blueprint for routing, reporting, and persistence.
- Generic core sales pipeline skill and reusable sales templates.
- Root instruction symlinks: `CLAUDE.md` and `GEMINI.md` pointing to `AGENTS.md`.

### Changed
- Bootstrap onboarding profile to include identity handshake fields.
- Core governance with template policy and language policy.
- README operating contract and instruction-source documentation.
