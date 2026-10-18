# The resident async-tasks supervisor

One supervisor per workspace/runtime fills the places the applied policy allows and dispatches each
claimed task to its own executor. It replaces the one-shot worker that every tick used to start.
Capacity is still decided only by the reservations of `solar-state` (`core/docs/execution-reservations.md`);
this document is what the supervisor adds around them. The applied capacity is `1` until the later
deliveries, so a supervisor runs tasks one at a time exactly as the worker did.

## Files

All under `<runtime root>/async-tasks/`, resolved through solar-paths. No environment variable moves
them and none names another owner.

| File | Written by | Meaning |
|---|---|---|
| `.locks/supervisor.lock` | the supervisor only | Atomic `flock`, held for its whole life. Its content records pid, start time and workspace id. Never removed. |
| `.locks/supervisor.json` | the supervisor | The identity and handshake: state (`starting`, `ready`, `draining`, `stopped`), workspace id and path, runtime, install root, pid **and start time**, heartbeat (refreshed every second), `reconciled`, capacity, running executions, blocked executions, last waits. |
| `.locks/supervisor-candidate.json` | the launcher | The candidate process just started (pid and start time), so the next tick observes the same one instead of starting another. |
| `.locks/supervisor-launch.lock` | launchers | A short exclusion between two launchers. It proves nothing about ownership. |
| `.locks/supervisor-control.json` | `stop_supervisor.sh` | A drain request bound to the target's pid and start time. Another incarnation ignores it. |
| `.locks/supervisor-exit.json` | the supervisor | Why a candidate left: `state_unavailable`, `reconciliation_failed`, `lock_held_without_identity`, `crashed`, `drained`. |
| `supervisor/children.json`, `supervisor/blocked.json` | the supervisor (mode 0600) | What was dispatched (id, token, pid, process group, start time) and what is blocked, so a later incarnation can reconcile. |
| `supervisor/supervisor.log` | the launcher's redirect | stdout/stderr of the supervisor. |

A resource named `supervisor` would share a lock-file name with a hook lock in the same folder; name
resources otherwise.

## Observing and starting it

`ensure_async_tasks.sh` (every tick) and `check_async_tasks.sh` (observation only) print one JSON object
(last line of stdout): `state`, `reason`, `identity` (kind, pid, start time, workspace, runtime), `age_seconds`,
`heartbeat_age_seconds`. They **observe** the identity: a process counts as the supervisor only when its
pid and start time match what it published. They never take the lock and never write its pid.

| Exit | State | Meaning |
|---|---|---|
| 0 | `ready` | Lock held, identity matches this workspace/runtime/install, heartbeat fresh, reconciliation done. |
| 10 | `starting` | A live, identified process is reconciling (or the previous design's one-shot worker is still finishing). Over 120 s it becomes 20. |
| 20 | `blocked` | Needs attention, nothing is started: `maintenance`, `draining`, `stale_heartbeat` (alive but not beating: never replaced), `identity_mismatch`, `owner_unverifiable`, `starting_timeout`, `startup_unverified` (no live identity after the 5 s budget), `lock_held_without_identity`, `recovery_required` (blocked executions), `legacy_worker_running`, `no_workspace_owner`. |
| 1 | `failed` | The start failed and was checked (`state_unavailable`, `reconciliation_failed`) or nothing is running (`check`). The next tick tries again. |

`ensure` starts a candidate only when nothing alive stands behind the runtime (no supervisor, no candidate,
no legacy worker), through `launch_supervisor.sh`: `Popen(start_new_session=True)`, stdin null, stdout/stderr to
the log, no inherited pipes. Two ticks at once start one candidate; candidates that still race for the lock
leave without dispatching (the winner is the only one that publishes). It waits at most **5 seconds** for the
handshake and never for the executions. Past the budget: 10 only with a live, verifiable identity behind it;
otherwise 20. A held maintenance barrier answers 20 without starting anything.

## What the supervisor does

* **Claim and dispatch.** Each pass asks `solar-state` for the next task (`task_claim_next_detail`): the reservation
  takes global capacity, provider limit, scopes and resources in the claim's own transaction, so the supervisor
  cannot exceed them and adds no other path. A claimed task goes to `execute_active.sh --task <id> --token <token>`
  in its own session and process group, with the pre-start hooks, the recurring stamp and the dependency marker
  that `start_next.sh` applies. The record of the claim is written before the process starts.
* **Fill.** Executions are collected with `poll`; a free place is filled as soon as one ends, on a queue signal
  (`SIGUSR1`; `python3 supervisor_lib.py poke` sends it to the identified supervisor), and at most one second after
  anything else (the poll). It does not wait for the 60 s tick.
* **Manual activations** (`activate.sh`) leave a reservation no executor holds; the supervisor takes it over with
  `task_adopt` (new token) and runs exactly that claim.
* **Collect and release.** Finishing the task marks its attached execution `ending`; its reservation,
  scopes and resources remain taken. After the executor process ends, the supervisor proves every recorded
  process group gone (stopping only verified groups belonging to that execution), then calls
  `Session.reservation_finish` to release the reservation in a transaction. A task still `active` under that execution's token — the executor died
  without finishing — is failed with `executor_exited` (outcome uncertain: **never retried**); one whose executor
  never took its execution is given back unambiguously and failed after three tries.
* **Cancellation** stops only the group of that execution, after a grace period, and the task becomes
  `cancelled` only once its group is gone. A lease that expired while the process is alive stops that group and
  fails the task (`lease_expired`).
* **Failed cleanup.** A group that cannot be proven gone leaves the execution counted and visible as
  `blocked: cleanup_failed` or `cleanup_unverified`. Ending reservations stay in `execution_reservations`;
  additional exclusions live in `execution_cleanup_holds`. Every claim reads both in its own transaction,
  so manual activation, the diagnostic worker and adoption cannot bypass cleanup. Holds survive restart.
  An unreadable imported legacy hold remains exclusive and requires operator recovery; it is never silently dropped.
* **The command's own group.** The router runs the command or provider in a process group of its own, apart from the
  executor's. The pid the executor records for the task (not the one an earlier run left) names it: when the supervisor
  stops an execution (cancellation, lease timeout) or collects it, that group is ended and proved gone **before** the
  task is failed or cancelled and the reservation released. A process table that does not answer is never read as an
  empty group: the reservation stays and the execution is `blocked: group_uncertain`.
* **Hooks.** A pre-start hook has a deadline (`cleanup_timeout` of the task, 60 s by default). One that does not answer is
  ended with its group and counts as blocked (the claim is given back, with a cooldown); while it runs the heartbeat keeps
  beating and finished executions are still collected.
* **Lowering the capacity** never stops a running execution; it limits new claims.

## Restart and recovery

At start, before `ready`, the supervisor reconciles every reservation against the process table:

* the owner is alive and was dispatched by a previous supervisor → **adopted** (watched until it ends, never killed
  for being an orphan, never dispatched again);
* the owner cannot be identified (the process table failed) → `blocked: owner_unverifiable`; nothing is replaced;
* the executor is gone and its process group still has members it cannot prove are its own →
  `blocked: group_uncertain`; nothing is killed;
* the executor is gone and the group is empty → the task is failed (`executor_lost`), not run again; a claim that was
  never dispatched is given back; a foreign owner (another process) waits for its lease like `task_adopt` does.

Blocked entries are re-judged every few seconds and clear on their own when the situation resolves.

## Drain and stop

`stop_supervisor.sh --drain [--timeout N]` (the contract `solar_client_drain_async` relies on) writes a control
request bound to the identified process, then waits: the supervisor stops dispatching, collects its executions and
exits, releasing the lock. Exit codes: `0` gone with nothing pending (or none was running); `1` still draining at
the deadline (it reports the pending executions; nothing is killed); `2` refused, the owner cannot be identified;
`3` gone but blocked executions remain. It never removes the lock and never signals a process by pid. `SIGTERM` to the
supervisor is the same request.

## From the one-shot worker

`run_worker.sh` is no longer an entry point: it needs `--diagnostic` and goes through the same reservations. During the
cut, if the previous design's worker is still running (its machine guard `/tmp/solar-async-tasks-worker.lock`, or
`SOLAR_TASK_WORKER_LOCK`, names a live process whose command line is `run_worker.sh`/`ensure_async_tasks.sh`), ensure
answers 10 `legacy_worker_draining` — 20 `legacy_worker_running` after 120 s — and starts no supervisor. The guard is
only read: new code never writes or removes it. The update drains and waits for that worker before replacing anything
(`core/docs/execution-reservations.md`).

## Console

`/api/console/capacity` projects, without writing: places used and free, the tasks running at once, why each queued task
waits (`dependency`, `resource`, `provider`, `capacity`, `recovery`), the supervisor's published state and its blocked
executions, and the applied configuration revision with the differences a pending proposal would make (nothing is
applied by looking). The pass stamp keeps `starting` and `blocked` as what they are: `starting` is not a fault, `blocked`
asks for attention like `failed`.

## Timings that can be tuned

Observation thresholds only (they cannot name an owner or a lock): `SOLAR_SUPERVISOR_HANDSHAKE_SECONDS` (≤ 5),
`SOLAR_SUPERVISOR_STARTING_LIMIT` (120), `SOLAR_SUPERVISOR_HEARTBEAT_STALE` (30), `SOLAR_SUPERVISOR_LEGACY_LIMIT` (120),
`SOLAR_SUPERVISOR_UNCERTAIN_HOLD` (300); and the supervisor's own `SOLAR_SUPERVISOR_POLL` (≤ 1),
`SOLAR_SUPERVISOR_SWEEP`, `SOLAR_SUPERVISOR_CANCEL_GRACE`, `SOLAR_SUPERVISOR_TERM_GRACE`, `SOLAR_SUPERVISOR_KILL_WAIT`.

## Deferred release and schema upgrade (#39)

Install and verify this fix through the supported update flow before enabling capacity 3/5.
A merged issue alone does not prove that the runtime has migrated; the other rollout prerequisites
remain in [async-rollout.md](async-rollout.md).

Schema v7 stores execution group identities and the ending marker in `execution_lifecycle` and `execution_groups`, and
cleanup exclusions in `execution_cleanup_holds`. The executor's group is captured when it attaches;
the command's group is captured in the same transaction that records its pid. Leaving `active`
commits the task result/status and the ending marker together, retaining the original reservation,
provider place, scopes and resources. A claimed task to which no executor attached may be returned
immediately after a refused hook or failed start.

Only `Session.reservation_finish` releases an ending reservation. It checks the original owner's
pid/start identity and all persisted groups, including supervisor holds. Unknown process-table
answers or live members refuse release; this operation never sends a signal. Supervisor collection
uses it after cleanup. Startup reconciliation releases finished executions without dispatching them
again. `task_adopt <id> --worker <worker>` can also recover an ending execution without a supervisor:
it returns `adopted: false`, `released: true`, `reason: ending_released` only after the same proof.
A queued recurrence remains `execution_ending` until this release, so it cannot race its previous run.
The capacity projection exposes each retained reservation's `phase` (`running` or `ending`).
Active-task adoption also proves old groups gone before replacing its token.

The normal maintenance/drain/cutover upgrade owns migration v6 → v7 and creates a pre-migration
SQLite backup. It imports `async-tasks/supervisor/cleanup-holds.json` in the schema transaction and
archives the source as `cleanup-holds.json.migrated-v7` only after commit. An unreadable source imports
an exclusive hold. A failed migration preserves schema v6 and the source file. Existing applied
policy, approvals, task results and history stay unchanged; this migration enables no concurrency.
Do not downgrade binaries or schema while dependent processes remain. File-format rollback refuses
while any reservation or cleanup exclusion remains, even when the task already has a terminal result.

## Not in this delivery

The restricted profile and derived-child contracts are in `restricted-review-profile.md`. Production reader profiles remain disabled and capacity remains 1. Effective managed-policy inspection for real CLI execution, the macOS launchd harness, quality pilot and 3/5 rollout are not verified by the supervisor simulations.

## Rollout evidence and operations

See [Async capacity rollout and reversal](async-rollout.md) for prerequisites,
exact proposal/application steps and safe drain/rollback. The
[quality pilot](review-quality-pilot.md) is prepared separately and requires
explicit account and bounded-cost authorization before real inference.

## Repository review extension

[Repository readers alongside a builder](repository-readonly-review.md) adds an
independent commit-bound read-only profile. Packet reviews remain supported.
The extension does not change applied capacity or enable any reader profile.
