# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

## [0.19.3] - 2026-07-26

### Fixed
- fix(solar-client): `bootstrap_solar_client.sh` no longer errors with `BASH_SOURCE[0]: unbound variable` when installed via `curl | bash`.

### Changed
- change(solar-client): default install root is `~/.local/share/solar` (Claude Code / Codex style). Wrapper stays at `~/.local/bin/solar`. Workspace is any directory (e.g. `~/Solar`). Legacy `~/Solar/solar` is still discovered as a fallback.

## [0.19.2] - 2026-07-26

### Fixed
- fix(test): allow empty commit in bootstrap SHA install E2E (publish gate no longer fails on a clean tree).

## [0.19.1] - 2026-07-26

### Fixed
- fix(solar-client): `solar --version` works without a workspace / Solar App runtime (installer smoke + CI); `create-release` restores executable bit on `scripts/solar` after version bump so git keeps `100755`.

## [0.19.0] - 2026-07-26

### Added
- feat(solar-gateway): `stop_transport_gateway.sh` with `--dry-run` / `--force` / `--tunnel-only`, strict ownership, and stale pid-file unlink.
- feat(solar-gateway): stable env stamp at `sun/runtime/gateway/env.stamp`, failure backoff via `env.fail`, and portable mkdir-lock (no `flock`) shared by ensure/setup.
- feat(solar-gateway): non-destructive preflight before stopping a healthy runtime; provider tokens validated via solar-router `list_supported_providers.sh` (canonical `PROVIDERS`).
- feat(solar-router): `list_supported_providers.sh` exports registered provider ids from `PROVIDERS`.
- test(solar-gateway): functional Telegram rollback harness + `smoke_priority_ensure.sh` (priority change → ensure → process env).

### Changed
- change(solar-gateway): setup no longer reuses existing listeners; occupied ports require `--restart` (preflight → stop → start → stamp).
- change(solar-gateway): `ensure_transport_gateway.sh` is drift-first — any env drift triggers full `setup --restart`; partial without drift remains tunnel-only.
- change(solar-router): provider id `gemini` retired in favor of `agy` (Antigravity CLI). Supported providers: `codex`, `claude`, `agy`, `agent`, `ollama`.
- change(solar-router): default headless command for `agy` is `agy -p --dangerously-skip-permissions --add-dir <workspace>`.
- change(solar-router): unified default provider priority `codex,claude,agy,agent` across router, onboard, diagnose, list_providers, templates, validate_mcp, and docs.
- change(solar-client): new `solar client update` versions atomically migrate `SOLAR_ROUTER_PROVIDER_PRIORITY` / `SOLAR_AI_PROVIDER_PRIORITY` (`gemini`→`agy`) before applying the framework update.
- change(templates): `workspace.env.example` and `solar -m` help list `agy` instead of `gemini`.
- change(solar-browser): `validate_mcp` checks all existing Antigravity MCP paths (local `.agents/mcp_config.json` effective when present, plus `~/.gemini/**` candidates).

### Fixed
- fix(solar-router): restore gateway long-job async path — when `mode=auto` emits `async_draft_created` on telegram/n8n, the router again creates a queued task, sets `notify_when: completed`, and returns a canonical ACK. Worker prompts keep Validation Gate for mutable actions; `add_notify.sh` failures use a no-notify ACK; create failures in `async_only`/`auto` fall back to `direct_reply` instead of a false ACK; `SOLAR_ROUTER_CONTEXT_TURNS` is validated/clamped.
- fix(solar-router): restore conversation continuity lost in `be1ae84` (thin dispatcher). `route()` / `route_stream()` again inject rolling `<solar_summary>` plus recent JSONL turns (`SOLAR_ROUTER_CONTEXT_TURNS`) into the provider prompt, persist updated summaries, and store clean `reply_text` in history.
- fix(solar-gateway): Telegram webhook set/verify failures now roll back (stop) instead of exiting under `set -e` with partial processes and no stamp.
- fix(solar-gateway): tunnel ownership matches stamp previous tunnel identity so name/config/host changes do not mark the old cloudflared as foreign during restart.
- fix(solar-gateway): `SOLAR_GATEWAY_LOCK_HELD=1` is ignored unless `lock/pid` exists and equals the parent PID (no manual lock bypass).
- fix(solar-gateway): `env.fail` hard-stops after `GATEWAY_FAIL_ATTEMPTS_CAP` (default 5) with the same fingerprint — no infinite spaced retry loop.
- fix(solar-client): `sync-clients` prune now removes dangling symlinks (e.g. skills/agents/commands left after a planet is deleted). Previously `[ -e ]` skipped broken links, so stale entries like `oh-my-codex:*` survived `solar client sync`.
- fix(solar-router): `_provider_priority()` no longer falls back to all providers when the configured list is empty or only contains unsupported tokens (e.g. `SOLAR_ROUTER_PROVIDER_PRIORITY=gemini`). It now raises `UnsupportedProviderPriorityError`; `route()` maps that to `error_code=invalid_provider_priority` (not `all_providers_failed`).
- fix(solar-router): the first provider selection after an update from a legacy client performs the same atomic `gemini`→`agy` workspace migration; migration failure is explicit and no provider runs.
- fix(solar-router): shared `migrate_provider_priority.py` helper + `onboard_router_env.sh` rewrite priority token `gemini` → `agy` with an explicit WARN, and do **not** copy `SOLAR_ROUTER_GEMINI_CMD` / `SOLAR_AI_GEMINI_CMD` into `SOLAR_ROUTER_AGY_CMD` (values like `gemini -y` would keep calling the retired binary).
- fix(solar-router): `diagnose_router.sh` on provider failure prints `error:` then `cmd:` with `<SOLAR_WORKSPACE>` / `<prompt>` placeholders instead of dumping the full prompt capture; `--verbose` keeps full error + raw capture.
- fix(solar-client): doctor / upgrade report copy tells operators to **remove** legacy `*_GEMINI_CMD` keys (optional new `SOLAR_ROUTER_AGY_CMD`), not rename the value in place.

### Removed
- remove(solar-router): silent support for `SOLAR_ROUTER_GEMINI_CMD` at runtime. Use `SOLAR_ROUTER_AGY_CMD` or the default `agy` command. `solar client doctor` / `upgrade` warn if legacy keys remain.

## [0.18.2] - 2026-06-06

### Added
- feat(solar-client): canonical `solar` CLI entry — `core/skills/solar-client/scripts/solar` (dispatcher for client, workspace, app, status, paths, chat REPL).
- feat(solar-app): `solar app voice *` — voice CLI nested under App (doctor, once, paste, ask, etc.).

### Changed
- change(solar-app): governance editor autocomplete — filter-as-you-type matches + HTML datalist from `GET /api/governance/tree`.
- change(solar-app): tray Voice menu re-enables copy + Ask Solar (experimental); paste remains primary validated path.
- change(solar-system): `interface` feature token deprecated; orchestrator uses `host` only.
- change(voice): user-facing hints use `solar app voice doctor` (not top-level `solar voice`).
- change(env): remove legacy `SOLAR_INTERFACE_*`; bind vars are `SOLAR_APP_HOST`, `SOLAR_APP_PORT`, `SOLAR_APP_BASE_URL` (not `SOLAR_HOST_HOST`).
- test(solar-app): suite directory renamed from `core/tests/skills/solar-host/` → `solar-app/`.

### Removed
- remove(solar-interface): skill and `:7741` daemon sunset — no bundle seed, no orchestrator ensure.
- remove(solar-voice): deprecated stub skill; voice implementation stays in `solar-app`.
- remove(solar-transport-gateway): deprecated alias stub (use `solar-gateway`).
- remove(solar-migration-playbook): deprecated alias stub (use `solar-migration`).
- remove(solar-cli): top-level `solar voice *` removed; use `solar app voice *` or Solar.app tray.
- remove(solar-app): CLI entry and path shims moved to `solar-client` (`solar`, `solar_status.sh`, `solar_paths.sh`).

### Fixed
- fix(voice): Ask intent falls back to `POST /api/chat` when SSE stream fails (tray notifications show result or error).
- fix(solar-app): tray Voice menu duplicate `else` (IndentationError on macOS).
- fix(solar-app): `interface_repl.py` imports `solar_paths` from `solar-client/scripts`.
- fix(solar-app): honor explicit `SOLAR_APP_PORT=9000` (hash port only when unset).
- fix(solar-app): `onboard_host_env.sh` migrates legacy env keys instead of overwriting with `:9000` defaults.

## [0.18.1] - 2026-06-02

### Fixed
- fix(solar-cli): `solar --version` stayed at `0.17.2` on tag `v0.18.0` — `SOLAR_VERSION` aligned with framework tag (`0.18.1`).
- fix(release): `create-release.sh` bumps `SOLAR_VERSION` in the same `chore(release)` commit as the tag (avoids post-tag bump commits).

## [0.18.0] - 2026-06-02

### Known issues
- **Solar.app Voice:** only **Push to talk (paste)** validated; copy, Ask Solar, global hotkey — see voice bug register.
- **Governance editor:** path tree shipped (`GET /api/governance/tree`); autocomplete / polish still pending (Host-3).
- **`solar-interface`:** skill and optional `:7741` daemon remain for dev/CLI; full sunset not done. Test dir still named `core/tests/skills/solar-host/`.

### Added
- feat(solar-app): **Host-3 governance** — `GET /api/governance/tree` (`.md`/`.json` under `sun/`, `planets/`); dashboard select + manual path; chat shows `reply_text`.
- feat(solar-app): `core/skills/solar-app/SKILL.md` — canonical control plane skill; runtime in `solar-app/scripts/`.
- feat(solar-client): **Fase 7** — canonical `resolve_solar_paths.sh` and `solar_paths.py`; tests in `core/tests/skills/solar-client/`.
- test(solar-host): `test_host_governance_tree.sh` — tree API, path rejection (`..`).

### Changed
- change(solar-app): runtime moved from `solar-host/scripts/` to `solar-app/scripts/` (no backward-compat symlink).
- change(solar-cli): human entry is **`solar app`** only; **`solar host`** subcommand removed.
- change(solar-client): portable bundle seeds `solar-client`, `solar-workspace`, `solar-app` only (no `solar-host` / `solar-interface` seeds).
- change(solar-system): LaunchAgent orchestrator uses `solar-app` `ensure_host.sh` / `check_host.sh`.
- change(solar-interface): one-release shims re-export `solar-client` path resolution (`resolve_solar_paths.sh`, `solar_paths.py`).
- change(solar-interface): default runtime dir `sun/runtime/app` (was `sun/runtime/interface`); `solar status` host block targets `:9000` only.
- change(.gitignore): `**/host_platform/macos/dist/` for py2app `Solar.app` artifacts (replaces obsolete `solar-host/.../dist/` path).

### Removed
- remove(solar-host): skill directory `core/skills/solar-host/` (superseded by `solar-app`).

### Fixed
- fix(solar-router): `env_int()` tolerates inline `#` comments in `.env` (e.g. `SOLAR_ROUTER_TIMEOUT_SEC`) — scoped chat no longer 502 on parse error.
- fix(solar-interface): `solar_status.sh` — restore missing `fi`; drop legacy `:7741` host fallback (Solar App Runtime panel).
- fix(solar-interface): `solar_paths.py` shim delegates `__main__` (prints `SOLAR_WORKSPACE` / `SOLAR_ROOT`).
- fix(solar-interface): `SKILL.md` — remove incorrect `solar app` “compatibility alias” copy; document `solar app` vs removed `solar host`.
- test(solar-client): `test_solar_paths_py.sh` asserts interface shim CLI output.

## [0.17.2] - 2026-06-01

### Changed
- change(solar-interface): bump CLI `SOLAR_VERSION` to `0.17.2` (`solar --version` aligned with latest tag).
- change(solar-client): **Fase 2.1 restored** — `client update` in git mode never rsync-backs up by default (clean or dirty); rollback = `git checkout <tag>`; `--backup` forces snapshot; `--bundle` still always backs up `core/`.

### Fixed
- fix(solar-client): `client update` backups for nested layout (`SOLAR_WORKSPACE` + `solar/` install) go to `$SOLAR_WORKSPACE/backups/`, not `$SOLAR_ROOT/backups/`.

## [0.17.1] - 2026-06-01

### Known issues
- **Solar.app Voice:** only **Push to talk (paste)** + **Detener grabación** validated; copy, Ask Solar, and global hotkey not working / not validated.
- Use dashboard chat at `:9000` for agent questions until voice ask is fixed.
- **Governance editor:** path tree/autocomplete under `sun/` and `planets/` not shipped yet (Host-3 polish).

### Added
- feat(solar-host): **Host-2** fleet operations on dashboard — `POST /api/actions/client` (`sync`, `client_doctor`, `workspace_doctor`) with allowlist, global lock (`409`), 120s/60s timeouts, 32 KB output cap, loopback-only client.
- feat(solar-host): **Host-2** request hardening — `Host` and `Origin` must target `127.0.0.1` / `localhost` (and matching port); rejects cross-origin and DNS-rebinding-style `Host` values.
- feat(solar-host): **Host-2** inbox events — `health.degraded`, `gateway.error`, `client.action.failed`; `emit_deduped()` with 5 min cooldown per `(type, workspace, key)`.
- feat(solar-host): `host_health_monitor.py` — fleet/status/async-failed scans; gateway check via `solar status` heuristics + `check_transport_gateway.sh`; background poller follows active workspace.
- feat(solar-host): `host_client_actions.py`, `reg.solar_cli_argv()` — invoke `solar` script via `bash` or PATH executable (no broken `bash solar` fallback).
- feat(solar-host): dashboard **Fleet operations** section (Sync skills, Client doctor, Workspace doctor + output `<pre>`); inbox filters for new event types.
- feat(solar-host): scoped chat — clearer `502` body when router fails; emits `run.failed` on chat errors.
- test(solar-host): `test_host_fleet_client_actions.sh` — allowlist, loopback, `Origin`/`Host` forbidden, `client.action.failed`.
- test(solar-host): **Host-3** `test_host_chat_e2e.sh` — `POST /api/chat` happy path with mock router (`SOLAR_ROUTER_CLAUDE_CMD`), not `SOLAR_VOICE_MOCK_STREAM`.
- test(solar-host): `test_host_events_contract.sh` extended — `gateway.error`, `health.degraded`, dedupe unit check.

### Fixed
- fix(solar-host): `solar host stop` stops orphan `host_server.py` listeners on `SOLAR_HOST_PORT` when `host.pid` is missing; `start` recovers pid file or clears port before bind.
- fix(solar-host): health poller no longer pins workspace from process start — rescans `get_active_path()` every 60s.

### Changed
- change(solar-host): `SKILL.md` Validation — documents Host-2 tests and Fleet operations API.

## [0.17.0] - 2026-06-01

### Added
- feat(solar-host): `voice_core.py` — Host client, intents, SSE `stream_ask`, `session.json` per active workspace.
- feat(solar-host): voice intents approve/reject/switch/open dashboard; `switch_active_workspace` fix.
- feat(solar-host): tray Voice menu — toggle PTT copy/paste, Ask Solar (worker threads).
- feat(solar-host): macOS global hold-to-talk module (`hotkey.py`) — **known broken in production**; tray PTT is the supported path.
- feat(solar-host): phrase-stream TTS (`voice_tts.py`, `AVSpeechSynthesizer` + `PhraseBuffer`; fallback `say`).
- feat(solar-host): `voice_config.py`, `voice_doctor.sh`, `solar voice doctor` CLI.
- feat(solar-interface): `SOLAR_VOICE_MOCK_STREAM` static SSE fixture for CI (no router/LLM).
- feat(solar-host): `solar voice ask` CLI subcommand.
- test(solar-host): `test_voice_core_unit.sh`, `test_voice_cli_host_api.sh`, `test_voice_stream_contract.sh`, `test_voice_macos_imports.sh`.
- test(solar-interface): `test_solar_status_host.sh` (host block + router stale age filter).
- feat(solar-router): `reconcile_router_audit.sh` — close orphan audit `start` records.

### Fixed
- fix(solar-cli): `solar status` reports **host** (`:9000` in-process) instead of legacy `interface` daemon check; runtime health via `/api/runtime/health`.
- fix(solar-router): stale in-flight WARN counts only recent orphans (<24h).

## [0.16.0] - 2026-06-01

### Added
- feat(solar-host): Host-1 macOS — `host_platform/macos/` (tray, notifications, `SOLAR_HOST_TRAY=1` on start).
- test(solar-host): `test_host_macos_notifications_unit.sh`.
- feat(solar-host): enriched inbox — `workspace.activated`, `approval.pending`, payloads with `workspace`/`summary`; `GET /api/events?types=`.
- feat(solar-host): dashboard inbox filters, pending badge, deep-link `?focus=approval:<id>`, inline approve/reject.
- feat(solar-interface): `InterfaceStore.create_approval()` + `POST /approvals`; event hook for pending approvals.
- test(solar-host): `test_host_events_contract.sh`, `test_host_approvals_two_workspaces.sh` (MVP-a a4).
- feat(solar-interface): `InterfaceStore` — workspace-scoped threads/runs/approvals DB (shared by Host and legacy daemon).
- feat(solar-interface): `interface_http.py` — shared HTTP dispatcher for threads/runs/approvals/SSE (Host `:9000` + legacy `:7741`).
- feat(solar-host): in-process workspace API on `:9000` (`host_interface.py`); full interface routes at root paths.
- feat(solar-host): `host_events.py` + `GET /api/events` + dashboard Inbox section (polling).
- test(solar-host): `test_host_interface_routes.sh` — threads/runs/ready/delete on Host.
- test(solar-host): `test_host_stream_smoke.sh` — SSE `POST /threads/{id}/stream` headers + `data:` event.
- test(solar-host): MVP-b smoke (`test_host_api_smoke.sh`, `test_no_legacy_listener_after_switch.sh`, `test_fleet_api_contract.sh`).

### Changed
- change(solar-host): **MVP-b.1** — full `interface_server` API on `:9000` via `InterfaceHttpDispatcher`; `do_DELETE` for threads; `GET /threads/{id}`.
- change(solar-host): workspace switch calls `stop_legacy_interface_daemon()` (MVP-b b2 — no stale `:7741` listeners).
- change(solar-host): `POST /api/runtime/interface/start` returns **200** with `{ deprecated: true }` (no longer 404).
- change(solar-host): **MVP-b.0** — Host serves approvals/chat in-process; no `:7741` proxy or escape-hatch flags.
- change(solar-interface): `interface_repl.py` default base URL → `http://127.0.0.1:9000` (`SOLAR_HOST_BASE_URL`).
- change(solar-host): `host_tray.py` pending count via `/api/approvals` on Host (not legacy `:7741`).
- change(solar-system): `host` feature = `:9000` only; `interface` token optional for dev daemon.
- change(solar-host): fleet health uses in-process `readiness()` for active workspace; `list_workspaces` omits `interface_port` (CLI `ports` retained).
- change(solar-interface): `interface_server.py` delegates to `interface_http.py` (legacy `:7741` compat).
- **Deprecated (public API):** `SOLAR_INTERFACE_PORT` / `port_offsets` in Host-facing responses — canonical API is Host `:9000`.
- feat(solar-host): multi-workspace registry (`~/Library/Application Support/Solar/workspaces.json`), `solar host workspace *`, fleet health API and dashboard.
- feat(solar-host): async monitor, kill switch, runtime start (interface/gateway), scoped chat, governance markdown editor.
- feat(solar-host): optional macOS tray (`host_tray.py`, requires `rumps`).
- feat(solar-host): `voice_cli.py` inside solar-host; `solar voice *` CLI (solar-voice skill stub only).
- feat(solar-system): `host` feature token and `ensure_host.sh` in orchestrator (`host` also ensures `solar-interface` daemon).

### Changed
- change(solar-interface): `:7741` landing redirects users to Solar Host (`:9000`).
- change(solar-client): portable bundle seeds `solar-host` only for app+voice (removed `solar-voice` seed).
- change(plans): product plan [2026-05-31_solar-app-plan.md](../../sun/plans/2026/05/2026-05-31_solar-app-plan.md) (replaces solar-host-plan).

## [0.15.0] - 2026-05-31

### Added
- feat(solar-client): new skill `solar-client` — workspace lifecycle scripts moved from `solar-interface`.
- feat(solar-workspace): new skill `solar-workspace` — `solar workspace doctor` for `sun/` and `planets/`.
- test(solar-workspace): `test_workspace_doctor.sh`.

### Changed
- change(solar-interface): daemon/REPL only; client lifecycle documented in `solar-client` / `solar-workspace`.
- change(solar-cli): `solar client doctor` is client-only; workspace checks use `solar workspace doctor`.
- change(solar-cli): `solar status` shows `client` and `workspace` blocks with doctor hints (`v0.15.0`).
- change(solar-client): runtime scripts moved from `core/scripts/` to skill-owned paths; shims remain one release.
- change(solar-client): portable bundle allowlist seeds `solar-client` + `solar-interface` + `solar-workspace` only (`v0.16.0`).
- change(solar-gateway): renamed from `solar-transport-gateway` (deprecation stub retained).
- change(solar-migration): renamed from `solar-migration-playbook` (stub retained).

### Removed
- remove(solar-n8n-workflow): skill removed from core; use `POST /webhook/n8n` via solar-gateway + router.
- remove(core/templates): sales commercial templates (`sales-*`, `lead-discovery-5q`); use planet skills instead.

### Fixed
- fix(solar-host): `start_host.sh` verifies `/health` before reporting success; stops stale pid when health fails; shows log tail on failure.
- fix(solar-host): dashboard escapes HTML; approval actions use `data-*` handlers and validated approval IDs (XSS-safe).
- fix(solar-migration): validation command targets `core/skills/solar-migration`.
- fix(docs): planet templates and onboarding/mcp docs use skill paths instead of legacy `core/scripts/`.
- fix(solar-client): `package_solar_bundle.sh` resolves framework repo root (`../../../..`); no longer copies `core/scripts/` into release bundles.
- fix(solar-workspace): `create-planet.sh` and `planet-git-bootstrap.sh` use `SOLAR_WORKSPACE` + `solar_core_dir` for templates/planets.
- fix(solar-skill-creator): `check-mcp.sh` and `context-report.sh` resolve workspace via `resolve_solar_paths.sh`.

### Added
- feat(solar-host): MVP local control plane UI on `SOLAR_HOST_PORT` (default 9000) — status, approvals, workspace overview.

## [0.12.0] - 2026-05-29

### Added
- feat(solar-client): Fase 3 dual-mode workspace — `core_source: global | workspace-snapshot` in manifest with `requires_global_client` and `portable_capabilities`.
- feat(solar-client): `solar client bundle create|verify` — opt-in portable bundle under `.solar/bundle/` with transitive allowlist, `index.json`, and checksums.
- feat(solar-client): `solar client sync --portable` — sync IDE + bundle create in one step.
- feat(solar-client): `solar client self-update` — alias for global `client update`.
- feat(solar-client): `install_solar_client.sh` and `bootstrap_solar_client.sh` for PATH install without monorepo familiarity.
- feat(solar-client): `solar_runtime_core_dir` / resolver uses bundle when `workspace-snapshot` (FAIL if bundle invalid).

### Changed
- change(solar-client): `solar status` and `solar client doctor` report `core_source` mode and portable bundle health.
- change(solar-client): `solar client sync` preserves `workspace-snapshot` manifest on bump (no silent reset to global).

### Fixed
- fix(solar-client): `bundle create` reads global `core/` via `solar_global_core_dir` so portable refresh no longer deletes its own source tree.
- fix(solar-client): export `SOLAR_GLOBAL_ROOT` in portable mode; `snapshot_outdated` and manifest version bump compare against the real framework install.
- fix(solar-client): bundle secret scan only flags `.env` files and literal `sk-ant`/`sk-proj` tokens (no false positives on framework scripts).

### Tests
- test(solar-client): `test_client_manifest.sh`, `test_client_bundle.sh`; smoke asserts default global contract.
- test(solar-client): `test_client_bundle.sh` covers second `bundle create` refresh and quiet doctor after create.

## [0.11.2] - 2026-05-27

### Changed
- change(solar-client): `solar client upgrade --restructure` moves the full framework install into `solar/` (not only `core/` + `.git`); post-restructure next steps remain manual (`client init`, `sync`, `doctor`).

### Fixed
- fix(solar-client): restructure idempotency no longer treats workspace-root `AGENTS.md` (from `client init`) as framework still at root.
- fix(solar-client): `client init` resolves `SOLAR_ROOT` via `solar_resolve_paths` when `solar/core/` exists (legacy_solar layout).

### Tests
- test(solar-client): extend `test_client_upgrade.sh` for full restructure plan/apply and post-init idempotency.

## [0.11.1] - 2026-05-27

### Changed
- change(solar-client): `solar client sync` updates manifest `core_commit` (and version) from `SOLAR_ROOT` via `solar_client_bump_manifest_from_install`.
- change(solar-client): `solar client doctor --strict` fails when manifest `core_commit` drifts from `SOLAR_ROOT` HEAD.
- change(solar-client): `sun-workspace-doctor` supports `--no-summary` when embedded in `solar client doctor` (single final summary).
- change(solar-interface): bump CLI `SOLAR_VERSION` to `0.11.1`.

### Fixed
- fix(solar-client): `solar_client_rotate_backups` prunes oldest backups (mtime), not newest.
- fix(solar-client): git install backup includes `.git/objects` for restorable `SOLAR_ROOT` snapshots.
- fix(solar-client): `solar client update --tag` without value exits 2 with a clear error (no unbound variable).

### Tests
- test(solar-client): extend `test_client_update.sh` — backup `.git/objects`, `--tag` error, rotate order, manifest `core_commit` bump.

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
