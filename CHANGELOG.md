# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added
- feat(solar-security): `sanitize_context.py` accepts a positional `target` (file, directory, or `-` for stdin) with recursive **in-place** directory sanitization; optional `--extensions` for suffix filtering; summarizes `sanitized_files` / `scanned_files`.
- feat(governance): add root-level preference update delegation in `AGENTS.md` so explicit user profile/context changes are delegated to core protocol execution.
- feat(governance): add `Profile Sync Protocol (required)` to `core/AGENTS.md` with trigger conditions, execution steps, and guardrails for `sun/preferences/profile.md` and `sun/MEMORY.md` synchronization.
- feat(solar-security): add `core/skills/solar-security/scripts/sanitize_paths.py` to rename tokenized filenames and update markdown links with dry-run support and optional mapping-based replacements.
- test(solar-security): add `core/tests/skills/solar-security/test_sanitize_paths.py` covering dry-run behavior, apply mode rename/link rewrites, and mapping-driven rules.

### Changed
- docs(solar-security): extend `sanitize_context.py` CLI and `SKILL.md` usage for directory mode (aligned naming with `sanitize_paths.py`'s `target`).
- chore(governance): move `Preference Update Delegation (Required)` section in root `AGENTS.md` next to governance delegation for clearer root-to-core ownership flow.
- docs(solar-security): document `sanitize_paths.py` usage in `core/skills/solar-security/SKILL.md`, including dry-run, apply mode, explicit overrides, and single-file execution.

### Fixed
- fix(solar-security): persist `"CUSTOM"` from `sun/runtime/security-map.json` across `sanitize_context.py` runs alongside existing `REGEX` / literal passthrough keys.
- fix(sync-clients): enforce strict mirror sync for managed client folders (`skills`, `agents`, `commands`) by pruning stale entries before sync across `.cursor`, `.claude`, `.codex`, and `.gemini`.
- fix(sync-clients): harden Gemini command sync cleanup to remove stale non-`.toml` leftovers in `.gemini/commands` and keep only index-backed generated command files.

## [0.7.0] - 2026-04-09
### Added
- feat: enhance task creation script with new options and improved usage documentation
- feat: allow immediate task execution with scheduled time set to "now"
- feat: implement subtask handling with re-queueing and dependency management
- feat: enhance create-planet script and templates for code repository support
- feat: add Ollama provider support and update related documentation
- feat: disable python terminal environment activation in synchronized VS Code settings

### Fixed
- fix(governance): prohibit identity data in MEMORY.md and update changelog
- fix: update script permissions for diagnose_router.sh and setup_ollama.sh



### Added
- feat(sync-clients): include `python.terminal.activateEnvironment: false` in `.vscode/settings.json` synchronization to ensure consistent terminal behavior.
- feat(solar-async-tasks): implement subtask handling with re-queueing and dependency management — `await_subtasks.sh`, parent re-queue logic, and `subtasks:` frontmatter field. Includes 119-line test suite in `core/tests/skills/solar-async-tasks/`.
- feat(solar-async-tasks): allow immediate task execution by setting scheduled time to `"now"` — `task_lib.sh` treats `"now"` as always-eligible; test coverage added.
- feat(solar-async-tasks): enhance `create.sh` with priority, scheduled time, body-file input, and direct-queue options; improved usage documentation.
- feat(solar-router): add Ollama provider — `scripts/providers/ollama.py`, `assets/ollama_prompt.md`, `setup_ollama.sh` setup script, and 38 new unit tests in `test_providers.py`.
- feat(create-planet): extend `create-planet.sh` and templates for code repository support — adds `planet-CONTRIBUTING.md` template and updates `planet-AGENTS.md` and `planet-structure.md`.
- feat(docs): revamp `README.md` layout with improved descriptions, use cases, and SVG provider assets (Claude, Codex, Gemini, Cursor, Ollama, VS Code).
- feat(AGENTS.md): clarify async task creation as the required path for tasks needing external resources.

### Changed
- refactor(solar-async-tasks): replace ad-hoc `sed` metadata writes with a `set_meta` function in `task_lib.sh` — used by `activate.sh`, `complete.sh`, and `start_next.sh`.
- refactor(solar-transport-gateway): update environment variable sourcing and script paths to use repository root for consistency across all bridge and tunnel scripts.

### Fixed
- fix(solar-router): set executable permissions (`755`) on `diagnose_router.sh` and `setup_ollama.sh`.
- fix(governance): prohibit identity data (user name, assistant name) in `MEMORY.md` — names belong exclusively in `sun/preferences/profile.md`. Stale references were persisting when actors renamed after initial onboarding. Adds **Identity Data Isolation Rule** and **Profile Update Protocol** to `core/onboarding-conversation-contract.md`; updates `core/AGENTS.md` memory protocol with explicit prohibition. Closes #1.

### Docs
- docs(solar-code): update `SKILL.md` and `task-spec.md` for clarity and structure improvements.
- docs(solar-code): standardize workflow to use `CONTRIBUTING.md` as the repo policy file; add CHANGELOG update requirement to `repo-policy.md`.

## [0.6.0] - 2026-03-29

### Added
- feat(core/tests): centralized skill unit tests under `core/tests/skills/<skill-name>/` with `core/tests/pyproject.toml` + `uv.lock` (pytest via `uv run --project core/tests …`); `core/AGENTS.md` documents the policy.
- feat(solar-skill-creator): exclude `tests/` directories from `.skill` zip packaging so skill archives stay minimal.
- feat(solar-interface): add thread deletion with stale-run cleanup and router conversation cleanup so interface and router state stay aligned.
- feat(transport-gateway): add async n8n HTTP polling flow (`202` + `poll_url`) to avoid proxy/origin timeout failures on long router runs.

### Changed
- refactor(solar-router): move unit tests from `core/skills/solar-router/tests/` to `core/tests/skills/solar-router/` with `conftest.py` for `scripts/` import path.
- refactor(solar-router): restore `read_system_prompt` and `resolve_jit_context`, keep the thin dispatcher design, and switch `auto` routing from JSON decision payloads to `<solar_decision>` / `<solar_summary>` tag parsing.
- refactor(solar-interface): align thread context and router persistence around thread IDs, strip Solar tags from SSE/user-visible output, and export `.env` values to subprocesses for provider consistency.
- refactor(providers): standardize provider execution around `REPO_ROOT`, keep Codex JSON-event streaming, and remove the unvalidated Gemini environment workaround.

### Fixed
- fix(solar-router): bring router behavior back in line with the documented JIT contract after the thin-dispatch refactor regression.
- fix(transport-gateway): keep the HTTP webhook bridge usable without waiting on long-running router responses behind Cloudflare/proxy timeouts.

## [0.5.0] - 2026-03-27

### Added
- feat(sync-clients): add `sync_vscode` function to automatically discover and register all planet repositories in `.vscode/settings.json` (`git.scanRepositories`).
- feat(sync-clients): add `--vscode-only` flag to allow targeted workspace configuration updates.
- feat(sync-clients): implement a modern, minimalist tree-view output (`↳`) that summarizes resource counts instead of listing every file.
- feat(config): update `.gemini/settings.json` to explicitly include all planet directories, ensuring full context visibility despite `respectGitIgnore` being enabled.
- feat(solar-router): add `scripts/providers/` package — `BaseProvider` with `resolve_binary`, `get_cmd`, `prepare_env`, `clean_output`, `run`. Adapters: `ClaudeProvider` (static cmd), `CodexProvider` (REPO_ROOT-anchored cmd), `GeminiProvider` (ANSI strip + OAuth guard), `AgentProvider` (workspace-anchored cmd). All `SOLAR_ROUTER_{PROVIDER}_CMD` overrides resolved in `BaseProvider.get_cmd`.
- feat(solar-router): add unit test suite in `tests/` — `test_providers.py` (20 tests, subprocess mocked), `test_router.py` (37 tests, all logic paths without real AI), `test_run_router.py` (21 contract tests). 78 tests total, no real AI binaries needed.
- feat(solar-router): expand `check_router.sh` smoke tests from 10 to 14 — adds `provider_locked_failed` (mock binary), `all_providers_failed` (mock binary, priority exhaustion), `async_only` success path, and audit early-exit bug guard (Test 14). Test 4 rewritten with mock provider to eliminate real AI dependency and prevent hangs.
- feat(core/AGENTS.md): add Skill governance rule — `core/skills/` changes governed by `solar-skill-creator`; `solar-code` applies exclusively to planet-operated repos.
- feat(solar-code): add `core/skills/solar-code/` — Solar-native protocol for local code modifications. Includes `SKILL.md` with canonical flow (intention → triage → local change → human review), three triage levels (micro/standard/multi-repo), and repo adoption contract. References: `task-spec.md`, `repo-policy.md`, `local-review-guide.md`.
- feat(solar-interface): add `core/skills/solar-interface/` — daemon-backed local interface layer with `SKILL.md`, SQLite schema (`references/001_initial.sql`), setup/onboarding scripts, health/status commands, and a local API server for thread/run management.
- feat(solar-interface): add interactive `solar` CLI + REPL workflow — supports daemon setup, command help/versioning, chat sessions with thread creation, provider management, usage tracking, and improved server-side context handling.
- feat(solar-router): add streaming support across router/provider layer — `route_stream()` and provider adapters now expose streamed execution paths for Claude, Codex, and Gemini while preserving the structured router contract.
- test(solar-router): add unit coverage for `resolve_jit_context` and provider streaming paths in `test_router.py` and `test_providers.py`.

### Changed
- refactor(solar-router): split monolithic `run_router.py` into three layers — `router.py` (provider-agnostic core: parse, validate, JIT, prompt, decision engine), `scripts/providers/` (four adapters: claude, codex, gemini, agent via `BaseProvider`), and `run_router.py` (thin entrypoint: stdin → `route()` → stdout + exit). Public contract v3 unchanged.
- refactor(solar-code): restrict scope to planet-operated repos only — `core/skills/` changes are governed by `solar-skill-creator`, not `solar-code`. Updated `SKILL.md`, `references/repo-policy.md`, and `core/AGENTS.md` (new Skill governance rule). Removes all references to `core/` as a valid solar-code target.
- feat(solar-system): extend orchestrator and health checks with `interface` feature support — `run_orchestrator.sh`, `check_orchestrator.sh`, `SKILL.md`, and `system-integration.md` now treat the local interface as a first-class managed runtime alongside existing features.
- feat(sync-clients): update `.vscode/settings.json` during sync to register planet repos in `git.scanRepositories` and ignore the `planets` root scan folder. Improves multi-repo discovery in VS Code/Cursor workspaces.
- chore(.gitignore): group editor ignores under IDE section and move `.vscode/` and `.agents/` to keep workspace settings out of framework version control.

### Fixed
- fix(sync-clients): add spacing to emoji-prefixed labels (Settings/Setup) in console output for better readability.
- fix(solar-router): replace `datetime.datetime.utcnow()` with `datetime.datetime.now(datetime.timezone.utc)` in `audit_log` — eliminates DeprecationWarning in Python 3.12+.
- fix(solar-system): translate `check_orchestrator.sh` suggested actions to English — all diagnostic messages now consistent with `core/` language policy.
- fix(gemini): remove unnecessary prompt flags from router command execution and improve subprocess error handling in `scripts/providers/gemini.py`.

### Docs
- docs(solar-router): update `SKILL.md` and `routing-policy.md` with internal architecture section — layer contract table (entrypoint / router core / provider adapters), adapter location, unit test command. Known bug note updated: removes "pending Orchestrator/Executor refactor" reference (refactor complete); bug now tracked via Test 14 in `check_router.sh`.

---

### Added
- feat(AGENTS.md): add Daily-log Execution Trace directive — when completing traceable work, append one line to `sun/daily-log/YYYY-MM-DD.md` with `HH:MM #tag Description → artifact`. Create file if missing. Tags: #sales #marketing #job #ops.
- feat(solar-router): integrate Cursor Agent (`agent`) as a first-class provider. Includes default command configuration with non-interactive flags (`-p`), workspace trust (`-f`), and MCP auto-approval (`--approve-mcps`).
- feat(solar-router): update `onboard_router_env.sh` and `diagnose_router.sh` to support `agent` priority, command migration, and preflight validation.
- docs(solar-router): update `SKILL.md` and `routing-policy.md` to reflect `agent` capabilities and contract v3 compliance.

### Changed
- feat(solar-router): consolidate timeout configuration to a single `SOLAR_ROUTER_TIMEOUT_SEC` variable. `run_router.py`, onboarding, and router docs now use one end-to-end timeout contract; the legacy provider-specific timeout key was removed.
- feat(sync-clients): recursive discovery of planet skills via `find -path "*/skills/*/SKILL.md"` — supports nested structures (e.g. `pm-*/skills/*` in phuryn). Planet skills no longer limited to `planets/*/skills/*`. Uses `LC_ALL=C sort` for deterministic collision resolution across locales.
- feat(daily-log): Log section from list to table format (Time | Tags | Description). Tags without `#` (sales, marketing, job, ops). Order: newest first — insert new rows at top. Artifact as markdown link mandatory in Top Priorities, Blockers, and Log for easy opening. `core/templates/daily-log.md` and AGENTS.md updated. Legacy list format deprecated.
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
