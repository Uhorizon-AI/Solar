# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- feat(AGENTS.md): add Daily-log Execution Trace directive — when completing traceable work, append one line to `sun/daily-log/YYYY-MM-DD.md` with `HH:MM #tag Description → artifact`. Create file if missing. Tags: #sales #marketing #job #ops.
- feat(solar-router): integrate Cursor Agent (`agent`) as a first-class provider. Includes default command configuration with non-interactive flags (`-p`), workspace trust (`-f`), and MCP auto-approval (`--approve-mcps`).
- feat(solar-router): update `onboard_router_env.sh` and `diagnose_router.sh` to support `agent` priority, command migration, and preflight validation.
- docs(solar-router): update `SKILL.md` and `routing-policy.md` to reflect `agent` capabilities and contract v3 compliance.

### Changed
- docs(sales-pipeline): refactor sales pipeline documentation, removing obsolete `SKILL.md` and clarifying usage of `sales-record.md` and `sales-pipeline-board.md` templates for unified stage tracking.
- feat(daily-log): update `core/templates/daily-log.md` — Top 3 → Top Priorities (flexible 1–N), Bloqueos → Blockers. Aligns with execution trace and todo-list format.
- docs(orchestration-blueprint): update daily-log semantics — on demand or execution trace; format Top Priorities, Blockers, Log.

## [0.4.0] - 2026-03-01

### Added
- feat(solar-router): implement Solar-JIT (Just-In-Time) agent orchestration architecture. Includes automated agent selection, context injection, UUID-based `router_id`, and structured audit logging in `sun/runtime/router/audit.jsonl`.
- feat(solar-router): add `status_router.sh` to monitor real-time router health, in-flight processes, and execution history.
- feat(config): implement `.geminiignore` with negation patterns to whitelist `sun/` and `planets/` workspace directories while maintaining `.gitignore` compatibility.
- feat(sync-clients): add Gemini CLI support with `.md`-to-`.toml` command conversion and `.gemini/` gitignore entry.

### Changed
- config(gemini): update `.gemini/settings.json` to enable `respectGitIgnore: true` and add global ignore for `node_modules`.
- feat(core): implement Solar-JIT architecture, `.geminiignore` filtering and `sync-clients` defaults.

### Fixed
- fix(sync-clients): set `respectGitIgnore` to `true` in Gemini config by default to support the new `.geminiignore` standard.

## [0.3.0] - 2026-02-21
### Added
- feat(solar-system, solar-transport-gateway): enhance orchestrator health checks and script organization
- feat(solar-async-tasks, solar-router): introduce async task execution with structured logging and enhanced routing
- feat(solar-transport-gateway): improve tunnel recovery and environment variable handling
- feat(solar-async-tasks): add manual task activation by ID with deterministic transitions
- feat(solar-skill-creator): update script usage documentation and validation rules
- feat(solar-async-tasks): enhance task sorting by scheduled time and priority
- feat(CHANGELOG.md): update first-run protocol and enhance task management
- feat(AGENTS.md): update first-run protocol for session initialization
- feat(solar-router): enhance Gemini provider handling with improved environment setup and OAuth prompt detection
- feat(solar-async-tasks): enhance task management with UUIDs, slug-based filenames, and improved sorting
- feat(solar-async-tasks, solar-router, solar-system): enhance logging, path resolution, and environment setup
- feat(solar-async-tasks): enhance task management with logging, requeue functionality, and error handling improvements

### Fixed
- fix(execute_active.py): remove redundant import and streamline error handling
- fix(solar-async-tasks): clean up requeue_from_error.sh to remove execution error history

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
