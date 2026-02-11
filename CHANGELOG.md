# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- `.github/FUNDING.yml` with optional donation links for project sustainability.
- `.github/ISSUE_TEMPLATE/bug_report.md` and `.github/ISSUE_TEMPLATE/feature_request.md` to standardize incoming reports and proposals.
- `.github/ISSUE_TEMPLATE/config.yml` with direct commercial support contact routing.
- `.github/pull_request_template.md` to enforce structured PR context and validation details.
- `CODE_OF_CONDUCT.md` with expected behavior, unacceptable behavior, and enforcement/reporting notes.
- `SECURITY.md` with private vulnerability reporting channel and response expectations.
- `SUPPORT.md` with community support, commercial support, and optional donation guidance.
- `CONTRIBUTING.md` with contribution scope, architecture boundaries, and changelog policy.
- `CHANGELOG.md` to track notable framework changes.
- `core/skills/solar-migration-playbook` to plan and execute phased migrations from existing folders/repos into Solar (`core/sun/planets`) with a reusable mapping template.
- `core/checklist-agents-validation.md` with practical tests for routing, hierarchy, first-run UX, onboarding, and ambiguity handling.
- `core/scripts/sync-clients.sh` to sync Solar core skills/agents/commands to local AI clients (`.codex`, `.claude`, `.cursor`).
- `core/mcp-catalog.md` as baseline documentation for MCP purpose, usage, and adoption journey.
- `core/scripts/check-mcp.sh` to validate required MCP declarations from a skill against local Codex MCP configuration.
- `core/scripts/sun-workspace-doctor.sh` to audit `sun/` workspace health (required files by default; optional git checks with `--check-git`).
- `core/scripts/planets-workspace-doctor.sh` to audit all `planets/*` workspaces (governance files by default; optional git checks with `--check-git`).
- `core/scripts/planet-git-bootstrap.sh` to initialize/fix Git setup for a single planet (repo init, first commit, optional origin, optional upstream push).
- Extended MCP catalog entries for `n8n`, `telegram`, `whatsapp`, and `chrome-devtools`, including a mobile-first conversation path.
- `core/skills/solar-n8n-workflow` skill (Telegram-first) with MCP requirements, fallback behavior, validation commands, and implementation reference.
- `core/skills/solar-telegram` with `.env`-based transport guidance, alert sender script, environment validator script, and bridge/alerts patterns reference.
- `core/skills/solar-telegram/scripts/onboard_telegram_env.sh` to auto-create/complete `.env` keys for Telegram without overwriting existing values.
- `core/skills/solar-telegram/scripts/setup_telegram.sh` as a single runbook to execute onboarding, optional interactive credential capture, validation, and optional test send.
- `core/skills/solar-transport-gateway` with a local bidirectional transport skill, v1 message contract reference, bridge runtime script, and runtime validation script.
- `core/skills/solar-transport-gateway/pyproject.toml` for Poetry-based dependency management (`websockets`).
- `core/skills/solar-transport-gateway` now includes internal Telegram webhook operations: `.env` onboarding, HTTP webhook bridge, cloudflared tunnel starter, webhook set/verify scripts, and webhook flow reference.
- `core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh` now provides one-command end-to-end setup (prepare, start services, open tunnel, set/verify Telegram webhook).
- `core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh` now prints copy/paste install commands for `cloudflared` when missing.
- `core/skills/solar-transport-gateway` now supports named Cloudflare tunnels (`SOLAR_TUNNEL_MODE=named`) with `configure_named_tunnel.sh` for stable webhook DNS.
- `core/skills/solar-transport-gateway` now includes AI provider routing policy via `.env` (`default`, `fallback`, `allowed`, `mode`) and returns `provider_used` in gateway responses.

### Changed
- `README.md` restructured for open-source positioning of `Solar`, clearer contribution path, and commercial CTA for Uhorizon AI.
- `README.md` now includes creator attribution to Louis Jimenez and maintainer/contact links for Uhorizon AI.
- `CONTRIBUTING.md` rewritten to clarify contribution goals, architecture boundaries, PR requirements, and review expectations.
- Root `AGENTS.md` now defines instruction-resolution priority (`nearest child AGENTS.md` wins by path scope).
- Root `AGENTS.md` now separates version-control boundaries from runtime workspace access rules, clarifying that parent-repo ignore status is not an access restriction and that VCS operations for `sun/` and `planets/<planet-name>/` must run in each workspace repo when present.
- First-run setup UX now uses a non-technical menu (`configure now`, `already configured`, `help`) through delegated setup protocol in `core/AGENTS.md`.
- Root `AGENTS.md` first-run protocol now attempts to read `sun/preferences/profile.md` on first interaction, using profile name/language when readable and delegating setup to `core/AGENTS.md` when missing.
- Root `AGENTS.md` now requires explicit scope clarification before writing when user requests are ambiguous.
- Root `AGENTS.md` now enforces silent profile verification language and explicitly prohibits exposing verification steps in user-facing replies.
- Root `AGENTS.md` now clarifies that `.git` in `sun/` and `planets/*` is optional by default and adds a required workspace doctor policy (git checks opt-in and bootstrap doctor disabled by default).
- `core/AGENTS.md` now requires running `bash core/scripts/sync-clients.sh` after changes in `core/skills/`, `core/agents/`, or `core/commands/`.
- `core/AGENTS.md` now defines delegated setup protocol details (setup menu, execution options, and onboarding handoff) when root first-run detects missing profile.
- `core/AGENTS.md` now defines `core/` self-management: agent executes scripts across `core/**` (including skill scripts) based on `SKILL.md` triggers/workflows, asking users only for inputs/secrets, blocked permissions, or high-risk actions.
- `core/AGENTS.md` now adds workspace doctor execution policy: on-demand by default, git checks opt-in, and missing `.git` non-blocking unless requested.
- `core/AGENTS.md` now defines a global `.env` policy for env-aware skills: skill-scoped header comment plus compact contiguous variable blocks without blank lines.
- `core/AGENTS.md` now defines a host availability note policy for runtime-host dependent skills (webhook/bridge/server/tunnel), requiring a short optional laptop runtime note only where relevant.
- `core/AGENTS.md` now requires per-skill validation with `package_skill.py` whenever a skill under `core/skills/` is modified.
- `core/bootstrap.sh` now runs `core/scripts/sync-clients.sh` when available to keep local clients aligned after setup.
- `core/bootstrap.sh` no longer writes `sun/.setup-complete`; setup readiness is now driven by profile read behavior in root first-run rules.
- `core/bootstrap.sh` now keeps workspace doctor checks on-demand by default and supports opt-in execution via `SOLAR_RUN_WORKSPACE_DOCTOR=1` (plus optional git checks via `SOLAR_DOCTOR_CHECK_GIT=1`).
- `core/skills/solar-skill-creator` now enforces MCP-oriented skill metadata: `Required MCP` and `Validation commands` always required; `Fallback if MCP missing` required only when MCP is actually required.
- `core/skills/solar-skill-creator` now enforces `.env` block conventions for any env-aware skill.
- `core/skills/solar-skill-creator` now enforces per-skill validation with `package_skill.py` in normal edit flow.
- `core/skills/solar-skill-creator` now includes guidance to add `Laptop runtime note (optional)` only for runtime-host dependent skills.
- `core/skills/solar-telegram` setup flow now supports `--token` and `--chat-id` flags so the agent can complete setup from chat without requiring terminal prompts.
- `core/skills/solar-telegram/scripts/onboard_telegram_env.sh` now writes a single compact `.env` block with skill header comment and no blank lines inside the Telegram variable block.
- `core/skills/solar-telegram` now documents optional laptop runtime considerations for `bridge` mode only.
- `core/skills/solar-transport-gateway` now documents optional laptop runtime considerations for long-running local endpoints.
- `core/skills/solar-transport-gateway` scripts now use Poetry (`poetry run`) instead of direct `pip` assumptions.
- `core/skills/solar-skill-creator/scripts/package_skill.py` now excludes local runtime folders (`.venv`, `.poetry-cache`, `__pycache__`, `.git`) from packaged `.skill` artifacts.
- `.gitignore` now includes `__pycache__/`.
- `.gitignore` now includes `.venv/` and `.poetry-cache/`.
- `core/checklist-onboarding.md` now includes on-demand `sun/` workspace health validation via `core/scripts/sun-workspace-doctor.sh` plus optional git checks.
- `core/checklist-onboarding.md` now includes on-demand `planets/*` workspace health validation via `core/scripts/planets-workspace-doctor.sh` plus optional git checks.
- `core/skills/solar-migration-playbook` now defines workspace doctor usage as on-demand in step 8, with optional git validation via `--check-git` only when needed.
- `sun/README.md` no longer references `.setup-complete` as a setup marker.

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
