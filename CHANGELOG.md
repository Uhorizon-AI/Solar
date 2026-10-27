# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

## [0.59.2] - 2026-10-27

### Fixed
- Allow repository reviews with safe internal symbolic links by recording and omitting aliases from the snapshot without duplicating their canonical files. Keep unsafe targets rejected and report the offending path and reason through MCP.

## [0.59.1] - 2026-10-25

### Fixed
- Keep task dates, optional tokens and latest recorded run duration visible under When on mobile; preserve labelled Runs columns with horizontal scrolling at narrow widths.
- Align provider and channel run breakdowns with Runs, percentage and measured average duration columns.
- Add compact task name/ID search beside the list count and an icon-only Copy action for the full detail ID, preserving status filters and parent context.
- Record elapsed duration for restricted router executions, including failures; show labelled timestamp-derived durations for historical Runs when both endpoints are recorded.
- Show input and output token counts directly in Console Tasks and recent Runs; keep measurement coverage and evidence under optional details, and match run counters by router ID.

## [0.59.0] - 2026-10-25

### Added
- Capture provider-reported token usage for asynchronous questions through solar-state schema 8, preserving partial measurement evidence and exposing coverage and counters in Console task details and MCP task view `usage`. Missing counters stay distinct from zero; subscription quota and monetary pricing are outside this delivery.

## [0.58.4] - 2026-10-24
### Fixed
- fix(router): honor payload channel on restricted run start row
- fix(router): record channel=mcp for restricted runs


## [0.58.3] - 2026-10-24
### Fixed
- fix(ci): avoid hardlinks in install test bootstrap clone


## [0.58.2] - 2026-10-24

### Changed
- Say that the read-only mode of `ask` is a request that depends on each client, in the README, `AGENTS.md`, the readonly-review guide, the `task.create`, `ask` and `solar_execute` descriptions, and one line in the approval text (English and Spanish) shown for `ask` and for a declared read. Measured on 2026-10-23: Codex, launched with its read-only sandbox, created a file because its own settings (`on-request` approvals with an automatic reviewer) allow leaving the sandbox; Cursor (Ask mode) and Claude (plan mode) did not write. Solar does not override a client's approval policy.
- Questions can share places once `ask_readonly_v1` is listed in `enabled_reader_profiles` (the registry already verifies it for the four clients); nine tests with the real registry cover mixed providers, per-provider limits and the two ways back (capacity 1, or removing the profile). Docs and comments no longer say that only Claude can share places.

### Fixed
- A queued question no longer says it is "confined to a verified read-only profile"; reviews keep that wording.
- The approval text no longer presents the revision of an ordinary task as a question: the executor and the text ask the same helper (`_derive_allowed`).

## [0.58.1] - 2026-10-23

## [0.58.0] - 2026-10-23

### Added
- Path zones (`path_zones.py` in `solar-state`): a declared path is classified as installation, planet, workspace or outside, and a task takes the outermost zone of its paths. Containment is decided by file identity (device and inode), so it is right on any volume: symlinks, `..`, whole directories, targets that do not exist yet, case variants of one folder, an installation nested in a planet. The zone is declared, not verified: it does not confine the client.
- `task.create` returns `zone` (aggregate plus path to zone list, labelled `declared, not verified`) for a task that declares access or asks a question, and the approval text of `task.create` and `task.authorize_run` shows it. It is informational.

### Changed
- A read declared with `access_policy` (mode read), a provider and instructions, with no `ask`, `review`, `review_batch` or exclusive resources, is the same question as `ask`: same profile, manifest, digest and access text. `ask` stays as an alias and keeps an explicit declaration whole. A declared read that does not cover the workspace and has no `ask.folder` is refused with a clear reason, as `ask` already did. A revision is only derived when its source is already a question. `task.update` of a question re-derives its inputs and keeps its folder and model.
- A question now waits for `task.authorize_run` when any declared path, not only the folder it starts in, is outside the workspace. This also applies to `ask`: it is stricter than before and never looser.
- The `task.create` summary, the `ask` argument, `solar_execute`, `SKILL.md` and the readonly-review guide describe a declared read as a question and say that every declared path counts.

## [0.57.1] - 2026-10-22

### Fixed
- `ask` is for own content only; external or untrusted content goes through `review` with `repository_readonly_v1` (said in the `task.create` summary, the `ask` argument and the readonly-review guide).

## [0.57.0] - 2026-10-22

### Changed
- The short output of `solar client update` uses the Solar Console colors (amber `Solar`, green `✓`, amber `!`, blue versions and `Next:`, red errors, grey `Log:`) when the output is a terminal. Without a terminal there are no escape codes, and the log stays plain text. `NO_COLOR` and `TERM=dumb` turn them off; `SOLAR_CLIENT_COLOR=always|never` is an explicit choice and wins over both. Truecolor is used when `COLORTERM` says so, else the nearest 256-color index.
- The status lines of the update follow one pattern, `✓ Thing done`, with a capital first letter and no em dashes; the LaunchAgent line reads `✓ LaunchAgent points to this install` (a LaunchAgent that is skipped, not installed or stale shows as `! LaunchAgent …`). The header is now `Solar client update` (it was `Solar Client update`) and the log line starts at the first column. `WARN`, `ERROR` and `FAIL` lines, and the indented lines that follow them, keep their own text: only the line that starts the error is red, on stderr.

## [0.56.0] - 2026-10-22

### Changed
- `solar client update` prints a short summary (version change, one line per phase, the result) instead of the full output: the git, drain, gateway and console output and the runtime migration JSON go to `<runtime>/update-logs/` (the last 10 are kept). Errors still reach the terminal with the lines above them, and `--verbose` prints everything. After a verified update, also one finished with `--resume`, it runs `solar client sync` and `solar client doctor` in the workspace (`--no-sync` skips them). The front updater passes `--verbose` and `--no-sync` only to a target whose entrypoint knows them.
- The `solar client upgrade` hint after an update appears only when there is something to upgrade (IDE artifacts in the install, an obsolete `.solar/core`, or a layout older than `solar-client-v1.2`). `solar client upgrade` no longer lists the smoke test and the LaunchAgent installer as next steps.

## [0.55.3] - 2026-10-22

### Fixed
- The `ask` argument of `task.create` now describes itself, and the `task.create` summary and the `solar_execute` description say that `ask` is what makes a task a question that asks the client for its read-only mode (a request, not a guarantee); without it the task is neither.
- The contract of the task lifecycle operations (`client_consent`) says they run on the client's own tool permission with no form, instead of promising native confirmation; only `task.authorize_run` asks.

## [0.55.2] - 2026-10-21

### Fixed
- The `solar_execute` description and the `task.create` summary now say how to ask another AI client a question through the MCP (`task.create` with `ask`, then `task.wait`); an agent with no context used to conclude there was no operation.

## [0.55.1] - 2026-10-21

### Fixed
- Restricted readers no longer require a model. `review.model` (and the batch child `model`) is optional for all four providers: when it is omitted no `--model` is passed and the CLI keeps the model it has already chosen (the `--model` help check is skipped too). For Cursor, only the model selection (`model`, `selectedModel`, `modelParameters`) of the user's `~/.cursor/cli-config.json` is copied into the private config. The manifest and digest record `model: null`, so a review with and without a model are different approved inputs, and the confirmation shows `client default`. Antigravity and Claude/Codex isolate their configuration, so their "default" is the CLI's own default, not a user setting.
- A restricted reader that exits non-zero now says why instead of only `restricted provider returned non-zero`: the task log gets `exit N: <reason>` with a fixed word for the known causes (`not_logged_in`, `quota_or_rate_limit`, `model_unavailable`) or a short redacted tail of stderr (prompt copies, bearer and key=value secrets and token-shaped strings removed). Antigravity now writes its log to the private directory (`--log-file`) so the reason survives the launch directory; the help check requires that option.
- Cursor, Antigravity, Codex and Claude can be asked a question with the session the user already logged in with: `BaseProvider.ask()` launches the client with the caller's own environment (no replaced `HOME`, no copied or linked credentials) and from any folder, and asks for the client's native read-only mode (`--sandbox read-only`, `--mode ask`, `--mode plan`, `--permission-mode plan`); the result names the mode used, or `none` when the client has no such mode. The restricted-reader cage is unchanged and stays a separate option.
- A question to one client is now a task of its own. `task.create`/`task.update` accept `ask` (`folder` and `model`, both optional) with the prompt in `instructions` and an explicit `provider` (`claude`, `codex`, `agent` or `agy`); no repository, commit or evidence is needed. It uses the new `ask_readonly_v1` profile: the prompt, client, model and the effective start folder (the workspace when omitted) are stored as an immutable, digest-checked input that must lie inside a declared read scope, and are verified again before launch. While that folder is the workspace or inside it the task is low risk and runs without `task.authorize_run`; any other folder (`/` and `$HOME` included) waits for it, and the confirmation shows the folder. Read-only is a request to the client, not a limit: see `core/docs/repository-readonly-review.md`. A client that fails or times out says why (`<client> exit N: not_logged_in | quota_or_rate_limit | model_unavailable`, `<client> exit timeout`); quoted secrets (`"api_key": "..."`) are redacted from that text. The prompt always follows a separator, so it can never be read as an option. Mixing `ask` with `review` or `review_batch` is rejected.

## [0.55.0] - 2026-10-20

### Added
- `task.wait` (A0, read-only) in `solar_execute`: one call sleeps in short slices up to `timeout_seconds` (max 90, default 60; `poll_seconds` 1-30, default 1) and answers with the final status plus the task's `result` view; a still-running task returns its status and a `next` hint, never an error. A queued task that still waits for `task.authorize_run` answers at once with `awaiting_approval` instead of burning the timeout. During the wait the stdio server keeps answering the transport: a `ping` gets its reply and cancelling the live request ends the wait (`cancelled_by_client`). It never claims, transitions or writes; the gate records it as `read_allowed`.

## [0.54.6] - 2026-10-20

### Changed
- The Codex repository reader now discovers its capabilities from `codex exec --help` option blocks (the same `cli_capabilities` check as Claude, Cursor and Antigravity) instead of looking for flag names anywhere in the help text; the version is only recorded.
- The Codex help, policy (`codex doctor --json`) and credentials refusals keep `execution_profile_unsupported` and now carry `error_detail` (`provider`, `stage`, fixed `reason`, `option`), so the task log names the failed check. A `doctor` field of an unexpected type is `doctor_unrecognized`; the `doctor` exit code is not evidence.

## [0.54.5] - 2026-10-20

### Fixed
- The restricted Claude package review (`text_only_review_v1`) no longer fails with `execution_profile_override_rejected` because the workspace's own `.claude/settings*.json` or `.mcp.json` declares `permissions`, `hooks` or similar; the launch never reads them.
- Command, flag and environment overrides are still rejected.

## [0.54.4] - 2026-10-20

### Changed
- The restricted Claude reader now discovers its capabilities from `claude --help` option blocks (the same `cli_capabilities` check as Cursor and Antigravity) instead of looking for flag names anywhere in the help text. The version is only recorded. A refusal keeps `execution_profile_unsupported` and carries `error_detail` (`provider`, `stage` `help` or `policy`, `reason`, `option`), so the task log says which check failed: `help_timeout`, `help_unavailable`, `help_failed`, `help_format_unknown`, `required_option_missing`, `required_value_unadvertised`, `policy_local_present`, `policy_local_unreadable`, `doctor_unavailable`, `doctor_timeout`, `doctor_failed`, `doctor_unrecognized` or `policy_unknown` (a policy reader that refused without a reason). Two small behaviour notes: the `--help` timeout for Claude is now 15 s (was 10 s), and `claude doctor` keeps the inherited environment without the `NO_COLOR`/`TERM=dumb` that the help and version calls add.

## [0.54.3] - 2026-10-19
### Fixed
- fix: make refusal providers mandatory and the refusal test hermetic
- fix: drop speculative help forms and name the real provider in refusals
- fix: ignore withdrawn value lists and read chained groups whole
- fix: accept the real Cursor and Antigravity help formats
- fix: cover unquoted choices lists in help parsing
- fix: accept common help layouts and close remaining parser false positives
- fix: harden help parsing and report accurate refusal stages
- fix: keep first help declaration and report preflight on every failure
- fix: discover reader CLI capabilities from --help instead of versions


## [0.54.2] - 2026-10-19

### Fixed
- A task waiting for `task.authorize_run` no longer waits in silence. The wait shows when it began and when it ends in the task list, the task views and the console; it is written once to the audit; it expires (`SOLAR_APPROVAL_WAIT_HOURS`, default 72, `0` turns it off): a one-off task goes back to draft, a recurring one skips only that occurrence and keeps its schedule; and the configured Telegram chat is told once when it begins and once when it ends, through the existing task notifier (title only, never the chat a task names). `task.authorize_run` is unchanged.

  Upgrade note: the wait counts from the approval, so a task already waiting longer than the limit (72 h by default) when this version is installed ends at its first claim, with one notice each. Set `SOLAR_APPROVAL_WAIT_HOURS` in the supervisor, MCP server and console environment alike (`0` turns the expiry off).

## [0.54.1] - 2026-10-19

### Fixed
- Approval friction: every MCP task operation asked a native form (126 confirmations granted in 7 days, 27 attempts left unapproved, no form in Claude Desktop, 8 forms to launch 4 requested reviews). MCP task lifecycle operations (`task.create`, `update`, `schedule`, `approve`, `return_to_draft`, `cancel`, `requeue`, `archive`) no longer ask a native form: the client's own tool permission is the consent. Risk is decided when the task is claimed: a task confined by a verified restricted read-only profile runs; any other task waits as `awaiting_approval` until `task.authorize_run`. External sends and capacity changes keep their form; tasks approved before this change keep running.
- `task.create` accepts `queue: true` to create and queue in one call (the gate audit keeps the argument). `task.requeue` and a recurring task keep their consent marker and authorization while the approved content is unchanged.

### Added
- `task.authorize_run` (native confirmation, bound to the approved content), `run_risk` / `needs_run_authorization` in solar-state, and `risk` / `awaiting_approval` in the task detail view.

## [0.54.0] - 2026-10-18

### Added
- Repository reviews now record the repository HEAD when the review finished (`Repository HEAD when the review finished: <id>`, same as / differs from the reviewed commit, or `unknown`) right after `Reviewed commit`. It is a record, not a gate: it never rejects or fails a review and stays out of the manifest and digest. Statements by the model about HEAD remain commentary.

## [0.53.1] - 2026-10-18
### Fixed
- fix: cap the task result view on bytes and cover multibyte replies
- fix: keep the provider's own headings in the task result view


## [0.53.0] - 2026-10-18

### Added
- Opt-in local evidence for Codex repository reviews (`SOLAR_ROUTER_REVIEW_EVIDENCE_DIR`, off by default): a redacted copy of the provider JSONL and final-message file in a mode-0700 directory with bounded retention (`SOLAR_ROUTER_REVIEW_EVIDENCE_KEEP`, default 10), kept for completed, failed and timed-out launches. `meta.json` records the model id and reviewed commit (never the prompt) to attribute a folder to its task. A pre-existing evidence directory open to group or others is refused, never chmod-ed (create it with `mkdir -m 700`), and an enabled capture that cannot run warns on stderr. Capture never changes review outcomes and never writes argv, env, stderr or credentials. Redaction is pattern-based, so the directory should still be treated as sensitive.

## [0.52.4] - 2026-10-18

### Fixed
- Codex repository reviews no longer accept interim agent messages as the review: the result comes only from the CLI's final-message file under a requested JSON schema and is validated (one non-empty `review` string); progress-only or malformed output, missing files, error events and non-single completed turns fail instead of completing. Limit: this checks the output shape, not review quality, and a schema-conforming placeholder is still indistinguishable from content.

## [0.52.3] - 2026-10-18

### Fixed
- Preserve the originating MCP progress token when requesting native confirmation so hosts can route the form to the correct conversation, without treating routing metadata as approval.

## [0.52.2] - 2026-10-18

### Fixed
- Diagnose negotiated MCP form confirmation separately from native question tools: report advertised support, attempt and outcome, explain unsupported-connection refusals, and reject malformed form capabilities without weakening approval requirements. Preserve original operation responses when their content cannot carry diagnostics.

## [0.52.1] - 2026-10-18

### Fixed
- Bind MCP stdio startup to the validated registered workspace regardless of a GUI client's launch directory, preserving existing registrations, runtime ownership checks and native approval requirements.

## [0.52.0] - 2026-10-18

### Added
- Commit-bound repository reviews alongside packet reviews: guarded Claude/Codex/Cursor/Antigravity CLI constructors, isolated snapshots, native review/batch preparation, derived child authorization and version-labelled results. Production capacity and enabled profiles remain unchanged.

## [0.51.2] - 2026-10-18

### Fixed
- Isolate Solar Client smoke workspaces, runtime state, install copies and service controls; report command errors separately from `.env` preservation failures.

## [0.51.1] - 2026-10-18

### Fixed
- Retain attached execution reservations until the owner and every recorded process group are proved gone. Persist ending markers and cleanup holds in schema v7, import legacy holds during backed-up cutover, and recover ending executions without rerunning completed work (#39).

## [0.51.0] - 2026-10-18

### Added
- Isolated opt-in macOS launchd evidence harness and integrated simulated concurrency/update regressions; production capacity remains 1 and reader profiles remain disabled.
- Async 3/5 rollout and safe reversal runbook, plus an offline quality-pilot preparation/report runner, shared rubric and paired results template. Real provider quality validation remains separately authorized and unexecuted.

### Fixed
- Wait for git identity collection throughout update, staged cutover, installation, status parsing and update-cache helpers before printing or advancing, avoiding a macOS Bash 3.2 process-substitution signal race that could abort portable updates with an interrupted write.

## [0.50.0] - 2026-10-17

### Added
- Guarded Claude `text_only_review_v1` adapter with one restricted launch constructor for run and stream, canonical approved envelopes, input budgets, token-bound router isolation and source revalidation. Unknown effective managed policy rejects real launches; production reader profiles remain disabled and capacity remains 1.
- Transactional, idempotent derived review children with bounded approved policy, individual approval snapshots, provenance checks and one recorded parent synthesis attempt. Legacy children without provenance remain nonexecutable. The console groups approval/provenance waits as authorization pending.

### Changed
- A provider's subtask declaration no longer authorizes arbitrary queued children. Only exact approved review templates and immutable input digests may be materialized. Interrupted synthesis requires explicit recovery rather than automatic replay.

## [0.49.0] - 2026-10-17

### Added
- Resident async-tasks supervisor (`supervisor.py`, one per workspace/runtime): the only holder of the atomic lock `<runtime>/async-tasks/.locks/supervisor.lock` (resolved through solar-paths, bound to the workspace owner), it claims through the same reservations as every other entry point and dispatches each claim by id and token to its own executor in its own process group. Executions are collected with wait/poll, a free place is filled within one second of one ending (or on `SIGUSR1`) without waiting for the 60 s tick, and a place is forgotten only after the executor's process group is proved gone. At start it reconciles processes and leases: live owners from a previous supervisor are adopted, an owner it cannot identify stays blocked, an executor lost without finishing is failed (never run again), and a group it cannot prove is its own is never killed. Cancellation stops only that execution's group; a failed cleanup blocks the affected resource and nothing else; lowering the capacity never stops a running execution. Contract: `core/docs/async-supervisor.md`.
- `launch_supervisor.sh` (detached `Popen(start_new_session=True)`, stdin null, output to the supervisor's log, no inherited pipes) and `stop_supervisor.sh --drain [--timeout N]` (the contract the update's drain already expected: stop dispatching, collect, exit; never removes the lock, never kills by pid).
- `/api/console/capacity` and a card on the executions screen: places used and free, tasks running at once, why each queued task waits (dependency, resource, provider, capacity, recovery), the supervisor's published state, and the applied configuration revision with the differences a pending proposal would make. `Session.queue_waits()` (read only) backs it.
- Pass-stamp results `starting` and `blocked`.
- `cleanup-holds.json` (read by every claim): from its dispatch, and after the executor gives its reservation back, what an execution holds (capacity, resources, scopes) stays taken for the supervisor, `activate.sh`, the diagnostic worker and adoptions until every one of its process groups (the executor's and the command's) is proved gone; it survives a restart. Stopping an execution also ends the command's own process group (the one the router creates) before its place is freed.

### Changed
- **Behaviour:** the cutover's default process listing ignores Solar processes of other installs (an absolute script path outside `SOLAR_CUTOVER_INSTALL_ROOTS`, set by the update to the live install), so another checkout's supervisor no longer makes it wait. `solar_client_drain_async` tells apart a drain that timed out (1), a supervisor that could not be identified (2) and blocked executions left behind (3). A pre-start hook has a deadline.
- **Behaviour:** `ensure_async_tasks.sh` no longer runs `run_worker.sh --once`. It observes the supervisor's identity (pid and start time; it never takes the lock or writes its pid), starts one candidate when none is alive, waits at most 5 seconds for the handshake and answers with a JSON object and the exit code `0` ready, `10` starting, `20` blocked, `1` failed. `check_async_tasks.sh` observes the same identity with the same codes. A held maintenance barrier answers `20` (it used to exit 0 with a message). The previous design's machine guard (`/tmp/solar-async-tasks-worker.lock`) is only read, never written or removed: a worker still running delays the supervisor (`10`, then `20` after 120 s).
- **Behaviour:** `run_worker.sh` is no longer a production entry point and refuses to run without `--diagnostic`; it still goes through the same reservations.
- **Behaviour:** `run_orchestrator.sh` maps ensure's answer to the stamp: `0` → `ok`, `10` → `starting` (not a failure), `20` → `blocked` and `1` → `failed` (both count as a failure and ask for attention). The gateway and the host are processed in every case. `write_pass_stamp.sh` accepts `ok|failed|skipped|deprecated|ignored|starting|blocked`; the console treats `blocked` like `failed` and `starting` as neither a fault nor a success; `check_orchestrator.sh` reports the supervisor by state and no longer suggests removing `supervisor*.lock`.

## [0.48.0] - 2026-10-16

### Added
- Execution reservations (schema v6, applied only by the cutover, with a backup first): taking a place and becoming `active` are one transaction for `task_claim`, `task_claim_next`, `activate.sh`, the worker and the generic move to `active`. Global capacity (initially `1`), provider limits, declared access (`access_policy`: read/write, canonical scopes with parent/child overlap and symlink aliases, exclusive resources), tasks that declare nothing run alone, and a drain barrier so a stream of readers cannot starve an exclusive task after `exclusive_wait_seconds`. Contract: `core/docs/execution-reservations.md`.
- Execution token: the claim returns it; completing, releasing, failing, awaiting and recording a pid need it, with a lease and heartbeat; `execute_active.sh --task <id> --token <token>` runs exactly the claimed task and `--once` only takes over an execution nobody runs. `start_next.sh` writes the claim to `$SOLAR_CLAIM_FILE`.
- Versioned execution configuration: operations `async_execution.propose` and `async_execution.apply` (A2) prepare `<runtime>/async-tasks/config/async-execution.json` and apply a validated revision to the runtime's policy in one transaction; editing the file activates nothing. `solar_state.py async-policy status|apply`.
- Material keys `access_policy`, `subtask_policy`, `execution_profile`, `review_input_digest` and `review_input_manifest`, covered by the digest only when declared (the digest stays `v2:`; no standing approval changes). `task.create`/`task.update` accept `access_policy`.
- Update sequence with a maintenance barrier: the target is staged and checked first, then `client_update_staged.sh` runs maintenance, drain, stop, cutover (backup, code replacement and migration under one exclusive lock), restart, verification and release. `solar client update --resume` continues an interrupted update; `--no-restart` holds the barrier; `--check` writes nothing. `async-supervisor` is a detected and drained service and `supervisor.py` is a running marker for the cutover. The migration result lists legacy subtasks (no record is backfilled).

### Changed
- **Behaviour:** an update no longer replaces the code before it stops anything; a failed update keeps the services stopped and the barrier held until `solar client update --resume`. A release older than this one cannot give that order: run `client_update_staged.sh` with explicit paths for the first installation (see `core/docs/execution-reservations.md`). The cutover marker also records the schema; a marker without it never lets an update skip the stop and cutover.
- **Behaviour:** `activate.sh` and `task_claim` revalidate dependencies and a pending cancellation, and refuse when the task does not fit (capacity, access, maintenance). With the initial capacity `1` the worker stays sequential.
- **Behaviour:** a declared `access_policy` makes a task concurrent only when its `execution_profile` is in the policy's `enabled_reader_profiles` (empty at first); every other task still runs alone, so raising the capacity changes nothing until a confined profile is enabled. Enabling is not enough either: the profile needs a verified implementation for the provider (`VERIFIED_PROFILES`, empty in this delivery), so every task still runs alone until the profile is delivered.
- **Behaviour:** `complete.sh`, `task_complete`, `task_release`, `task_fail`, `task_await` and a transition out of `active` refuse a missing or stale execution token (`StaleToken`) while the task holds a reservation.

## [0.47.1] - 2026-10-16

### Fixed
- `solar client update` no longer stops with `CutoverRefused: base schema v4, this code speaks v5` on an already-migrated base: the cutover now upgrades a base that is only behind in schema, and a failed upgrade changes nothing. **To recover a runtime left at v4 by v0.47.0, update to the release with this fix and run `solar client update` again.**

## [0.47.0] - 2026-10-16

### Added
- `task.return_to_draft` (A2, `task_id` + `expected_row_version`): a queued task goes back to draft keeping its id, body, schedule, run counters and history. `approved_*` are withdrawn (the previous digest stays in `audit` as `task_approval_withdrawn`) and the worker cannot claim it until `task.approve`. Schema v5 adds `queued -> draft` to the `transitions` table of existing bases.
- `approval_digest_mismatch` (`audit` row once per row version, a log line on every refusal, and the console task list): the reason is `absent`, `legacy` or `mismatch`.
- The console list shows one row per logical task: finished older versions fold under the newest one linked by `revises_task_id`, which `console_tasks` now projects.

### Changed
- **Behaviour:** `task_claim`, `task_claim_next` and `activate.sh` take a queued task only when its approval covers what is stored. The digest (now `v2:`-prefixed) covers the material fields without the title, and the definition: the body without the `# {title}` heading and without the runtime sections. `task.approve` records it, with a snapshot of the definition, with or without `expected_row_version`; a task created already queued is stamped the same way. **Release note: every row already `queued` (recurring ones included), and any imported by the cutover, carries no `v2:` digest and is NOT claimed until it is approved again with `task.approve`; nothing is converted automatically and nothing is announced beyond the log, `audit` and the console. Right after upgrading run `python3 core/skills/solar-state/scripts/solar_state.py task list-unapproved` and approve each task.** Executor settings (`executor`, `local_command`, `local_timeout`) are now part of what is approved. Contract: `core/docs/task-approval-contract.md`.
- `task.update` and `task.schedule` accept queued tasks. A rename keeps the place and the approval; any other change returns the task to draft in the same transaction. Results, delivery and errors of earlier runs and `recurring_run_count`/`recurring_last_run` are kept.
- `activate.sh` fails when its claim is refused (no `Activated`, `blocked_by_task_ids` kept) and `recurring_last_run` is stamped only after a winning claim. `approve.sh` no longer reports success when the approval fails.

## [0.46.0] - 2026-10-15

### Added
- Console identity: `GET /health` and `/api/runtime/health` now report the physical `workspace` and `runtime` of the console. `core/skills/solar-app/scripts/host_identity.py` is the single decision point (`match`, `mismatch`, `legacy`, `partial`, `unreachable`, `invalid`), compared on physical paths, and it is applied by `check_host.sh` (with and without flag), `ensure_host.sh`, `start_host.sh`, `stop_host.sh` and `solar_host_stop_orphan_listeners`. Contract: `core/docs/console-identity.md`.
- `solar_test_guard --services` (opt-in) aborts a test whose service detection is real and whose effective install is the real global install; the LaunchAgent still needs a `launchctl` double. Contract: `core/docs/test-isolation.md`.
- Test-only port override `SOLAR_APP_TEST_MODE=1` + `SOLAR_APP_TEST_PORT` (process environment only; never selects 9000, ignored in a workspace `.env`). A suite-wide guard records the listeners on :9000 before the first test and fails the run if a new one remains.

### Changed
- **Behaviour:** a console that answers but serves another workspace or runtime, or reports no or partial identity, no longer satisfies `check_host.sh` (exit `3`, `--json` gives `available: false` naming the identity) or the system supervisor, which prints `status: UNTRUSTED` and counts the host as DOWN. `ensure_host.sh` and `start_host.sh` refuse it with a diagnostic (who removes it and how) and do not retry. After upgrading, an older console that predates identity is replaced on the next `ensure_host.sh`/`start_host.sh` if it is provably this runtime's (runtime pid file or this install's `host_server.py` path); otherwise it is left running and reported.
- `solar_host_stop_orphan_listeners` no longer stops any listener that merely looks like the console: it stops proven-own listeners only, reports the rest and returns non-zero. `solar_host_stop_pid` signals only a live `host_server.py`. Listeners are matched to exactly `SOLAR_APP_HOST:port` (another loopback address, a LAN address or the wildcard is not this console); without `lsof` an unidentified console is neither adopted nor stopped. `stop_host.sh` ignores a stale or recycled pid file.
- The loopback health probe ignores proxies configured in the environment. `/health` also reports the console's `pid`; stop and pid-file repair act on that pid (never on every listener of the port), and listeners are matched to exactly `SOLAR_APP_HOST:port`. A console of this runtime that still reports a previous workspace (`stale_workspace`) is stopped and replaced rather than stranded as `UNTRUSTED`; a differing runtime is always refused.
- Known limit: a hung console of another workspace served by the same install is recognised by install path only and can be stopped (the runtime pid file is the strong proof); an answering console is never judged that way. See `core/docs/console-identity.md`.
- The console port is no longer written to `.env`: `onboard_host_env.sh` and `client_init.sh` stop emitting `SOLAR_APP_PORT` (the key was already ignored); the doctor assumes 9000. The shipped `workspace.env.example` no longer lists it either. The console copy and the port label name the real port (`{port}` placeholders; the label falls back to 80/443 by protocol), which only differs under the test override.
- A pid reported by a console is signalled only if it is also the listener of `SOLAR_APP_HOST:port` (when `lsof` exists), on every stop path.
- `solar status` shows the reason (`error`) when the console answers but is not this one, instead of a bare DOWN.
- `solar_test_guard --services` also judges a simulated process table (`SOLAR_CLIENT_PS_OUTPUT_FILE`): detected host/gateway services need their stop/start hooks.
- `test_discovery_profile.py` simulates "no service running" and calls the guard with `--services`, so a full sync can no longer stop or start the services of the install it runs from.

### Fixed
- A test suite could stop or replace the real console and leave it served from a pytest temporary directory, and the supervisor accepted any console that merely responded.

## [0.45.0] - 2026-10-14

### Added
- Dashboards: a planet declares its surfaces in its own `planets/<planet>/.solar/dashboards.json` (a stable `name` with no dots, title, description, owner, `updated_at`, `mode`, and **exactly one** of loopback `url` or in-planet `file`) and this machine registers the declared ids in the `dashboards` block of `.solar/settings.json` (`enabled`, `registered` with an optional machine-specific `start_command`). A **tool** (`url`) is a loopback HTTP root this machine registers and starts by hand; a **view** (`file`) is a read-only HTML page the planet generates, served by the console itself from `GET /dashboards/<planet>/<name>`. The console joins both in a read-only screen after Tasks (internal id `dashboards`) and in the new `GET /api/console/dashboards` route. The stable `name` is the identity: changing the target keeps `/dashboards/<planet>/<name>`. A view's link is built from the planet and the entry name, never from the declared path: the route re-resolves the file against the declaration, confines it to the planet's `operations/`, requires a lowercase `.html` suffix, refuses a symlink hop and caps it at 4 MiB, then serves it under a restrictive CSP (`default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox`, plus `nosniff` and `no-referrer`). A view reports the file's own **mtime** as freshness, never a date the HTML claims. A single malformed entry is reported with its own id and never hides the valid ones; a registered id with no declaration is surfaced as `registered_dashboard_not_declared`. `solar client sync dashboards status|list|seed|register|unregister|enable|disable`: `register`/`unregister` write settings only and never start, probe or read a planet file; `seed <planet> [--force]` is the only subcommand that writes inside a planet, creating the declaration when absent, validating an existing one without writing, and (with `--force`) writing a new exclusive backup and refusing when the file has uncommitted git changes unless `--allow-dirty`. The declaration gets its own confinement (inside the planet, a regular `.json`, no symlink hop, `.solar` never a symlink) instead of a shared `operations/` confinement, respects Client planet exclusions and is capped at 128 KiB. Starting a registered surface stays an explicit operator action: the console shows the start command as escaped copyable text and never runs it.

### Changed
- **Breaking: the operational-report concept is retired; its views become dashboards.** The console no longer has a report surface: `GET /api/console/reports`, the `/reports/<planet>/<relative-path>` file route, the navigation id `reportes`, the `report` kind and the `operations/leadership/reports/index.json` publication index are gone. What a planet used to publish as a report is now declared as a `file` dashboard entry and served, read only, by the dashboard route. The read-only scoping pieces both surfaces shared (planet exclusions, bounded reads, the published-planet walk) moved to the neutral `operation_publication.py`; `app_http.py` no longer imports a report reader. **Migration (one line):** a planet still writing `operations/leadership/reports/index.json` must stop writing it and declare each view as a `file` entry in its own `.solar/dashboards.json` instead; the index is no longer read.
- The console navigation id for the screen after Tasks is `dashboards` (was `reportes`); the route, title and question are unchanged.
- `solar client sync dashboards enable|disable` copy no longer mentions reports, and `disable` states plainly that the console then lists no dashboards at all, views included.

### Fixed
- `solar client sync dashboards seed --force`: the backup is now created exclusively (`O_CREAT|O_EXCL|O_NOFOLLOW`), so a symlink planted at `dashboards.json.bak` can no longer redirect the write outside the planet; a repeated `--force` adds `.bak.2`, `.bak.3`, … and never replaces an earlier backup.
- Dashboards reader: a non-string `mode` (for example `[]` or `{}`) is refused as an isolated entry instead of raising `TypeError` and discarding every dashboard of the planet; a malformed registration block is reported without hiding the declared views; an uppercase `.HTML` suffix is refused, matching `seed`, so an entry can no longer list as valid and then 404; and the registration is read through the same `.solar/manifest.json` legacy fallback as the CLI.
- `solar client sync dashboards register` no longer rewrites the `scope` and `layout` keys, which are owned by `client_lib.sh` and `codex_agents.py`; `write_config` uses `setdefault`.

### Removed
- `core/skills/solar-app/scripts/operation_reports.py` and `core/skills/solar-app/references/operation-reports.md`.
- `core/tests/skills/solar-app/test_operation_reports.py`; the report fixtures and assertions in `test_console_ui.py` and `test_operation_dashboards.py`.

## [0.44.0] - 2026-10-13

### Changed
- **A Solar Client older than this version refuses the new manifest (format 2, exit 5) once a workspace has migrated, so update every machine or checkout that shares that workspace before running `solar client sync --codex-only` on it.** Automatic migration happens on the next `sync --codex-only` (or full sync) with publication enabled: the manifest moves to format 2 (format 1 is still read) and each unchanged `solar__*` file (manifest, generation mark, `name` and hash all match) is replaced by the new role in the same locked run; edited, unmanaged or manifest-less `solar__*` files are reported as conflicts and left untouched. A second run changes nothing, and an interrupted run converges on the next one.
- Native Codex agents are published as `<planet>:<agent>` (for example `uhorizon:uh-backend-dev`) instead of `solar__<planet>__<agent>`: the role `name` and the file `<planet>:<agent>.toml` use the contract `name` as is (hyphens and case kept, no `_` rewriting), the same string already used as the identity in the exclusions (which still match `-`/`_` and case loosely). Planet and agent names accept only `[A-Za-z0-9._-]`, must start with a letter or digit and are at most 64 characters; invalid names are rejected with a reason, never substituted. Publication stays off by default.
- `:` in file names is not portable to Windows. No extra Windows check was added on purpose: the publisher already requires POSIX locking (`fcntl`) and never runs there; the limit only affects checkouts shared with Windows. A letter-case-only rename of a contract publishes the new role one sync later.

## [0.43.0] - 2026-10-13

### Added
- Opt-in native Codex agents: with `solar client sync codex-agents enable`, `solar client sync` also publishes derived roles from top-level `planets/<planet>/agents/*.md` contracts into `.codex/agents/solar__<planet>__<agent>.toml` (only `name`, `description`, `developer_instructions`), tracked by a hash manifest so edited, unmanaged or colliding files are reported and never overwritten, and unchanged generated files are retired when a contract goes away. Adds `codex-agents status [--json]|preview [--contents] [--json]|enable|disable` and Codex-specific exclusions (`exclude --client codex <planet>|<planet>:<agent>`, including the `--client=codex` form) on top of the global ones; an excluded planet is never opened by the publisher. Off by default and silent while disabled; other clients are unchanged.
- A contract that still exists but no longer validates (broken frontmatter, empty body, serialization failure) keeps its published role (`kept: contract is invalid`): editing a contract never deletes the agent. It is retired only when the `.md` disappears or the agent/planet is excluded.
- Renaming a contract (letter case, `-` vs `_`, new stem) updates the published role in place, but only after confirming the previous source is gone (the `.md`, its `agents/` dir or its planet no longer exists): the previous identity is adopted by the new source in the same plan, so it is never kept and retired at once (previously the file was deleted and later runs reported a persistent conflict). A previous source that is still present (invalid contract, unreadable, name mismatch, excluded/unobservable planet) keeps its published role and is reported as a conflict. Two sources sharing a public name remain a conflict.

## [0.42.1] - 2026-10-13

### Fixed
- Console Autonomy "Latest decisions": the MCP gate audit writes a decision row and an outcome row per call, and both were counted as decisions, inflating the total and showing every outcome as "Denied". Only decision rows (and older rows with a boolean `allowed` and no `kind`) are counted and listed; the payload (`total`, `allowed`, `last`) is unchanged.

## [0.42.0] - 2026-10-12

### Added
- Read-only operational reports from explicit planet indexes. Paths are confined to each planet's `operations/` directory, refusing both a symlink within it that points elsewhere and an `operations/` that leaves the planet, and are served with a sandboxed CSP that omits top navigation and popups.

### Changed
- Console: the IDEs screen is renamed Apps (menu, title, question and headings in English and Spanish). Its internal id and `/api/console/ides` route are unchanged.
- Replace global Continuity navigation and its summary card with Reports, and rename External entry to Channels (diagnostics only, no conversation history). The legacy continuity endpoint is retained. The three-tool MCP contract is unchanged.

## [0.41.0] - 2026-10-12

### Changed
- Console Tasks status filters: the eight per-status chips and their recurring counters become seven groups in one toolbar: Errors (error, never hidden; at 0 it shows a green check and a good-news panel linking to the next pending group), Running (active, only when some task is active), Drafts, Queue (planned, queued), Done (completed), Closed (cancelled, archived) and All, plus a real "Recurring" checkbox that intersects the group and drives the counts. Empty groups hide unless selected. The default is the first non-empty of Errors, Running and Drafts, else All, decided at each opening; the selection can ride in the URL hash across a reload. Active tasks list first; a parent's subtask count stays every child, filtered or not. Row pills show all eight states with glyph and text (red only for error, blue only for active) and a recurring mark follows the id. The toolbar has roving tabindex and arrow keys (the Recurring checkbox stays outside it and is reached with Tab), count labels, a stable polite live region outside the repainted block (the only status region: an empty group announces its own title, and the zero-errors panel does not announce itself), and a light focus ring that survives a repaint; below 900 px it uses two touch-sized rows with the Recurring switch sharing the first row inside the toolbar box, at the right edge. Presentation only: no data, state machine or endpoint changes.

## [0.40.1] - 2026-10-12

### Fixed
- Console task detail follow-up: link ports must be 1 to 65535, bracketed IPv6 hosts must be valid addresses and internationalized host names stay text; the workspace id is shown; a context or configuration that is not an object no longer breaks the block; the host logs the 503 warning (exception class only) through the `solar.app` logger, adding a stderr handler only when neither that logger nor the root logger has one (a configured root is trusted and propagation is unchanged; if the root is configured after the console started the warning can print twice, which is accepted), and unexpected read errors on other console routes answer a fixed message instead of the exception text.

### Changed
- Console Tasks screen: the list and the detail share the width evenly (stacked below 900 px) instead of a fixed 320 px detail column; up to 1600 px the list shows Status, Task and Created; field lists use two label/value columns that wrap long values; schedule days show names and a run limit of 0 shows as unlimited; "No recorded checkpoint" replaces "No recorded context" when a schedule is shown; the complete record keeps the frontmatter folded (it folds again when the record closes) and the instructions apart; the task History lists the newest event first.

## [0.40.0] - 2026-10-12

### Added
- Console task detail: selecting a task reads, on demand and read only, a curated "Context and follow-up" block (recorded checkpoint, owner, next check, wait, decision, stored schedule with IANA timezone and resources). The checkpoint parser is shared with the MCP task views, whose three tools, schemas and `checkpoint_invalid` refusal are unchanged. An invalid checkpoint or unreadable frontmatter is reported for that task only as a stable `context_error` code and does not hide its schedule or history. The complete stored record (every column, every frontmatter entry, instructions rendered as sanitized Markdown with only http, https and mailto links) loads only on an explicit `full=1` request; failures answer with a fixed message, never exception text.

## [0.39.1] - 2026-10-12

### Changed
- MCP: native confirmations are now a compact, human summary (action, object, concrete changes, effect, reason) in the configured console language, instead of JSON arguments, the full task state, identifiers and hashes. The text is generated from validated arguments and the stored task; approval binding, authority, row version, expiry and single use are unchanged. See `core/skills/solar-mcp/references/approvals.md`.

## [0.39.0] - 2026-10-12

### Changed
- MCP: the public catalog is now exactly three tools. `solar_search` finds capabilities, documents, operations, resources and tasks and reads one task (detail, instructions, config, status, result, error, history). `solar_docs` reads skills, framework documents (`core-doc:`) and operation contracts (`operation:`), whole or by section. `solar_execute` runs one registered operation with a closed per-operation schema, authority and approval. The nine previous tool names answer with a non-executing `tool_renamed` error for two minor releases (recorded in the gate audit), and Client discovery verification accepts either catalog meanwhile. Mapping and policy: `core/docs/mcp-tool-migration.md`. Resources are unchanged.
- MCP: approvals bind the operation name and exact arguments. `telegram.send` always needs an explicit `chat_id`; `task.create` always stores a draft (`queued` and `description` became `task.approve` and `instructions`); `action.run` takes its mandate from the registration (none registered: refused; a different caller-supplied one: refused). Cancel and requeue require `expected_row_version`. The operator approval CLI grants only registered A2 operations with valid arguments. Every decision gets a `trace_id` and an outcome row in the gate audit.

### Added
- Task management through MCP: `task.update`, `task.schedule` and `task.archive`, and `task.create` with `revises_task_id` for a draft revision of an approved task. Editing and scheduling never queue; only `task.approve` does, for the exact stored version (`expected_row_version`). Approved, active and finished tasks keep their instructions. Archiving keeps the row, body and events; a queued recurrence is cancelled and archived in one step.
- solar-state: optimistic `row_version` checks, `task_update`, `task_archive`, an approval digest recorded on approve, and `scheduled_timezone` (IANA) so weekly schedules keep their local hour across daylight-saving changes.

## [0.38.2] - 2026-10-10
### Fixed
- fix: remove the authoring skill dependency from the agent template


## [0.38.1] - 2026-10-10

### Changed
- Rename the agent authoring skill to `solar-agent-creator` and focus its workflow on creating and improving contracts, approved learning, memory and continuity. Keep the `solar agent` CLI interface unchanged.

## [0.38.0] - 2026-10-10

### Changed
- Agent learning now lives in dated contract lessons (up to 10), optional shared planet memory (up to 20 records and 100 lines, whichever is reached first), or reusable skills, with validated promotion and a legacy migration policy. Aligned core governance and planet creation guidance with the canonical learning policy; updated agent and memory templates, app loading requirements, and guidance for client sync and renewing exported continuity after contract changes.

## [0.37.0] - 2026-10-09

### Added
- Explicit agent continuity CLI: identity-scoped reads, bounded portable exports and verified restore without carrying permissions or activating tasks.
- Opt-in planet execution facts: initialization references an existing approval, with evidence references, idempotent event keys and backup/restore, leaving shared machine-state storage unchanged. The workspace AGENTS template now scopes the planet-local `.solar/` fact destination.

## [0.36.0] - 2026-10-09

### Added
- `solar-agent` v1: canonical agent contracts across clients, reusable templates and human-approved file-based lessons. Runtime continuity and execution databases remain outside this documentation-only skill.

## [0.35.0] - 2026-10-09

### Added
- MCP task status with a task ID reads stored agent/responsibility identity and continuity checkpoint details through solar-state. Queue listings remain summaries; reading recorded evidence does not verify an effect or authorize a retry.

## [0.34.2] - 2026-10-09

### Documentation
- Record the capability-discovery experiment: four fresh Codex rounds showed that the reduced profile saves about 4,200 tokens per request but does not lower session cost (mean total input about +5 %, uncached about +22 %). The profile stays opt-in and not enabled; the profile reference lists the evidence, the cause and how to measure a future attempt. No runtime change.

## [0.34.1] - 2026-10-08

### Changed
- Capability describe outline responses include a short `usage` hint. Complete-body and single-section responses omit it. The tool description and the property descriptions point at `section` instead of treating `full=true` as the ordinary way to read a skill. Parameter names, types, and defaults are unchanged. The 85% threshold includes `usage`, so an outline that was just under that line can now return the complete body.

## [0.34.0] - 2026-10-08

### Fixed
- Capability describe keeps a heading that follows a fenced block. The block is indented by at most three spaces and closes only on the same character repeated at least as many times as it opened. Four spaces, a tab, a shorter run, the other fence character, or backticks inside a paragraph no longer hide a later section.

### Changed
- Capability search descriptions are at most 120 characters, cut on a word boundary, with an ellipsis only when the text is cut. A limit above 10 is applied as 10 and reported with `limit_capped`, instead of refusing the call.
- Capability describe returns a heading outline for units larger than 4 KiB. The outline keeps the preamble before the first level-2 heading, and copies governance sections in full. A heading is governance when its title contains, without regard to case, any of `authority`, `gate`, `governance`, `safety`, `never`, `approval`, `autoridad`, `gobernanza`, `seguridad`, `nunca`, `aprobaci`, `obligatori`, `prohib`, `regla`, `límite`, `limite`, `dependencia`, or `antes de`. `section` reads one exact heading and `full` returns the complete unit. Units of 4 KiB or less still return the complete text. A preamble or governance section that does not fit in 64 KiB refuses the response instead of being cut. When the outline response JSON would not be smaller than 85% of the complete-body response JSON, describe returns the complete body instead.

## [0.33.1] - 2026-10-07

### Fixed
- A finished file migration is no longer resumed as if those files were still the source of truth. `migrate` records that the move finished. When that record is present — or, for an older marker, every original source in `pre-state-<stamp>/` is already aside — and no old-format file remains in place, it returns already and does not run catch-up. One file set aside is not that record. A task whose status has since changed in the base, and a log that exists only under `task-logs/`, no longer refuse the cutover, so `solar client update` can record the new install. A source deleted before it was set aside is still refused. `.DS_Store` is not an old-format file and does not reopen catch-up. The migration marker is replaced from a temporary file, so a crash during the write leaves the previous marker readable. An interrupted migration, with old files still in place, still refuses a real change in a file.

## [0.33.0] - 2026-10-07

### Added
- Shared eligible skill inventory, bounded MCP capability Search/Describe and
  opt-in Client-managed discovery publication for the shared `.agents` surface.
  Native publication stays the default; discovery verifies the registered
  Codex MCP before hiding managed skill names and supports native rollback.

### Fixed
- Client sync now reports a publication failure as an error and aborts for every
  client destination, rather than continuing after `sync-clients.sh` fails.
- Router documentation no longer claims `metadata.skills` injects descriptions.
- Token/session protocol v1.1 marks estimates and invented report figures,
  preserves all three session levels and distinguishes catalog bytes from usage.
- Discovery design separates task state writes from Telegram and
  action handlers; checkpoints are deferred to an independent review.
- Profile writes use the canonical Client writer. Codex-only discovery refuses
  Antigravity destinations, and unsafe individual skill packages warn and skip
  without aborting publication of eligible packages. Existing MCP verbs keep
  their original validation.

## [0.32.0] - 2026-09-30

### Added
- feat(solar-app): `/api/console/health` adds `attention`. Calm lists only non-zero counts. A fault or a missing check names the cause. The page shows that sentence.
- feat(solar-app): console copy is English unless `.solar/settings.json` sets `"language"` to `es`. Health returns that `language`. The page follows it, including the browser title. A missing key stays English.
- feat(solar-client): `solar client language set es` writes that key. `solar client update` keeps it. The alias table lives in `solar-client/scripts/console_language.py`. If that file is missing, the error names the path.

### Changed
- The console names continuity and delegations in plain language. A file with `revoked_at` is revoked: dimmed, dated, and not counted as active. Detail: `docs/tasks/2026-09-29-console-attention.md`.

## [0.31.1] - 2026-09-29

### Fixed
- fix(solar-state, solar-app): execution channels and distinct `user_id` values come from the audit start matched by `router_id`. An end with no start counts as channel `other`; its `user_id` is used only then. The requester screen shows that count and does not treat the values as people.

## [0.31.0] - 2026-09-29

### Fixed
- fix(solar-app): `/api/console/health` states the database, port 9000, system, router, LaunchAgent, and gateway. The console renders those states. A stale pass leaves system unverified unless that stamp recorded a feature failure. Changing the task filter keeps the detail on a visible task. Entrada externa uses the health read from the current visit. An unreadable continuity time stays on the screen as missing data.

### Added
- feat(solar-app): the console at `/app` is the eight-question view. It is HTML, CSS and JS with no build step. Inter and Montserrat ship under `assets/fonts/` with the SIL Open Font License and are served by `app_http.py`. Each screen reads `/api/console/*`. A 503 with `refused` shows the reason. The verdict comes from `/api/console/health`. The summary reloads every 30 seconds; the other screens reload when opened. Times use Europe/Madrid. The page does not mutate Solar, and it does not call the older `/api/app/*` routes.

## [0.30.0] - 2026-09-29

### Added
- feat(solar-state, solar-app, solar-system): the console can read the installation without creating runtime files. `read_session()` takes a shared lock on the existing `state.lock`, refuses when the lock, owner, format or schema is missing, and does not take the daily backup. Queries cover every task status, per-task history, subtasks and execution aggregates. Reconciled durations stay out of every average, and rows with no provider stay out of the provider buckets. Eight read-only routes answer the console questions, including mandate mode from the YAML. A fresh pass stamp is healthy only when local health, the connector, and the ws, http, and tunnel processes are all up; otherwise it is a fault. The host refuses to bind when `SOLAR_APP_HOST` is not loopback. Each LaunchAgent pass writes `runtime/system/pass-stamp.json` with the time, the result of each feature, and local gateway facts.

## [0.29.2] - 2026-09-28

### Fixed
- fix(solar-client): Codex no longer gets a second skill tree under `.codex/skills`. The v0.29.0 note was wrong: with `CODEX_HOME` unset, Codex open on the workspace reads `.codex/skills` as well as `.agents/skills`. Sync publishes Codex through the `.agents/skills` copies, shared with Antigravity. `--codex-only` publishes those copies. Solar symlinks already in the workspace `.codex/skills` are removed; a `CODEX_HOME` that points elsewhere is left untouched.

## [0.29.1] - 2026-09-28

### Fixed
- fix(solar-gateway): a tunnel outage no longer hard-stops retries for a year. `tunnel_recovery_failed` stays on the backoff cap and does not count toward `GATEWAY_FAIL_ATTEMPTS_CAP`. An older `env.fail` already exhausted with that reason is retried when preflight passes, without deleting the file by hand. While `cloudflared` is still running, ensure leaves it to reconnect for `GATEWAY_TUNNEL_RESTART_GRACE_SEC` instead of killing it on every pass.

## [0.29.0] - 2026-09-27

### Added
- feat(solar-client): `sync-clients.sh` publishes skills to Antigravity as copies under `.agents/skills` (`--antigravity-only`, included by default). Commands, workflows and rules are not published. A shared frontmatter `name` across planets is reported and left unchanged. Solar records the names it published in `.agents/skills/.solar-managed` and prunes only those. A folder that already exists and is not in that list is left in place and reported. Codex reads repo skills from `.agents/skills` and reads `$CODEX_HOME/skills` (`~/.codex/skills` when unset), so the workspace `.codex/skills` is a second copy only when `CODEX_HOME` points at that directory. Codex publishing is unchanged.

## [0.28.3] - 2026-09-27

### Removed
- remove(solar-app): `app_index.py` and `index.sqlite`. The console and `solar://index` read counts from the views in `state.sqlite`. An `index.sqlite` left in an existing runtime can be deleted by hand.

## [0.28.2] - 2026-09-27

### Fixed
- fix(solar-router, solar-client): `--stale-count` no longer prints 0 when `session()` refuses. The reason goes to stderr and the command exits non-zero; `solar status` shows `unknown (state refused: <reason>)`. `solar status --json` reads that reason from the environment, so a quote or backslash in it does not break the JSON. The status host fixture claims its runtime and writes audit rows through solar-state when the runtime is sqlite.

## [0.28.1] - 2026-09-26

### Fixed
- fix(solar-client): `solar_client_git_dirty` returned success on a clean tree, and the clean branch of `solar client update` printed "uncommitted changes". The function is `solar_client_git_clean`. A clean git install reports the rollback checkout; a tree with uncommitted changes reports those changes.

## [0.28.0] - 2026-09-26

### Fixed
- fix(solar-client): a shell test that runs `init`, `sync` or `update` no longer uses the machine runtime or the system `launchctl`. The harness guard asks `solar-paths` for the runtime (`solar_runtime.py runtime`) with `SOLAR_RUNTIME_ROOT` and `SOLAR_APP_DATA` unset, and aborts when the test would use that path or when `launchctl` is not a test double.
- fix(solar-client): the portable bundle now follows skill imports that are built from path pieces (`parents[2] / "solar-state" / "scripts"`, `_SKILLS / "solar-x" / "scripts"`). `solar-state` is included with every skill that imports it, and a skill in the bundle cannot import a skill that was left out.
- fix(solar-client): `solar_client_state_cutover` checks that the cutover script exists and that `solar-state` is complete in the active install before it stops the LaunchAgent, the console or the gateway. A miss exits with an error and stops nothing.
- fix(solar-client): in portable mode, `solar client update` updates the global install and regenerates `.solar/bundle`. It no longer treats the bundle as the install. If no global install exists it says so and exits before it changes anything. A global install without `.git` is updated with `--bundle` (`mode=bundle-core`), the same contract as a non-portable install; the snapshot is not that install. Services keep running from the global install; the LaunchAgent plist `SOLAR_ROOT` stays that path, so a bundle snapshot is not a binding mismatch.
- fix(solar-client): in portable mode, `solar client sync` claims the runtime and runs the state cutover against the global install. `.solar/bundle` only publishes the IDE links. Stop and start scripts are that install's, so a console or gateway started there is seen before the migration. `solar client sync --portable` re-resolves paths after `bundle create`, so a transition from `core_source: global` publishes those links from the new bundle.
- feat(solar-client): `solar client bundle remove` returns the workspace to `core_source: global` through the canonical settings writer, republishes the IDE links with the global install's `sync-clients.sh`, and then moves `.solar/bundle` aside. If the links cannot be rebuilt, the bundle stays and the command says to run `solar client sync`.
- fix(solar-client): `solar client bundle remove` leaves portable mode when `.solar/bundle` is missing or invalid. It resolves the workspace with `solar_resolve_paths --skip-snapshot-check`, so the missing-bundle refusal is the only check skipped. `SOLAR_WORKSPACE` stays exported, and a `SOLAR_ROOT` that still points at `.solar/bundle` is not accepted as the global install.

### Upgrade
A workspace already on `core_source: workspace-snapshot`, whose global install is still v0.26.x or v0.27.0, cannot take this fix with `solar client update`. `~/.local/bin/solar` runs that install, whose updater still resolves `SOLAR_ROOT` to `.solar/bundle`, and `solar client bundle remove` is not in that install yet. The global install must have no local changes (`git -C ~/.local/share/solar status --short` empty): git checkout refuses when local changes conflict, and carries them over when they don't; start from a clean tree. Check the fix out in the global install, regenerate the bundle, then update:

    git -C ~/.local/share/solar fetch --tags && git -C ~/.local/share/solar checkout v0.28.0
    solar client bundle create
    solar client update

## [0.27.0] - 2026-09-26

### Fixed
- fix(solar-state): the published status and its test still described the world from before v0.26.0. `SKILL.md` said the audit, continuity and mandate events were on files and that `migrate` / `rollback` were not called from `solar client update` or `sync`. `test_client_update.sh` asserted the published updater never calls `solar_client_state_cutover`. Both were already false: that updater reloads the new `client_lib.sh` and the cutover runs before anything starts. The status and the test now say so. No runtime is migrated for this correction.

### Added
- feat(solar-client, solar-state): one install belongs to one workspace. The runtime's identity is a `workspace_id` stored in `workspace-owner.json` and in `.solar/settings.json`; the path is not the identity. `claim_owner` is the only writer of the owner file. `session`, `operate` and `cutover` read the caller's id from `$SOLAR_WORKSPACE/.solar/settings.json` and refuse a missing or different owner; `describe` reports that as not ready. `init`, `update` and `sync` claim before any other write. A claim that refuses leaves the install, settings and services untouched. The updater that is installing this code cannot claim before it writes; the new cutover claims before it stops anything, and a refused claim does not stop services. `solar client claim-runtime --rebind` moves the recorded path when the id matches. `solar client claim-runtime --repair` is the only repair when the two ids differ: without `--keep` it prints both and writes nothing; `--keep owner` or `--keep settings` keeps the named side. `--keep` without a value, or without `--repair`, exits 2.
- feat(solar-mcp): `workspace()` resolves the workspace with `resolve_solar_paths`. Started outside a workspace, verbs refuse and no runtime is created.
- feat(solar-client): `state-cutover.json` records the install identity and `sqlite`. The same identity does not stop, migrate or restart. A global install's identity is the commit of `SOLAR_ROOT`; a portable install's is `bundle_checksum`. A missing checksum, or a commit of `unknown`, does not skip the cutover. `rollback` deletes the marker.
- change(docs): the OneDrive / multi-machine section is now "Una instalación, un workspace". Portable mode is an install that travels inside the workspace, not a second machine.

## [0.26.1] - 2026-09-26

### Fixed
- fix(solar-state): a resumed migration no longer crashes on a part `ensure_dirs` (or a stale process) recreated empty after it was already moved aside. `_move_old_files` did a directory-level `os.replace` unconditionally, which raises `ENOTEMPTY` the moment the holder already has that part's content from an earlier, completed move — hit for real on 2026-09-26 running `solar client update` against a runtime whose migration had already finished. It now merges file by file into the existing holder when one is found, so a leftover empty folder is dropped and a genuinely new file old code wrote into it still reaches the base.
- fix(solar-state): `migrate` and `rollback`, run from a terminal, printed only a raw JSON blob. They now print one readable summary line first ("Migrated 7 task(s) (…), backup: …", "Already migrated. Nothing new to bring in.") with the JSON kept below it for scripting. `rehearse`'s output is unchanged: a test parses its stdout as JSON.

## [0.26.0] - 2026-09-26

### Added
- feat(solar-state): the runtime state gets an owner. Tasks, the router audit, cross-channel continuity and the events of A3 mandates live in one SQLite file, `state.sqlite`, that only this skill opens. `solar-paths` says where; this says what, and nothing else is imported. A shared flock on `state.lock` covers every read and write; a cutover holds it exclusive. `STATE_FORMAT` is read inside that lock and any value other than `sqlite` is refused, so a cutover that dies halfway leaves the runtime on files. Schema v1 is the published foundation and a test pins its SQL; v2 adds what a rollback needs to write the files back (`source_name`, subtask plans, cancellation requests, and mandate streams that exist even when empty); v3 records that an empty `router/audit.jsonl` existed. No component calls the skill yet, and no runtime has been moved onto it.
- feat(solar-state): the cutover between the file runtime and the base (`migrate`, `rollback`, `rehearse`). `rehearse` imports into a throwaway base and touches nothing. `migrate` and `rollback` refuse unless `SOLAR_STATE_ALLOW_CUTOVER=1`. A resume that already finds `STATE_FORMAT=sqlite` checks the marker, the base and the schema, waits for old writers — including the bare names `create.sh`, `task_cancel.py`, `reconcile_router_audit.sh`, `continuity_cli.py` and `delegation_ctl.py` — and brings in what that old code wrote meanwhile. A task, log, subtask plan, cancellation, the audit, continuity or a mandate stream that is neither still in place nor already under `*.migrated-<stamp>` is refused. Rollback copies `task-logs/` back to `async-tasks/logs/` without moving the source, and an empty audit file comes back empty. `tmp/`, `hooks/` and anything unknown stay where they are.
- feat(solar-state): every reader and writer of tasks, audit, continuity and mandate events moves onto solar-state. `create.sh`, `approve.sh`, `task_cancel.py`, `requeue_from_error.sh`, `start_next.sh`, `activate.sh`, `complete.sh`, `execute_active.py`, `router.py` and `work_status.sh` no longer touch `async-tasks/` or `router/audit.jsonl` directly; they call the `solar_state` API or its CLI, and refuse when `STATE_FORMAT` is not `sqlite`. The MCP verbs `solar_task_approve`, `solar_task_cancel` and `solar_task_requeue` go the same way, with no file-queue branch — one truth, not two. `sun/delegations/*.yaml` is now opened only by `solar-state` (`mandates.py`); `mcp_gate.check_mandate` calls it in process instead of shelling out to the router. `app_index.py` is replaced by views in `state.sqlite` (`runtime_views.py`): the console and `solar-mcp` read from there, and `solar-mcp` no longer imports `solar-app`. Skills (`solar-async-tasks`, `solar-mcp`, `solar-router`) describe the queue as rows, not files, and stop when there is no MCP verb instead of falling back to the shell.
- feat(solar-client): `solar client update` and `solar client sync` now call `solar_state_cutover.py migrate` (`solar_client_state_cutover` in `client_lib.sh`) — the piece the previous two entries said was missing. Stopped services are not restarted if the migration fails; `--check` never migrates; `--no-restart` migrates and leaves services stopped. `solar state rollback` uses the same protocol in reverse.

## [0.25.8] - 2026-09-21
### Fixed
- fix(solar-router): one continuity record, adopted from sun/runtime once


## [0.25.7] - 2026-09-21

### Changed
- change(solar-paths, solar-client): the base everyone imports is its own skill. `solar-client` was two things at once — the library that resolves the workspace, the framework, the runtime directories and the secret store, which ten of the other thirteen skills import, and the CLI that installs, syncs and starts the rest. Base and top in the same package, so every dependency cycle in the framework ran through it (`client → gateway → client`, `client → router → async-tasks → client`). The six resolvers move to `solar-paths`, which depends on nothing: `resolve_solar_paths.sh`, `solar_paths.py`, `solar_runtime.py`, `solar_runtime_paths.sh`, `solar_secrets.sh` and `solar_secrets.py`, plus `host_platform/` — the OS app-data location, which lived in `solar-app` and was imported *back* by the runtime resolver, inverting the layer. `solar-client` keeps the CLI and now imports the base like everybody else. No behaviour changes: the four resolvers never had dependencies of their own, only the folder did. The portable bundle seeds `solar-paths` first, and its tests move to `core/tests/skills/solar-paths/`.

## [0.25.6] - 2026-09-21

### Fixed
- fix(solar-async-tasks): a subtask's result is not introduced twice. The child is asked to write its own `## Result`, and the execution log wraps another one around it, so the parent read `### <key> — completed` followed by a heading that told it nothing. The aggregation drops the repeated heading.

## [0.25.5] - 2026-09-21

### Fixed
- fix(solar-async-tasks): two holes the first real Telegram request with subtasks exposed. `create.sh` wrote `title:` and `scheduled_time:` into the frontmatter unquoted, unlike every field beside them, so text that reaches a title — a Telegram message, or a `<subtasks>` declaration written by a provider — could close the quote and add frontmatter lines of its own, including `notify_when` or an origin. Both are quoted now, `--priority` is validated against its three values instead of being interpolated, and a declared subtask title that spans more than one line is rejected at the parser. The quoting keeps non-ASCII text as it was written: it exists to stop a value from closing its quote, not to flatten the alphabet, and nothing downstream decodes JSON — an accented request was already reaching the queue as `object: "revisi\u00f3n ..."`, which is what the listing and the completion notice would show. Separately, the pre-phase treated a complete manifest as a finished batch: a parent that never got parked (the worker died between the reserved exit code and `await_subtasks.sh`) arrived active with its children still queued and synthesized over results that did not exist. It now waits again unless every child is terminal, while a child whose file is gone is still reported as missing rather than waited for forever.

## [0.25.4] - 2026-09-20

### Fixed
- fix(solar-router, solar-async-tasks): a task that names a framework file can find it. Providers run from `SOLAR_WORKSPACE` so their CLIs discover `CLAUDE.md` and `profile.md`, but the framework is not inside that tree: `core/` exists in the install and in the source repo, never at the workspace root. A prompt naming `core/skills/...` therefore resolved nowhere, and on 2026-09-20 a subtask stopped and asked which path to use instead of reading the file. The router had both paths resolved at import and kept them to itself (`_SOLAR_ROOT`, unused). `prepare_env` now passes `SOLAR_ROOT` and `SOLAR_WORKSPACE` down to every provider, without overwriting an exported value, and both the gateway parent body and a subtask's inherited `## Object` section say that a `core/` path belongs to the framework at `$SOLAR_ROOT`. No file or link is added to the workspace.

## [0.25.3] - 2026-09-20

### Changed
- change(solar-async-tasks, solar-router): a request with subtasks completes even when the provider is sandboxed. The parent body asked the provider to run `create.sh` itself, which codex cannot do — its sandbox has no write access to `SOLAR_TASK_ROOT`, outside the workspace — so on 2026-09-20 the first real gateway request needing children died there. The provider now **declares** its children in a `<subtasks>` block (a JSON list, at most 5, `title` and `body` required and `provider` optional; any other key, a sixth child or malformed JSON rejects the whole block and sends the task to `error/` with the reason named) and the worker creates them. The worker fixes everything else: the object, scope and effect travel down from the parent unchanged, children get no origin metadata so only the parent notifies, and depth is capped at one. `subtask_ids` records which children were the parent's as `key=id` pairs and is never cleared, unlike `blocked_by_task_ids`, which stays the traffic light of the wait. Results no longer depend on a child writing into the queue: before the second execution the worker reads each child's log and writes `## Subtask results` into the parent, with the failed ones present with their status and reason. The discovery by diff (comparing open task ids before and after an execution) is withdrawn along with its false positives — it also counted anything that appeared in `drafts/`, `planned/` or `error/` during the run — and `detach_subtasks` no longer has any effect. A child's identity (`parent_task_id`, `subtask_key`) is written by `create.sh` itself, through two new flags, in the same atomic write as the rest of the file: `create.sh` publishes into `queued/` where the worker can pick the child up at once, so a key written afterwards left a window where a crash produced an orphan that ran unwatched and could not be reconciled on retry. The inherited object also travels in the child's body as an `## Object` section, because frontmatter is stripped before the prompt is built and the child's provider would otherwise never see the scope it must stay inside. The executor still never touches the queue: it exits with a reserved code and the shell moves the parent with `await_subtasks.sh`, as before. An interrupted creation resumes on the next run from a durable declaration kept beside the queue, and the provider is not called until every declared child exists.

## [0.25.2] - 2026-09-20

### Changed
- change(solar-router): the `<delivery>` instruction spends its budget on the reader. The first real delivery (2026-09-20) filled a quarter of the cap with a closing line that described where the detail lived instead of pointing at it, a repeat of its own opening sentence, and a note about a missing local dependency. It now ranks the evidence: a link the reader can open from the channel when one exists, because that is the only kind they can follow from a phone, and otherwise a verifiable reference (a relative path or a stable id) named together with the system it lives in. A local path is not phone-followable and is no longer offered as if it were. It also asks for no restating of the opening line at the end, nothing about the executor's own tooling unless it changed the answer or left work unverified, and bullets when listing things the user has to decide. The cap is stated as a ceiling rather than a target.

## [0.25.1] - 2026-09-20

### Changed
- change(solar-router): the `<delivery>` block is plain prose with no length target. It asked for "one or two short paragraphs", which reads as a budget rather than a shape; the message now takes the room the work needs, up to the 1200-character cap, because being clear matters more than being short. No labels and no template either way.

### Fixed
- fix(solar-async-tasks): `create.sh` fails instead of announcing a task it did not write. The script has no `set -e`, so a failed redirect left it running and it still printed `Task created` with an ID for a file that does not exist; the caller then queued work on that file and found out much later. Observed when a provider sandbox could not write into `SOLAR_TASK_ROOT`: the executor read the success, delegated, and only afterwards discovered the child task was missing. The task is now written to a temporary file beside its destination and moved into place only once the write succeeded whole, so a write that emits some bytes and then fails (a full disk, a killed sandbox) leaves no truncated task for the worker to pick up. Any partial file is removed and the exit code is non-zero. This makes the failure visible; it does not make the write possible — a sandboxed provider still cannot create child tasks.

## [0.25.0] - 2026-09-20

### Added
- feat(solar-async-tasks): the completion notice is the delivery the executor wrote, not a fixed line plus a path. A gateway parent is asked to close its reply with a `<delivery>` block: one or two short paragraphs in the language of the request, written the way a colleague who did the work would, with the evidence in the closing sentence. No labels and no template. The worker copies that block into the task as `## Delivery` (capped at 1200 characters, keeping the last line; a cut sets `delivery_truncated: true`) and the notification sends that section as the whole message, so it can be read on a phone without opening the Mac. `## Result` is never sent: it is the provider's own account, and transporting it is not compressing it. Every execution rewrites the section and recomputes the flags, so a parent that runs twice or is requeued from error never notifies a previous run's delivery. Tasks created with `delivery_expected: true` that finish without the block are marked `delivery_missing: true` and their notice says so instead of announcing the work as resolved; tasks without the flag keep the previous notice. The `notify_long` path is retired: it read the unbounded `## Result` and no task used it.
- feat(solar-async-tasks, solar-router): the declared scope of a request reaches the task that carries it out. The router already extracted and validated `object`, `scope` and `effect` before queueing, then recorded them only in the audit: the executor saw the raw user text alone, so a request naming one artifact could be carried out on another. `create.sh --metadata` now accepts those three keys plus `delivery_expected` as a closed allowlist (unknown keys are still dropped), writes them as frontmatter, and the task body restates them in an `## Object` section with the instruction to act on that object and return a question instead of working on a substitute. `delivery_expected` is written by the same call that puts the `<delivery>` instruction in the body, so removing the instruction removes the flag.

## [0.24.3] - 2026-09-19

### Fixed
- fix(solar-async-tasks): a completed task records `result_path` pointing at its execution log, which is where the result is written (a provider sandbox may not be able to write into the task queue). The completion notification linked the task file instead, which holds no result. An explicit `result_url`/`result_path` set by the task author still wins, and failed tasks record nothing.

## [0.24.2] - 2026-09-19

### Fixed
- fix(solar-async-tasks): task notifications are sent to Telegram as plain text. In Markdown, a stray `_` or `*` in a task title or path made Telegram reject the notification with HTTP 400 (`notify_status: failed`, `telegram_send_failed`). `send_telegram.sh` accepts `TELEGRAM_PARSE_MODE=none` to omit `parse_mode`.
- fix(solar-client): when the installed version changes, `solar client update` restarts the long-running services that are already running (transport gateway, console on :9000), so they stop running the previous code from memory. Nothing that is stopped gets started. Only services whose command line holds this install's path count, so another Solar install on the machine is never touched. After the update the restart logic reloads the newly installed `client_lib.sh`, so it follows the new version's rules. New `--no-restart` and `--restart` options; a failed restart prints the manual command and exits non-zero.
  - **Upgrade note:** updating from 0.24.1 or earlier runs the previous updater, which cannot restart services yet. Run `solar client update --restart` once after this update.

## [0.24.1] - 2026-09-19

### Fixed
- fix(solar-router, solar-gateway): look up async tasks in the same queue `task_lib.sh` writes (`SOLAR_TASK_ROOT`, else the framework runtime `async-tasks`) instead of the removed `sun/runtime/async-tasks`. A long request queued from Telegram/n8n no longer answers "I couldn't queue the task" (with `queued: false`) while the task is actually queued, and the gateway replay path finds the task already created for an `origin_request_id` instead of risking a duplicate.
- fix(solar-async-tasks): `start_next.sh` reads the queue one path per line instead of word-splitting it. With the queue under `~/Library/Application Support`, every path was split at the space, so no queued task ever started ("No tasks ready to start").

## [0.24.0] - 2026-09-19

### Added
- feat(solar-gateway): platform-agnostic message identity. n8n may send `channel` (platform, e.g. `telegram`), `conversation_id` and `message_id`; the gateway composes `session_id = channel:conversation_id` and `request_id = channel:conversation_id:message_id` and never splits a composed id. `channel` is lowercased and must match `^[a-z0-9_-]+$`. `%` and `:` inside `conversation_id` and `message_id` are escaped (`%25`, `%3A`) so different parts never compose the same id; numeric Telegram ids are unchanged. Telegram conversations become the reply chat for origin notify. Partial parts, a malformed `channel` or a conflicting `session_id` are rejected before the replay ledger and never stored. The previous n8n body (`request_id`, `session_id`, optional `chat_id`) is still accepted; without `session_id` it no longer falls back to a shared `n8n:default` session.

### Changed
- Router continuity is keyed by `session_id` instead of `user_id` (`conversation_key`). Existing history stored per `user_id` is not migrated: the next message in each conversation starts without prior turns.
- End-user messages generated by `core/` are now in English, per the language policy: gateway and router replies (including the canonical long-task ACK `On it. I'll let you know here when it's done.` and `(Task: <id>)`), the WebSocket timeout reply, async-task completion and failure notifications, and the read-only App console UI (`lang="en"`, English dates). Tests, docs and examples in `core/` follow the same policy. `client_init.sh` no longer defaults the profile's preferred language to Spanish. Docs and examples in `core/` no longer reference a private client name.

### Fixed
- Async tasks no longer share one router conversation (`user_id = solar-async-tasks`); each task keeps its own `task_<id>` context.
- Direct Telegram webhook requests use a stable `request_id` (`telegram:<chat>:<message_id>`) instead of a random one.

## [0.23.2] - 2026-09-15

### Added
- feat(solar-mcp): user-level Cursor, Claude and Codex registration via `solar mcp print|install|uninstall`, with dry-run, validated workspace, pinned interpreter, atomic/idempotent updates and portable bundle inclusion. Gemini registration is not supported.
- feat(solar-mcp): native client form confirmation manages approval IDs internally when supported; approvals bind the workspace and are reserved before execution to prevent replay. Clients without form elicitation still need trusted out-of-band approval; original-turn authority binding is not implemented.
- fix(solar-mcp): preserve TOML comments, quoted tables and unrelated settings, reject unsafe layouts, detect observed concurrent configuration changes and retain one current backup.

### Fixed
- MCP cancellation closes pending forms and skips cancelled deferred calls; registration resolves its executable once before output or writes.
- MCP snippets include the Solar server key; registration preserves and validates a stable interpreter without requiring TOML support for stdio startup.
- Native confirmation queues interleaved messages and respects request cancellation; config locks live in the Solar runtime instead of client directories.

## [0.23.1] - 2026-09-12

### Fixed
- fix(solar-gateway): treat a named tunnel as healthy when cloudflared `/ready` reports HA connections, so a hairpinned public `/health` curl from the origin host no longer marks the orchestrator PARTIAL or restarts the tunnel.

## [0.23.0] - 2026-09-12

### Added
- feat(solar-async-tasks): route stop requests through canonical task cancellation and report `cancelled` only after the managed process acknowledges termination.

### Changed
- Show the effective `SOLAR_ROOT` and classify it as an installed root or development checkout in text and JSON status output.
- Retain the existing App status, logs and activity shell as a read-only console on port 9000. Read canonical Markdown tasks and router audit records, including injected history, summary use and duration.
- Require recent console and storage access checks for host availability. Report gateway failures and stale records with their causes and dates, separately from task execution failures.

### Removed
- App conversation APIs, SQLite conversation store and reconciliation worker; CLI chat and voice commands; macOS tray, HUD, dictation, TTS and Whisper integration.
- Dashboard mutation and fleet surfaces. `/` and `/dashboard` now lead to the existing console at `/app`.

### Fixed
- fix(codex): invoke current Codex CLIs with `--sandbox workspace-write` instead of the removed `--full-auto` flag.

## [0.22.1] - 2026-09-06

### Fixed
- fix(solar-system): keep feature health-check timeouts isolated from async-task helpers so enabling `async-tasks,host` does not make `solar status` report `run_with_timeout: invalid duration 'bash'`.

## [0.22.0] - 2026-09-06

### Added
- feat(solar-gateway): persist n8n response snapshots by `request_id`; serialize duplicate requests across threads and processes so concurrent retries execute the router once and replay the same response.
- feat(solar-async-tasks): accept flat or nested origin metadata through `create.sh --metadata`; notify the allowlisted origin chat with a brief completion message and result location, or optional ordered message batches.

### Changed
- change(solar-gateway): separate inbound HTTP channels from Telegram webhook registration. Only `SOLAR_GATEWAY_CLAIM_TELEGRAM=true` permits registration; absent/false never claims, and foreign webhooks are preserved. Retire the legacy webhook flags and OWNER fallback.
- change(solar-gateway): require Bearer authentication for n8n and fail closed without a configured secret. Use one synchronous POST with a default 90-second router budget; retire HTTP 202/poll execution and include the claim flag and secret hash in restart drift detection.
- change(solar-router): propagate origin metadata to queued parent tasks, reuse the parent/subtask lifecycle, and support `SOLAR_N8N_AUTO_QUEUE=false` without creating a draft. Children created without metadata do not inherit completion notifications.

### Fixed
- fix(solar-gateway): normalize managed environment blocks into dependency order, rename the gateway header to `[solar-gateway]`, remove its legacy header, and keep the n8n secret inside the gateway block.
- fix(solar-gateway): bound and validate `getWebhookInfo` lookups. Failed, malformed, or unsuccessful responses never authorize registration; manual registration fails, while setup/ensure skips claiming and continues.
- fix(solar-gateway): terminate the n8n router's dedicated process group on timeout without killing the WebSocket bridge.
- fix(solar-router): check the task's queued/active state before returning the canonical asynchronous acknowledgement.
- fix(solar-async-tasks): record delivery failures on the task and preserve confirmed-delivery deduplication; notify configured tasks after execution errors, timeouts, and cleanup failures without sending sensitive error details. Resolve the sender from the installation when the workspace is separate.
- fix(solar-telegram): preserve the caller's destination chat when loading environment configuration.

## [0.21.0] - 2026-07-26

### Added
- feat(solar-client): after `solar client update` (and on `--check`), report macOS LaunchAgent `SOLAR_ROOT` binding via solar-system helpers; warn when the plist is stale or incomplete.
- feat(solar-client): `--reinstall-launchagent` on a real update rewrites the LaunchAgent plist and restarts the transport gateway so bridges inherit the new install root (fail-closed if gateway restart fails).

### Fixed
- fix(solar-client): `--check` stays read-only — combining `--check` with `--reinstall-launchagent` is rejected (exit 2) before any host mutation.

## [0.20.2] - 2026-07-26
### Fixed
- fix(solar-system): detect stale LaunchAgent SOLAR_ROOT


## [0.20.1] - 2026-07-26

## [0.20.0] - 2026-07-26

### Added
- feat(solar): Codex-style update banner on `solar` / `-h` (and `solar status`) when a newer GitHub release exists; cached 24h; `solar update` to upgrade; disable with `SOLAR_NO_UPDATE_CHECK=1`.
- feat(solar-client): `solar client sync exclude list|add|remove` manages `sync_exclude_planets` in workspace settings (skip planet skills/agents/commands on sync; invalid settings fail closed before IDE mutation).

### Changed
- change(solar-client): workspace binding file is `.solar/settings.json` (layout `solar-client-v1.2`); dual-read with legacy `.solar/manifest.json`; atomic write then remove legacy; preserve `sync_exclude_planets` and unknown keys on rewrite.
- change(solar-client): rename writer to `solar_client_write_settings_v12` (deprecated alias `solar_client_write_manifest_v11` retained); mid-fail before replace keeps legacy `manifest.json`.

### Fixed
- fix(solar): bare `solar` / `-h` show help (no Solar App, no chat attempt).
- fix(solar-client): `api_get`/`api_post` catch `URLError` (no raw urllib traceback when Solar App is down).
- fix(solar): top-level `solar update` aliases `solar client update` (no longer treated as chat text).
- fix(solar-client): update-notice cache read is single-line (`latest checked ttl`) so TTL freshness works.
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
- change(plans): Solar App product plan, kept in the workspace (replaces solar-host-plan).

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
