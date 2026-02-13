# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- `CLAUDE.md` and `GEMINI.md` symlinks in all planets pointing to `AGENTS.md` for multi-client AI compatibility.
- `core/scripts/create-planet.sh` helper script to automate planet creation with proper structure (AGENTS.md template + symlinks).
- `core/templates/planet-structure.md` comprehensive guide for planet structure, resource creation, and sync workflow.
- `core/commands/solar-validate-governance.md` interactive command to verify governance coherence: AGENTS.md structure and connections, delegation chain (each layer knows only immediate delegate), and resource sync protocol consistency.
- Planet resource sync support in `core/scripts/sync-clients.sh`: automatically discovers and syncs `planets/*/skills/`, `planets/*/agents/`, `planets/*/commands/` to AI clients.
- Deterministic resource naming in `core/scripts/sync-clients.sh`: all planet resources are always prefixed as `<planet-name>:<resource-name>` (npm-style), only `core/` resources remain unprefixed.
- `core/skills/solar-async-tasks` for asynchronous task management: create drafts, plan, approve with priority (high/normal/low), queue, and run via `start_next.sh` or `run_worker.sh`. State in `sun/runtime/async-tasks/` (drafts, planned, queued, active, completed, archive). Scripts: `create.sh`, `plan.sh`, `approve.sh`, `list.sh`, `start_next.sh`, `complete.sh`, `setup_async_tasks.sh`, `verify_lifecycle.sh`, `task_lib.sh`.
- `core/skills/solar-async-tasks/scripts/run_worker.sh` to run the queue automatically: `--once` (one cycle, e.g. for cron) or loop with `--interval SECS`; clean exit on SIGINT/SIGTERM; logs failures to stderr and continues on next interval in loop mode.
- `core/skills/solar-async-tasks` scheduling: optional `scheduled_time` and `scheduled_weekdays` (ISO 1–7) in task frontmatter; `is_scheduled_now()` in task_lib with ±15 min window; `schedule.sh` to set/update schedule; `list.sh` shows schedule as `@ 10:00 L,M,X,J,V` for QUEUED/PLANNED.
- `core/skills/solar-async-tasks/scripts/add_notify.sh` to set `notify_when: completed` on a task so the user is notified when it completes.
- `core/skills/solar-async-tasks/scripts/notify_if_configured.sh` (called by `complete.sh`): if task has `notify_when: completed`, sends "Tarea completada: [title]" via Telegram using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from `.env` (optional override from `sun/preferences`). SKILL section "When to suggest async (e.g. Telegram)" for agent guidance.
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
- AI-agnostic memory protocol: `sun/MEMORY.md` (required, max 200 lines) and `planets/*/MEMORY.md` (optional, max 100 lines) for operational learnings only, stored in filesystem for access by any AI (Claude, Gemini, etc.).
- `core/templates/planet-MEMORY.md` template for planet memory files (free-form structure, domain learnings, not configuration).
- Documentation scope policy in `core/AGENTS.md`: `core/docs/` for framework documentation, `sun/docs/` for user documentation, `sun/plans/` for user-specific design decisions and implementation plans.

### Changed
- `core/skills/solar-transport-gateway` WebSocket keepalive timeouts increased from default 20s to `ping_interval=60s` and `ping_timeout=180s` in both `run_websocket_bridge.py` and `run_http_webhook_bridge.py` to prevent error 1011 (keepalive ping timeout) when AI router processing exceeds 20 seconds.
- `core/skills/solar-transport-gateway/assets/system_prompt.md` now includes async task creation workflow: describe task first, ask confirmation, execute create→plan→approve→notify flow, with explicit rule to never create async tasks without confirmation.
- `core/AGENTS.md` now includes "Planet management rule" defining when to use `create-planet.sh`, referencing `planet-structure.md`, and requiring sync execution for planet resources.
- `core/bootstrap.sh` "Next steps" now recommends using `create-planet.sh` instead of manual planet creation.
- `core/checklist-onboarding.md` "Planet Setup" now recommends `create-planet.sh` as primary method and references `planet-structure.md` for advanced resource workflows.
- `core/scripts/sync-clients.sh` now syncs resources from both `core/` and `planets/*/` (skills, agents, commands) with deterministic npm-style prefixing: all planet resources are prefixed as `<planet-name>:<resource-name>`, only `core/` resources remain unprefixed.
- `core/scripts/sync-clients.sh` now uses Bash 3.2+ compatible syntax (temp files instead of associative arrays) for macOS compatibility.
- `core/scripts/sync-clients.sh` duplicate detection (`is_duplicate`, `get_source`) now uses exact string matching (no regex, no substring) for robust handling of special characters.
- `core/templates/planet-AGENTS.md` "Planet Sync Rule" (renamed from "Resource Sync Protocol") now references `../../AGENTS.md` (root governance) instead of duplicating documentation, maintaining single source of authority.
- `core/templates/planet-AGENTS.md` now includes explicit "Governance Delegation" section documenting authority (domain-specific governance) and immediate delegation (to root).
- `AGENTS.md` (root) "Instruction Resolution" now explicitly defines Solar's three-layer governance structure (root, core, planets) instead of abstract "child files", clarifying that `sun/` is runtime storage, not a governance layer.
- `AGENTS.md` (root) "Governance Delegation" separated as own section, documenting only immediate delegation (root → core), not entire chain.
- `AGENTS.md` (root) now includes "Planet Resource Sync" section that delegates to `core/AGENTS.md` for framework operational rules.
- `core/AGENTS.md` "Governance delegation rule" (renamed from "Governance reference rule") now documents only immediate relationship (called by root), not entire governance chain.
- `core/AGENTS.md` "Governance delegation rule" now documents only immediate relationship (called by root), not entire governance chain, following minimal knowledge principle.
- `README.md` now emphasizes Solar as an "AI Operating System" with clear OS analogies (routes tasks, abstracts AI providers, manages memory, enforces governance, coordinates execution).
- All planet `AGENTS.md` files now include resource sync protocol documentation (in Spanish for Spanish planets, English for others).
- Governance delegation principle applied consistently across all AGENTS.md files: each layer knows only its immediate delegate, not the complete chain.
- `core/skills/solar-async-tasks/scripts/list.sh` now orders QUEUED by priority (high → normal → low) and by filename within each group.
- `core/skills/solar-async-tasks/scripts/create.sh` now prints the correct variable (`$FILENAME`) on task creation.
- `core/skills/solar-async-tasks/SKILL.md` updated with description (plan → approve → queue by priority → execute), workflow including run_worker, "Automatic execution (run_worker)" section, and validation commands for `run_worker.sh --once`.
- `core/skills/solar-async-tasks/scripts/start_next.sh` now only picks tasks within their scheduled window (`is_scheduled_now`); `list.sh` shows schedule for QUEUED and PLANNED when set.
- `core/skills/solar-async-tasks/SKILL.md` now includes "Scheduling (optional)", "When to suggest async (e.g. Telegram)", and "Notification (Telegram)" (default from `.env` TELEGRAM_*, optional override from sun/preferences).
- `core/skills/solar-async-tasks/scripts/complete.sh` now calls `notify_if_configured.sh` after moving a task to completed so Telegram notification is sent when the task has `notify_when: completed` and `.env` has Telegram credentials.
- `solar.code-workspace` now includes `claudeCode.respectGitIgnore: false` to enable Claude Code @ mention indexing for runtime workspaces (`sun/` and `planets/`) while keeping them in `.gitignore` for version control separation.
- `solar.code-workspace` simplified settings to minimal required configuration (removed optional `files.exclude` and `search.exclude` patterns).
- `README.md` restructured for open-source positioning of `Solar`, clearer contribution path, and commercial CTA for Uhorizon AI.
- `README.md` now includes creator attribution to Louis Jimenez and maintainer/contact links for Uhorizon AI.
- `README.md` hero copy now positions Solar as an agentic operating system for multi-AI operations by context, clarifies Sun/Planets roles, and updates audience ordering to include founders, operators, developers, and non-technical teams.
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
- `docs/assets/solar-header.svg` hero subtitle and audience text now align with the updated README positioning, including improved line breaks and visual hierarchy.
- `core/checklist-onboarding.md` now includes on-demand `sun/` workspace health validation via `core/scripts/sun-workspace-doctor.sh` plus optional git checks.
- `core/checklist-onboarding.md` now includes on-demand `planets/*` workspace health validation via `core/scripts/planets-workspace-doctor.sh` plus optional git checks.
- `core/skills/solar-migration-playbook` now defines workspace doctor usage as on-demand in step 8, with optional git validation via `--check-git` only when needed.
- `sun/README.md` no longer references `.setup-complete` as a setup marker.
- `core/AGENTS.md` "Memory protocol" now defines AI-agnostic memory structure (`sun/MEMORY.md` required, `planets/*/MEMORY.md` optional), concision rules (max 200/100 lines, free-form, only stable patterns), and first-run protocol (read `sun/MEMORY.md`, delegate to setup if missing).
- Root `AGENTS.md` "First-Run Protocol" now checks both `sun/MEMORY.md` and `sun/preferences/profile.md` before delegating to setup protocol (aligned with core).
- `core/AGENTS.md` "Setup Protocol" now invoked when `sun/MEMORY.md` or `sun/preferences/profile.md` are missing (aligned with root).
- `core/bootstrap.sh` no longer creates `sun/memories/` directory (now uses single `sun/MEMORY.md` file in root).
- `core/bootstrap.sh` now creates `sun/MEMORY.md` if missing with free-form template for operational learnings.
- `core/scripts/planets-workspace-doctor.sh` now validates `MEMORY.md` (uppercase) instead of `memory.md` (lowercase).
- `core/scripts/create-planet.sh` "Next steps" now includes optional step to create `MEMORY.md` from `core/templates/planet-MEMORY.md` template.
- `core/checklist-onboarding.md` "Planet Setup" now references `core/templates/planet-MEMORY.md` (renamed from `planet-memory-template.md`).
- `core/templates/planet-MEMORY.md` renamed from `planet-memory-template.md` for naming consistency with `planet-AGENTS.md` pattern (no `-template` suffix).

### Removed
- `core/templates/planet-memory.md` (legacy template, replaced by `planet-MEMORY.md`).
- `core/templates/sun-memory-template.md` (unused, sun/MEMORY.md created by bootstrap).

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
