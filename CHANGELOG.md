# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- `core/skills/solar-system/scripts/check_orchestrator.sh` — new single-command orchestrator health check. Reports supervisor state (plist + launchctl) and per-feature health (`transport-gateway` via `check_transport_gateway.sh`, `async-tasks` via filesystem checks). Emits `HEALTHY/PARTIAL/DOWN` verdict with exit codes `0/2/1` aligned with `check_transport_gateway.sh`. Includes portable timeout (gtimeout/timeout/bash fallback with process group kill), orphan lock detection with PID validation, and explicit output for non-numeric lock content.
- `core/skills/solar-transport-gateway/scripts/ensure_transport_gateway.sh` — moved from `solar-system/scripts/` to its owning skill. Logic (check + recovery of gateway) belongs to `solar-transport-gateway`, not to the orchestrator.

### Fixed
- `core/skills/solar-transport-gateway/scripts/check_transport_gateway.sh` — curl calls now use `--max-time 5` to prevent hanging when the HTTP bridge is slow to respond.
- `core/skills/solar-system/scripts/check_orchestrator.sh` — `FEATURE_TIMEOUT` raised to `15s` (5s curl + process overhead margin) to avoid false DOWN verdicts when the gateway is healthy but slow. Suggested actions for `PARTIAL` tunnel state now read the cloudflared log and emit a specific diagnosis: QUIC/control stream errors (transient, retry), Cloudflare registration errors (token/tunnel reconfiguration needed), auth errors, or network errors. Each case includes the exact command to run.

### Changed
- `core/skills/solar-system/scripts/solar_orchestrator.sh` renamed to `run_orchestrator.sh` to follow `verbo_objeto` naming convention. `Solar.c` wrapper updated and recompiled. LaunchAgent reinstalled.
- `core/skills/solar-router/scripts/smoke_test.sh` renamed to `check_router.sh` to follow `check_` prefix convention for health/validation scripts.
- `core/skills/solar-async-tasks/scripts/verify_lifecycle.sh` renamed to `validate_lifecycle.sh` (`validate_` for internal structure/prerequisite checks, `verify_` reserved for external state like APIs/webhooks). Header comment updated to match new purpose.
- `core/skills/solar-system/scripts/run_orchestrator.sh` now calls `ensure_transport_gateway.sh` from `core/skills/solar-transport-gateway/scripts/` (correct ownership).
- `core/skills/solar-system/SKILL.md` — updated validation commands, workflow section (3 observability commands documented with scope), and orchestrator behavior to reference `run_orchestrator.sh`.
- `core/skills/solar-transport-gateway/SKILL.md` — added `ensure_transport_gateway.sh` to validation commands.
- `core/skills/solar-router/SKILL.md` — added `check_router.sh` to validation commands.
- `core/skills/solar-async-tasks/SKILL.md` — added `validate_lifecycle.sh` to validation commands.
- `core/skills/solar-system/references/system-integration.md` — updated orchestrator entrypoint and feature dispatch paths.
- `core/skills/solar-system/scripts/diagnose_launchagent.sh` — updated `ORCHESTRATOR` variable to point to `run_orchestrator.sh`.
- `core/skills/solar-async-tasks/scripts/validate_lifecycle.sh` — permissions set to `755` (executable).
- `core/skills/solar-transport-gateway/scripts/ensure_transport_gateway.sh` — permissions set to `755` (executable).

### Removed
- `core/skills/solar-system/scripts/solar_orchestrator.sh` (renamed to `run_orchestrator.sh`).
- `core/skills/solar-system/scripts/ensure_transport_gateway.sh` (moved to `solar-transport-gateway/scripts/`).
- `core/skills/solar-router/scripts/smoke_test.sh` (renamed to `check_router.sh`).
- `core/skills/solar-async-tasks/scripts/verify_lifecycle.sh` (renamed to `validate_lifecycle.sh`).

### Added
- `core/skills/solar-async-tasks/scripts/execute_active.py` — Python executor for async tasks. Handles full I/O JSON with solar-router v3 (`channel=async-task`, `mode=direct_only`), respects per-task `provider:` frontmatter override (strict mode), writes structured logs, and moves tasks to `error/` on failure. Replaces fragile bash provider loop.
- `core/skills/solar-router/scripts/smoke_test.sh` — Executable smoke test for solar-router v3: validates JSON contract on success/failure, error codes, mode validation, async_only feature gate, execute_active.py frontmatter parsing, and parse_ai_decision_output degradation. 19 PASS, 0 FAIL, 1 SKIP (provider-dependent test skipped when no AI available).
- `core/skills/solar-async-tasks/scripts/requeue_from_error.sh` to move tasks from `error/` back to `queued/` after fixing the root cause.

### Changed
- `core/skills/solar-router/scripts/run_router.py` — **Breaking (v3).** Router is now the single source of truth for all AI execution and routing policy. Changes: (1) full contract v3 input/output JSON (adds `channel`, `mode`, `decision`, `error_code`); (2) provider selection and fallback moved from consumers into router; (3) `provider` field enables strict mode with no fallback (`error_code: provider_locked_failed`); (4) `DecisionEngine` added for `decision.kind` (`direct_reply`, `async_draft_created`, etc.); (5) `mode=async_only` bypasses AI execution entirely — creates draft by policy from user text without calling any provider; (6) `mode=auto` + AI output parsed for semantic `decision.kind` with controlled degradation to `direct_reply`; (7) async draft created via `create.sh` subprocess (no direct file writes from router); (8) output is always structured JSON (never plain text).
- `core/skills/solar-router/assets/system_prompt.md` — Updated for v3: in `mode=auto`, AI must return a JSON object with `decision.kind` and `reply_text`. Added decision rules, examples for `direct_reply` and `async_draft_created`, and hard constraints for two-step async confirmation.
- `core/skills/solar-transport-gateway/scripts/run_websocket_bridge.py` — Removed all provider selection and fallback logic. Now a pure delegate: forwards full request payload (including `channel` and `mode`) to solar-router v3 and returns structured response with minimal envelope. Preserves real `error_code` from router JSON even on non-zero exit code.
- `core/skills/solar-transport-gateway/scripts/run_http_webhook_bridge.py` — Telegram inbound now sends `channel=telegram`, `mode=auto` to WS bridge. n8n inbound sends `channel=n8n`, `mode=auto` and exposes router v3 JSON directly (no legacy `solar_status`/`solar_response` double-wrapper). Handles `decision.kind` for Telegram response routing. No local async policy or fallback.
- `core/skills/solar-async-tasks/scripts/execute_active.sh` — Refactored to lightweight wrapper: sets up paths/env, calls `execute_active.py`, and runs `complete.sh` on success. All provider logic removed from bash.
- `core/skills/solar-router/references/routing-policy.md` — Rewritten for v3: documents router as single source of truth, DecisionEngine rules table, caller mapping (`channel`/`mode` per caller), contract v3 input/output, n8n bridge output rule, and key invariants.
- `core/skills/solar-router/SKILL.md` — Updated scope, contract v3 section, DecisionEngine rules, and consumer references.
- `core/skills/solar-transport-gateway/SKILL.md` — Updated message contract to v3, channel mapping, and route pattern from `<provider>` to `<channel>`.
- `core/skills/solar-async-tasks/SKILL.md` — Updated execute_active section to document `execute_active.py` + wrapper pattern and router v3 delegation.
- `core/skills/solar-system/SKILL.md` — Added note that `SOLAR_SYSTEM_FEATURES` is also read by solar-router to gate async draft creation.
- `core/skills/solar-telegram/references/telegram-transport-patterns.md` — Updated Telegram routing notes: `channel=telegram`/`mode=auto`, `decision.kind` controls response flow, activation requires second explicit confirmation.
- `core/skills/solar-transport-gateway/references/telegram-webhook-flow.md` — Updated base endpoint pattern from `/webhook/<provider>` to `/webhook/<channel>`.

### Fixed
- `core/skills/solar-transport-gateway/scripts/run_websocket_bridge.py` and `core/skills/solar-async-tasks/scripts/execute_active.py` — Structured router v3 JSON errors (real `error_code` like `unsupported_provider`, `invalid_mode`, `provider_locked_failed`) are now preserved when router exits with code 1. Previously overwritten with generic `router_error`, breaking trazability. Only falls back to `router_crashed` when stdout is not parseable JSON at all.
- `core/skills/solar-router/scripts/run_router.py` — `mode=async_only` no longer fails with `all_providers_failed` when AI providers are unavailable. Draft is now created by policy from user text without any provider call.
- `core/skills/solar-transport-gateway/SKILL.md` — Removed internal solar-router details (system prompt path, conversation JSONL, override env keys) from "Conversation continuity" section. Delegate skills must not document the internals of the skill they delegate to. Section now reads: "Managed entirely by `solar-router`."

### Changed
- `core/skills/solar-skill-creator/SKILL.md`: scripts guidance changed from fixed section format to a documentation rule (if `scripts/` exists, explain usage somewhere in `SKILL.md`).
- `core/skills/solar-skill-creator/scripts/package_skill.py`: removed hard requirement for `## Scripts`; now validates script-usage coverage only when `scripts/` has files; keeps `## Required MCP` required and `## Fallback if MCP missing` conditional.
- `core/skills/solar-skill-creator/scripts/package_skill.py`: line-count warning (>500) is non-blocking.
- `core/skills/solar-skill-creator/scripts/init_skill.py`: template aligned to the new scripts documentation rule (no rigid scripts section).
- `core/skills/solar-sales-pipeline/SKILL.md`: added `## Required MCP` with `None`.
- **Root `AGENTS.md`** — Introduced a single **First-Run / Session start Protocol (Required)** at the top: mandatory read order at session start is (1) this file, (2) `sun/preferences/profile.md` (who you are talking to), (3) `sun/MEMORY.md` (context and learnings). Removed duplicate "First-Run Protocol" and "Memory (Required)" sections; memory behaviour remains defined only in `core/AGENTS.md` (Memory protocol). Ensures agents always load profile and memory before the first reply.
- `core/skills/solar-async-tasks/scripts/task_lib.sh` now generates unique task IDs using UUIDs (via `uuidgen`, `openssl`, or timestamp fallback) instead of timestamp-based IDs (`YYYYMMDD-HHMM`); adds `created_epoch()` function for extracting created timestamps from task metadata with ISO8601 parsing and file mtime fallback; adds `slugify()` and `build_task_filename()` for human-readable filenames without ID prefix; adds `task_basename_exists()` for collision detection across all task directories and logs; updates `find_task()` to search by metadata `id` field instead of filename pattern matching.
- `core/skills/solar-async-tasks/scripts/create.sh` now uses `build_task_filename()` to generate clean slug-based filenames (e.g., `sample-task.md`) instead of ID-prefixed names.
- `core/skills/solar-async-tasks/scripts/setup_async_tasks.sh` now uses `build_task_filename()` for sample task creation.
- `core/skills/solar-async-tasks/scripts/list.sh` now uses `extract_meta()` consistently across all task sections (DRAFTS, PLANNED, ACTIVE, COMPLETED, ERROR, ARCHIVE) instead of direct `grep | cut` parsing; QUEUED section now orders by priority (high > normal > low) then by created timestamp ascending (FIFO) for deterministic queue behavior.
- `core/skills/solar-async-tasks/scripts/start_next.sh` now orders queued tasks by priority descending then created timestamp ascending (FIFO) using `created_epoch()` for deterministic task selection.
- `core/skills/solar-async-tasks/scripts/verify_lifecycle.sh` now runs in isolated temporary directory (`mktemp`) to avoid interfering with real runtime data; adds explicit validation of `start_next.sh` output; uses `set -euo pipefail` for strict error handling; includes trap for automatic cleanup.
- `core/skills/solar-async-tasks/scripts/requeue_from_error.sh` now removes the `## Execution Error` block when requeueing (clean slate for manual requeue); usage example now shows UUID format instead of timestamp format.
- `core/skills/solar-system/scripts/status_launchagent_macos.sh` now includes `print_tail_with_timestamps()` function to propagate timestamps from structured log entries to continuation lines in stderr output (last 10 lines).
- `core/skills/solar-async-tasks/scripts/execute_active.sh` now writes one flat log per task (`logs/<task-file>.log`), overwriting on each run to keep last execution state, and includes structured metadata for success/error outcomes.
- `core/skills/solar-async-tasks/scripts/task_lib.sh` now provides `setup_logging()` and `cleanup_old_logs()` (7-day log retention) used by async task execution; `cleanup_old_logs()` log message wrapped in explicit `if` for clarity.
- `core/skills/solar-router/scripts/run_router.py` now uses `FALLBACK_PATHS` to resolve provider CLIs when the process PATH is minimal (e.g. LaunchAgent); resolves to absolute path and uses it for execution; Claude invocation adds `--no-session-persistence`; Gemini invocation now adds `-p`, sets default non-interactive auth env (`GEMINI_CLI_HOME`, `GEMINI_FORCE_ENCRYPTED_FILE_STORAGE`), and fails fast when Gemini returns OAuth prompts with exit code 0; "client not found" error message includes current PATH for debugging.
- `core/skills/solar-system/scripts/solar_orchestrator.sh` now exports a deterministic baseline PATH (`/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`, `/bin`, `/usr/sbin`, `/sbin`) at startup so provider CLIs are discoverable when run from LaunchAgent.
- `core/skills/solar-async-tasks/scripts/list.sh` now shows `error/` task detail paths and resolves execution error time from the latest `## Execution Error` block when frontmatter timestamps are absent.
- `core/skills/solar-async-tasks`: QUEUED list order now includes `scheduled_time` — tasks sort by priority (high > normal > low), then by scheduled time (e.g. 09:00 before 09:30), then by created (FIFO). `task_lib.sh` adds `scheduled_minutes()` to convert frontmatter `scheduled_time` (HH:MM or HH:MM:SS) to minutes since midnight for sorting; tasks without schedule sort after scheduled ones (9999).
- `core/skills/solar-async-tasks/SKILL.md` updated to document manual requeue flow from `error/`, one-log-per-task behavior, retention cleanup, and explicit runtime folder semantics (`drafts/planned/queued/error/archive`).
- `solar.code-workspace` now sets `git.repositoryScanMaxDepth: 3` to improve multi-repo discovery in nested workspace layouts.

## [0.2.0] - 2026-02-16
### Added
- feat(docs): update AGENTS.md and related templates for resource synchronization
- feat(solar-router): update documentation and scripts for provider diagnostics
- feat(solar-router): add diagnose_router.sh script for preflight checks of AI providers
- feat(solar-async-tasks): enhance task provider handling and unique ID generation
- feat(solar-system): enhance launchd plist rendering and task library functionality
- feat: refactor AI provider routing to use solar-router, update documentation and scripts accordingly
- feat(solar-router): implement solar-router skill with provider management and environment setup
- feat(transport-gateway): enhance process management and environment setup scripts
- feat(solar-system): switch launchd to Solar entrypoint and align logging
- feat: Implement solar-system orchestration with LaunchAgent support and related scripts
- feat: Enhance task management with hooks and recurring support

### Fixed
- fix(solar-async-tasks): trim whitespace from task provider strings in execute_active.sh
- fix(websocket-bridge): improve error handling and logging for provider execution failures


### Added
- `core/skills/solar-router` — Shared router for AI provider execution with Solar repo context, extracted from solar-transport-gateway. Includes run_router.py, diagnose_router.sh, onboard_router_env.sh, routing policy v2, and system prompt assets.
- `core/skills/solar-system/scripts/Solar.c` C wrapper source for the Solar launchd entrypoint binary.
- `core/skills/solar-system/scripts/diagnose_launchagent.sh` one-pass diagnostic script for LaunchAgent bootstrap issues.
- `core/skills/solar-system/scripts/set_icon.swift` helper to apply custom icon metadata to the Solar entrypoint binary.
- `core/skills/solar-system/scripts/svg2png.swift` helper to render SVG icons into PNG assets for `.icns` generation.
- `core/skills/solar-system/assets/solar-icon.svg` source icon used to build Solar system icon assets.
### Changed
- `core/templates/planet-AGENTS.md` — Replaced minimal sync rule with full Planet Sync Rule: verification checklist (Agents, Commands, Skills, Request Routing, Ownership matrix), sync command, and when to sync; corrected prefix description to "planet resources always prefixed" (matches sync-clients.sh).
- `core/templates/planet-structure.md` — Added "Update AGENTS.md" step to Creating a Skill/Agent/Command; added Commands to Resource Sync checklist and Best Practices.
- `core/scripts/create-planet.sh` — Next steps: added step 4 "keep AGENTS.md in sync (Agents, Commands, Skills, Request Routing)" when adding resources.
- `core/bootstrap.sh` — Next steps: "keep AGENTS.md in sync" when adding planet resources.
- `core/scripts/sync-clients.sh` — Header comment: corrected naming (core unprefixed, planets/* always prefixed); removed obsolete "conflict resolution" wording.
- Unified AI router variable naming to `SOLAR_ROUTER_*` prefix (removed `_AI_` infix for clarity and consistency).
- `core/skills/solar-router/scripts/run_router.py` default runtime directory changed from `sun/runtime/transport-gateway` to `sun/runtime/router`.
- `core/skills/solar-transport-gateway/scripts/run_websocket_bridge.py` now reads `SOLAR_ROUTER_PROVIDER_PRIORITY` and `SOLAR_ROUTER_TIMEOUT_SEC` with automatic fallback to legacy variable names for backward compatibility.
- `core/skills/solar-async-tasks/scripts/execute_active.sh` now reads `SOLAR_ROUTER_PROVIDER_PRIORITY` with automatic fallback to legacy `SOLAR_AI_PROVIDER_PRIORITY`.
- Router timeout alignment: provider timeout default 300s, bridge/consumer timeout default 310s to prevent race conditions.
- `core/skills/solar-router/scripts/diagnose_router.sh` (router provider preflight/diagnostic): added `--verbose` for full error output on provider failure; all references in solar-router, solar-async-tasks, and solar-transport-gateway point to this script.
- `core/skills/solar-async-tasks/scripts/execute_active.sh` now records per-provider errors (last 15 lines each) in task error files and logs "Trying provider: X" / "→ X: OK|FAIL" to stderr for easier debugging.
- All skill documentation updated to use `SOLAR_ROUTER_*` naming exclusively, with legacy variables documented only in migration table.
- `core/skills/solar-skill-creator/SKILL.md` now requires a short `System activation` subsection for skills designed to run via `solar-system` (feature token, install/status commands, and ownership pointer).
- `core/skills/solar-system/assets/com.solar.system.plist.template` now executes a single Solar entrypoint binary (`scripts/Solar`) from `ProgramArguments` for launchd compatibility.
- `core/skills/solar-system/scripts/install_launchagent_macos.sh` now enables the launchd label before bootstrap to recover from disabled overrides.
- `core/skills/solar-system/scripts/install_launchagent_macos.sh` now defaults logs to `~/Library/Logs/com.solar.system/`, ensures log paths exist before bootstrap, compiles the Solar wrapper entrypoint, and applies a custom icon when available.
- `core/skills/solar-system/scripts/render_launchagent_plist.sh` now renders the Solar wrapper entrypoint path and aligns default log paths with `~/Library/Logs/com.solar.system/`.
- `core/skills/solar-system/scripts/status_launchagent_macos.sh` now reads the same default log paths used by install/render scripts (`~/Library/Logs/com.solar.system/`).
- `core/skills/solar-system/scripts/uninstall_launchagent_macos.sh` no longer leaves a persistent `disabled` override on the launchd label.
- `core/skills/solar-system/assets/com.solar.system.plist.template` now sets `WorkingDirectory` to repo root so launchd runs the Solar process with correct cwd.
- `core/skills/solar-system/scripts/render_launchagent_plist.sh` now substitutes `__WORKING_DIRECTORY__` from REPO_ROOT when rendering the plist.

### Fixed
- Documentation: prefix rule described "on conflict" but sync-clients.sh always prefixes planet resources; corrected across templates.
- Added Commands to verification checklists where missing (planet-AGENTS.md, planet-structure.md, create-planet.sh).
- `core/skills/solar-async-tasks/scripts/task_lib.sh`: `extract_meta` no longer causes script exit when a frontmatter key is missing (grep in subshell with `|| true` to avoid pipefail exit in `start_next.sh` and other callers).
- `core/skills/solar-async-tasks/scripts/task_lib.sh`: `SOLAR_TASK_ROOT` default now prefers `$(pwd)/sun/runtime/async-tasks` when that path exists, so async-tasks runs correctly under LaunchAgent when cwd is repo root.
- `core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh` now resolves `poetry` and `curl` robustly in LaunchAgent contexts (minimal PATH), preventing false `Missing dependency: poetry` failures during `solar-system` ticks.

### Removed
- `core/skills/solar-transport-gateway/references/ai-routing-policy.md` (moved to solar-router/references/routing-policy.md)
- `core/skills/solar-transport-gateway/scripts/check_ai_providers.sh` (moved to solar-router/scripts/diagnose_router.sh)
- `core/skills/solar-transport-gateway/scripts/run_ai_router.py` (moved to solar-router/scripts/run_router.py)

## [0.1.0] - 2026-02-13
### Added
- feat(release): add semi-automated release creation workflow
- feat: implement AI-agnostic memory protocol and update related documentation
- feat: enhance WebSocket keepalive settings and document async task creation workflow
- feat: implement planet management features including automated creation, resource sync, and governance validation
- feat: enhance async task notifications and scheduling
- feat: enhance scheduling capabilities for async tasks
- feat: introduce solar-async-tasks for managing asynchronous tasks
- feat: add on-demand workspace doctors with optional git checks
- feat(core): add solar migration playbook skill
- feat(transport-gateway): add conversation continuity and stable runtime path

### Fixed
- fix(release): handle multiline changelog entries in awk



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
- `core/commands/solar-create-release.md` interactive command for creating framework releases with semantic versioning and automatic changelog generation.
- `core/scripts/create-release.sh` semi-automated release script: analyzes commits (Conventional Commits), proposes version bump (MAJOR/MINOR/PATCH), generates CHANGELOG entry, asks confirmation, creates tag and commit, optional push with `--push` flag.

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
- `CONTRIBUTING.md` now includes "Creating a Release" section documenting semantic versioning workflow and Conventional Commits format for maintainers.
- `README.md` now includes "Development" section for maintainers with release creation reference.

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
