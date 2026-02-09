# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- `CONTRIBUTING.md` with contribution scope, architecture boundaries, and changelog policy.
- `CHANGELOG.md` to track notable framework changes.
- `core/skills/solar-migration-playbook` to plan and execute phased migrations from existing folders/repos into Solar (`core/sun/planets`) with a reusable mapping template.
- `core/checklist-agents-validation.md` with practical tests for routing, hierarchy, first-run UX, onboarding, and ambiguity handling.
- `core/scripts/sync-clients.sh` to sync Solar core skills/agents/commands to local AI clients (`.codex`, `.claude`, `.cursor`).
- `core/mcp-catalog.md` as baseline documentation for MCP purpose, usage, and adoption journey.
- `core/scripts/check-mcp.sh` to validate required MCP declarations from a skill against local Codex MCP configuration.
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
- Root `AGENTS.md` now defines instruction-resolution priority (`nearest child AGENTS.md` wins by path scope).
- Root `AGENTS.md` first-run protocol now uses non-technical UX with simple menu options (`configure now`, `already configured`, `help`).
- Root `AGENTS.md` now requires explicit scope clarification before writing when user requests are ambiguous.
- `core/AGENTS.md` now requires running `bash core/scripts/sync-clients.sh` after changes in `core/skills/`, `core/agents/`, or `core/commands/`.
- `core/AGENTS.md` now defines `core/` self-management: agent executes scripts across `core/**` (including skill scripts) based on `SKILL.md` triggers/workflows, asking users only for inputs/secrets, blocked permissions, or high-risk actions.
- `core/AGENTS.md` now defines a global `.env` policy for env-aware skills: skill-scoped header comment plus compact contiguous variable blocks without blank lines.
- `core/AGENTS.md` now defines a host availability note policy for runtime-host dependent skills (webhook/bridge/server/tunnel), requiring a short optional laptop runtime note only where relevant.
- `core/AGENTS.md` now requires per-skill validation with `package_skill.py` whenever a skill under `core/skills/` is modified.
- `core/bootstrap.sh` now runs `core/scripts/sync-clients.sh` when available to keep local clients aligned after setup.
- `core/bootstrap.sh` now writes `sun/.setup-complete` and root `AGENTS.md` uses it as setup fast-path to avoid repeated first-run setup prompts across new conversations.
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
