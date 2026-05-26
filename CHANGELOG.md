# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

## [0.11.0] - 2026-05-25

### Added
- feat(solar-client): `solar client update` — global install update via git (full `SOLAR_ROOT` repo) or `--bundle` (core/ only).
- feat(solar-client): `client_update.sh` with backup under `$SOLAR_ROOT/backups/`, `--tag`, `--repair` (OneDrive manifest), `--check` report.
- feat(solar-client): `test_client_update.sh` unit tests for update helpers.
- feat(solar-router): audit `end` event on failed routes after early-exit (fixes stale in-flight).
- feat(solar-router): `status_router.sh --stale-count` for compact status.

### Changed
- change(solar-client): `client_doctor --strict` fails on manifest drift after global update.
- change(solar-interface): `solar status` shows router stale in-flight count; `--verbose` adds MCP path hint.
- change(solar-interface): bump CLI `SOLAR_VERSION` to `0.11.0`.
- change(solar-client): `smoke-solar-client.sh` runs `update --check`, update unit test, and `--bundle` fixture.

### Fixed
- fix(solar-router): `route()` writes audit `end` on `async_only` disabled and provider failures (Test 14).

## [0.10.1] - 2026-05-25

### Added
- feat(solar-client): extend `solar client upgrade` with install-root report, prune of IDE/agent artifacts under `SOLAR_ROOT`, and optional `--restructure` for legacy monorepo layouts.
- feat(solar-client): `test_client_upgrade.sh` unit tests for install prune helpers.

### Changed
- change(solar-client): `client_doctor` warns when pruneable artifacts exist under `SOLAR_ROOT` (hint: `solar client upgrade`).
- change(solar-interface): bump CLI `SOLAR_VERSION` to `0.10.1`.
- change(solar-client): `smoke-solar-client.sh` runs upgrade unit test and isolated install prune check.

### Fixed
- fix(solar-client): `smoke-solar-client.sh` canonicalizes `INSTALL_ROOT` before `SOLAR`, `RESOLVE`, and unit-test paths (relative arg e.g. `solar` works).

## [0.10.0] - 2026-05-25

### Added
- feat(solar-client): Fase 1.1 — `solar client upgrade` (workspace layout, removes obsolete `.solar/core/`, writes `solar-client-v1.1` manifest).
- feat(solar-client): `client_lib.sh` shared manifest/version helpers; `solar client update --check` compares global vs workspace manifest.
- feat(solar-client): `smoke-solar-client.sh` go/no-go for manifest-only workspaces.

### Changed
- change(solar-client): two-path model — `SOLAR_WORKSPACE` (active agent) + `SOLAR_ROOT` (install root containing `core/`); `resolve_solar_paths.sh` replaces `resolve_solar_home.sh`; removed `SOLAR_HOME`, `REPO_ROOT`, `SOLAR_CORE_ROOT`.
- change(solar-client): `client_init` no longer copies framework into `.solar/core/`; `--from-dev` removed.
- change(solar-client): `client_sync` updates `manifest.synced_at` and `core_version` after IDE sync.
- change(solar-client): `client_doctor` validates manifest v1.1, drift vs global client, `.env` tracked in git → FAIL.
- change(solar-interface): `solar paths` references global `@core/skills/` (no `.solar/core/` alias).
- change(solar-system): `solar_system_bind_workspace` fixes resolver exports lost in `$(solar_system_repo_root)` subshell.
- change(solar-interface): bump CLI `SOLAR_VERSION` to `0.10.0`.

### Removed
- remove(solar-client): embedded `.solar/core/` vendor layout and `init --from-dev` workspace bundling (use `solar client upgrade` on v0.9.0 workspaces).
- remove(solar-client): obsolete `smoke-solar-client-fase1.sh` and `smoke-solar-client-v1.1.sh` (consolidated into `smoke-solar-client.sh`).

### Fixed
- fix(solar-system): LaunchAgent plist exports `SOLAR_WORKSPACE` and `SOLAR_ROOT` for `Solar.c` wrapper.
- fix(solar-interface): chat/stream invoke router via resolved `ROUTER_SCRIPT` under `SOLAR_ROOT/core/`.
- fix(solar-transport-gateway): gateway scripts bind active workspace via `solar_resolve_paths` (not install root as workspace).
- fix(solar-router): `diagnose_router.sh` and `check_router.sh` resolve cwd workspace + `SOLAR_ROOT` for router/async paths.
- fix(solar-browser): `check_browser.sh` and `ensure_browser.sh` load `.env` from active workspace.
- fix(solar-interface): REPL skill discovery uses `SOLAR_ROOT/core/skills` on v1.1 workspaces.

## [0.9.0] - 2026-05-24

> **Release note:** Solar Client Fase 1 lives here until go/no-go closes the phase; then promote this section to `[0.8.2]` (or `[0.9.0]`). Tag `v0.8.1` covers release-script fixes only, not Fase 1.

### Added
- feat(solar-client): add `core/scripts/smoke-solar-client-fase1.sh` go/no-go smoke (#11–#17, inline #13, stderr on failure).
- feat(solar-client): add `resolve_solar_home.sh` with `.solar/core` + legacy `core/` discovery, export conflict detection, and `--home` override.
- feat(solar-client): add `solar client init|sync|doctor`, `solar status` (5 blocks), and `solar paths` via the `solar` CLI.
- feat(solar-client): add `package_solar_bundle.sh` allowlisted bundling and `client_init.sh --from-dev` for new workspaces.
- feat(solar-client): add workspace templates `workspace-AGENTS.md` and `workspace.env.example`.

### Changed
- change(solar-interface): resolve `SOLAR_HOME` / `SOLAR_CORE_ROOT` / `REPO_ROOT` in interface, router, sync-clients, doctor, and async-tasks.
- change(sync-clients): read skills/agents/commands from `SOLAR_CORE_ROOT`; exclude `.solar/` in VS Code/Cursor settings during sync.
- change(solar-interface): bump CLI `SOLAR_VERSION` to `0.8.1`.

### Fixed
- fix(tests): `test_resolve_solar_home.sh` captures output without `$(...)` subshell; `_assert_run` uses `|| code=$?` (bash `if` clears exit status).
- fix(sync-clients): `sync_vscode` no longer exits 1 on workspaces with an empty `planets/` dir (`ls` + `pipefail` under `set -e`).
- fix(smoke): Phase 1 smoke script counts PASS/FAIL in `#11`/`#12` blocks (no subshell); Summary matches printed `FAIL:` lines.
- fix(solar-interface): `solar status` system block no longer false-WARN when LaunchAgent is loaded (`status_launchagent` exit code vs pipefail).
- fix(solar-interface): `solar client doctor` treats ports in use by solar-interface / solar-transport-gateway as OK (health check, pid file, process args).
- fix(solar-interface): `solar_paths.py` always runs shell resolver (no stale `SOLAR_HOME` bypass); router status/list_providers always resolve from cwd.
- fix(solar-interface): `client_init` preserves existing governance files unless `--force-governance` (backup before replace).
- fix(solar-interface): resolver errors always print to stderr even with `--quiet`.
- fix(solar-interface): `solar status` adds `client` block for symlink/port WARNs; fixes Python IndentationError in chat payloads.
- fix(solar-interface): `solar paths` shows `.solar/core/skills/` on new workspaces; resolver tests count PASS/FAIL correctly.

## [0.8.1] - 2026-05-24

### Docs
- docs(changelog): consolidate duplicated `0.8.0` release notes into a single Added/Changed/Fixed structure.

### Fixed
- fix(release): `create-release.sh` promotes curated `[Unreleased]` content when present; auto-generates from commits only when `[Unreleased]` is empty; skips `chore(release)` and changelog meta commits.

## [0.8.0] - 2026-05-24

### Added
- feat(context): add `core/scripts/context-report.sh` to report lines, characters, directional token estimates, and large active-context files across governance, memory, skills, agents, and commands.
- feat(solar-async-tasks, solar-router): add async-task execution consent contract so queued tasks can write declared artifacts without re-approval while preserving gates for external, destructive, credential, irreversible, or out-of-scope actions; link the contract from JIT delegation and router policy docs.
- feat(sun-workspace-doctor): add optional `--check-plans` validation for `sun/plans/YYYY/MM/YYYY-MM-DD_*` layout, month-folder alignment, and future-date timeline markers.
- feat(solar-browser): introduce shared browser runtime skill (`ensure_browser.sh`, `check_browser.sh`, onboarding) for Chrome DevTools MCP on-demand usage.
- feat(solar-browser): add lifecycle validation (`validate_mcp.py`), enhanced ensure/check scripts, and `core/docs/browser-protocol.md`.
- feat(solar-router): add `list_providers.sh` to enumerate configured AI providers from router config.
- feat(solar-async-tasks): add `provider` frontmatter option to `create.sh` for strict provider selection at task creation.
- feat(solar-async-tasks): expand task-authoring references (`simple-task.md`, `task-with-subtasks.md`, `detached-subtasks.md`, `recurring-with-gate.md`).
- feat(governance): add session-level token budget protocol (`core/docs/token-budget-protocol.md`) for L1/L2/L3 context loading.
- feat(solar-security): add `solar-security` skill with `sanitize_context.py`, `sun/runtime/security-map.json` mapping, and unit tests.
- feat(solar-security): `sanitize_context.py` accepts a positional `target` (file, directory, or `-` for stdin) with recursive **in-place** directory sanitization; optional `--extensions` for suffix filtering; summarizes `sanitized_files` / `scanned_files`.
- feat(governance): add root-level preference update delegation in `AGENTS.md` so explicit user profile/context changes are delegated to core protocol execution.
- feat(governance): add `Profile Sync Protocol (required)` to `core/AGENTS.md` with trigger conditions, execution steps, and guardrails for `sun/preferences/profile.md` and `sun/MEMORY.md` synchronization.
- feat(solar-security): add `core/skills/solar-security/scripts/sanitize_paths.py` to rename tokenized filenames and update markdown links with dry-run support and optional mapping-based replacements.
- test(solar-security): add `core/tests/skills/solar-security/test_sanitize_paths.py` covering dry-run behavior, apply mode rename/link rewrites, and mapping-driven rules.

### Changed
- docs(governance): clarify provider invocation roles and JIT delegation so deferred, multiprovider, external-resource, or blocking work goes through `solar-async-tasks` before considering direct provider/router calls.
- refactor(governance): extract browser, JIT delegation, profile sync, and setup protocols from inline `AGENTS.md` into `core/docs/*.md`; slim root and `core/AGENTS.md` to active rules only.
- change(solar-system): remove browser from orchestrator supervision; browser runs on-demand via `ensure_browser.sh` per browser protocol.
- docs(onboarding): relocate onboarding and orchestration docs under `core/docs/`; add `mcp-requirements.md`; remove obsolete agent/onboarding checklist files.
- docs(governance): add context sustainability rules to root `AGENTS.md`, `core/AGENTS.md`, and the planet AGENTS template so Solar favors breadcrumbs and references over always-loaded context.
- docs(solar-skill-creator): make `solar-skill-creator` the skill context-sustainability gate for lean `SKILL.md` files and in-skill `references/`.
- refactor(agents): restructure root and `core/AGENTS.md` for clarity; move detailed rules to protocol docs.
- refactor(solar-async-tasks): reduce `SKILL.md` into a concise operational index and move detailed scheduling, recurrence, cleanup, notification, runtime, and error recovery guidance to `references/runtime-operations.md`; streamline task scripts and execution-flow documentation.
- change(solar-router): include `~/.local/bin` in provider fallback binary resolution so LaunchAgent runs can find Cursor Agent's `agent` CLI.
- change(solar-system): refactor LaunchAgent setup; build entrypoint at `sun/runtime/system/Solar` (via `SOLAR_SYSTEM_RUNTIME_DIR`); stop tracking compiled binary under `core/skills/solar-system/scripts/`.
- change(solar-security): `sanitize_paths.py` loads `sun/runtime/security-map.json` when `--use-mapping` is set and `--mapping` is omitted, matching the default mapping path used by `sanitize_context.py` (paths relative to the process working directory).
- docs(solar-security): correct `SKILL.md` examples for `sanitize_paths.py` so every command includes required rules (`--use-mapping` and/or `--old` / `--new`); document the default mapping file.
- test(solar-security): extend `core/tests/skills/solar-security/test_sanitize_paths.py` with coverage for default mapping resolution when `mapping_path` is unset.
- change(solar-security): directory mode in `sanitize_context.py` defaults to `*.md` only; use `--extensions` to include html, json, txt, etc.
- docs(solar-security): extend `sanitize_context.py` CLI and `SKILL.md` usage for directory mode (aligned naming with `sanitize_paths.py`'s `target`).
- chore(governance): move `Preference Update Delegation (Required)` section in root `AGENTS.md` next to governance delegation for clearer root-to-core ownership flow.
- docs(solar-security): document `sanitize_paths.py` usage in `core/skills/solar-security/SKILL.md`, including dry-run, apply mode, explicit overrides, and single-file execution.

### Fixed
- fix(solar-async-tasks): treat errored child tasks as terminal dependencies so parent tasks can resume and record unavailable providers instead of staying blocked forever.
- fix(solar-async-tasks): remove Bash 4-only `mapfile` from `execute_active.sh` so LaunchAgent execution works on macOS Bash 3.2.
- fix(solar-async-tasks): parse `blocked_by_task_ids` in both canonical CSV inline and YAML list formats so parent tasks do not resume before child tasks complete.
- fix(solar-security): persist `"CUSTOM"` from `sun/runtime/security-map.json` across `sanitize_context.py` runs alongside existing `REGEX` / literal passthrough keys.
- fix(sync-clients): enforce strict mirror sync for managed client folders (`skills`, `agents`, `commands`) by pruning stale entries before sync across `.cursor`, `.claude`, `.codex`, and `.gemini`.
- fix(sync-clients): harden Gemini command sync cleanup to remove stale non-`.toml` leftovers in `.gemini/commands` and keep only index-backed generated command files.

## [0.7.0] - 2026-04-09

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
- fix(governance): prohibit identity data (user name, assistant name) in `MEMORY.md` — names belong exclusively in `sun/preferences/profile.md`. Stale references were persisting when actors renamed after initial onboarding. Adds **Identity Data Isolation Rule** and **Profile Update Protocol** to `core/docs/onboarding-contract.md`; updates `core/AGENTS.md` memory protocol with explicit prohibition. Closes #1.

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
- feat(AGENTS.md): add Daily-log Execution Trace directive — when completing traceable work, append one line to `sun/daily-log/YYYY-MM-DD.md` with `HH:MM #tag Description → artifact`. Create file if missing. Tags: #sales #marketing #job #ops.
- feat(solar-router): integrate Cursor Agent (`agent`) as a first-class provider. Includes default command configuration with non-interactive flags (`-p`), workspace trust (`-f`), and MCP auto-approval (`--approve-mcps`).
- feat(solar-router): update `onboard_router_env.sh` and `diagnose_router.sh` to support `agent` priority, command migration, and preflight validation.

### Changed
- refactor(solar-router): split monolithic `run_router.py` into three layers — `router.py` (provider-agnostic core: parse, validate, JIT, prompt, decision engine), `scripts/providers/` (four adapters: claude, codex, gemini, agent via `BaseProvider`), and `run_router.py` (thin entrypoint: stdin → `route()` → stdout + exit). Public contract v3 unchanged.
- refactor(solar-code): restrict scope to planet-operated repos only — `core/skills/` changes are governed by `solar-skill-creator`, not `solar-code`. Updated `SKILL.md`, `references/repo-policy.md`, and `core/AGENTS.md` (new Skill governance rule). Removes all references to `core/` as a valid solar-code target.
- change(solar-system): extend orchestrator and health checks with `interface` feature support — `run_orchestrator.sh`, `check_orchestrator.sh`, `SKILL.md`, and `system-integration.md` now treat the local interface as a first-class managed runtime alongside existing features.
- change(sync-clients): update `.vscode/settings.json` during sync to register planet repos in `git.scanRepositories` and ignore the `planets` root scan folder. Improves multi-repo discovery in VS Code/Cursor workspaces.
- chore(.gitignore): group editor ignores under IDE section and move `.vscode/` and `.agents/` to keep workspace settings out of framework version control.
- change(solar-router): consolidate timeout configuration to a single `SOLAR_ROUTER_TIMEOUT_SEC` variable. `run_router.py`, onboarding, and router docs now use one end-to-end timeout contract; the legacy provider-specific timeout key was removed.
- change(sync-clients): recursive discovery of planet skills via `find -path "*/skills/*/SKILL.md"` — supports nested structures (e.g. `pm-*/skills/*` in phuryn). Planet skills no longer limited to `planets/*/skills/*`. Uses `LC_ALL=C sort` for deterministic collision resolution across locales.
- change(daily-log): Log section from list to table format (Time | Tags | Description). Tags without `#` (sales, marketing, job, ops). Order: newest first — insert new rows at top. Artifact as markdown link mandatory in Top Priorities, Blockers, and Log. `core/templates/daily-log.md` and AGENTS.md updated. Legacy list format deprecated.
- change(daily-log): update `core/templates/daily-log.md` — Top 3 → Top Priorities (flexible 1–N), Bloqueos → Blockers. Aligns with execution trace and todo-list format.

### Fixed
- fix(sync-clients): add spacing to emoji-prefixed labels (Settings/Setup) in console output for better readability.
- fix(solar-router): replace `datetime.datetime.utcnow()` with `datetime.datetime.now(datetime.timezone.utc)` in `audit_log` — eliminates DeprecationWarning in Python 3.12+.
- fix(solar-system): translate `check_orchestrator.sh` suggested actions to English — all diagnostic messages now consistent with `core/` language policy.
- fix(gemini): remove unnecessary prompt flags from router command execution and improve subprocess error handling in `scripts/providers/gemini.py`.

### Docs
- docs(solar-router): update `SKILL.md` and `routing-policy.md` with internal architecture section — layer contract table (entrypoint / router core / provider adapters), adapter location, unit test command. Known bug note updated: removes "pending Orchestrator/Executor refactor" reference (refactor complete); bug now tracked via Test 14 in `check_router.sh`.
- docs(solar-router): update `SKILL.md` and `routing-policy.md` to reflect `agent` capabilities and contract v3 compliance.
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
- feat(solar-system, solar-transport-gateway): enhance orchestrator health checks and script organization.
- feat(solar-async-tasks, solar-router): introduce async task execution with structured logging and enhanced routing.
- feat(solar-transport-gateway): improve tunnel recovery and environment variable handling.
- feat(solar-async-tasks): add manual task activation by ID with deterministic transitions.
- feat(solar-skill-creator): update script usage documentation and validation rules.
- feat(solar-async-tasks): enhance task sorting by scheduled time and priority.
- feat(CHANGELOG.md): update first-run protocol and enhance task management.
- feat(AGENTS.md): update first-run protocol for session initialization.
- feat(solar-router): enhance Gemini provider handling with improved environment setup and OAuth prompt detection.
- feat(solar-async-tasks): enhance task management with UUIDs, slug-based filenames, and improved sorting.
- feat(solar-async-tasks, solar-router, solar-system): enhance logging, path resolution, and environment setup.
- feat(solar-async-tasks): enhance task management with logging, requeue functionality, and error handling improvements.
- feat(solar-system): add `check_orchestrator.sh` — single-command orchestrator health check (`HEALTHY/PARTIAL/DOWN`, portable timeout, orphan lock detection).
- feat(solar-transport-gateway): add `ensure_transport_gateway.sh` (moved from `solar-system/scripts/` to owning skill).
- feat(solar-async-tasks): add `execute_active.py` — Python executor for async tasks via solar-router v3 (`channel=async-task`, `mode=direct_only`); replaces fragile bash provider loop.
- feat(solar-router): add executable smoke test for router v3 JSON contract (later renamed to `check_router.sh`).
- feat(solar-async-tasks): add `requeue_from_error.sh` to move tasks from `error/` back to `queued/` after fixing root cause.

### Changed
- change(solar-system): rename `solar_orchestrator.sh` → `run_orchestrator.sh`; update `Solar.c` wrapper and LaunchAgent.
- change(solar-router): rename `smoke_test.sh` → `check_router.sh` (`check_` prefix for health scripts).
- change(solar-async-tasks): rename `verify_lifecycle.sh` → `validate_lifecycle.sh` (`validate_` for internal checks).
- change(solar-system): `run_orchestrator.sh` calls `ensure_transport_gateway.sh` from `solar-transport-gateway` (correct ownership).
- change(solar-system, solar-transport-gateway, solar-router, solar-async-tasks): update SKILL.md validation commands and `system-integration.md` for new script names.
- change(solar-async-tasks): refactor `execute_active.sh` to lightweight wrapper around `execute_active.py`.
- change(solar-router): **Breaking (v3).** Router becomes single source of truth — contract v3 JSON (`channel`, `mode`, `decision`, `error_code`), provider fallback/strict mode, `DecisionEngine`, `async_only` draft creation, structured JSON output only.
- change(solar-router): update `system_prompt.md` for v3 `decision.kind` + `reply_text` in `mode=auto`.
- change(solar-transport-gateway): bridges delegate to router v3 — remove local provider selection; Telegram/n8n use `channel` + `mode=auto`; expose router JSON without legacy double-wrapper.
- change(solar-router, solar-transport-gateway, solar-async-tasks, solar-telegram): rewrite routing policy and transport docs for v3 channel mapping.

### Fixed
- fix(execute_active.py): remove redundant import and streamline error handling.
- fix(solar-async-tasks): clean up `requeue_from_error.sh` to remove execution error history.
- fix(solar-transport-gateway): add `--max-time 5` to `check_transport_gateway.sh` curl calls to prevent hangs.
- fix(solar-system): raise `FEATURE_TIMEOUT` to `15s` in `check_orchestrator.sh`; improve `PARTIAL` tunnel diagnostics from cloudflared logs.

### Removed
- remove(solar-system): `solar_orchestrator.sh` (renamed to `run_orchestrator.sh`).
- remove(solar-system): `ensure_transport_gateway.sh` (moved to `solar-transport-gateway/scripts/`).
- remove(solar-router): `smoke_test.sh` (renamed to `check_router.sh`).
- remove(solar-async-tasks): `verify_lifecycle.sh` (renamed to `validate_lifecycle.sh`).
