# Execution reservations

What `solar-state` guarantees before a task becomes `active`, and how an update keeps new code
away from an old runtime. Delivered in schema v6. Every entry point shares it: `task_claim`,
`task_claim_next`, `activate.sh`, the worker, and the generic move to `active`.

## One place per active task

Taking a place and moving the task to `active` happen in one transaction. A task that does not
fit stays `queued` and the reason is returned (never an error):

| Reason | Meaning |
|---|---|
| `global_capacity` | The applied policy's capacity is used up |
| `provider_capacity` | The provider has its own limit and it is used up |
| `scope_conflict` | A writer overlaps a scope held by another task (parent/child paths overlap; symlinks are resolved at claim time; reader/reader never conflicts). Paths are compared case-insensitively on every platform: on a case-sensitive volume `/Data/x` and `/data/x` are treated as the same scope, which can only serialize more, never less |
| `resource:<name>` | The resource is held; resources are always exclusive |
| `exclusive_needs_idle` / `blocked_by_exclusive` | A task that runs alone (see below), and blocks every other start while it runs |
| `drain_barrier` | An exclusive task has waited `exclusive_wait_seconds`; nothing else starts until it does |
| `subtask_authorization_required` | The child lacks valid derived authorization under its parent's approved policy |
| `maintenance` | An update holds the barrier (below) |
| `cancellation_requested`, `blocked_by_dependency`, `parent_revoked`, `access_policy_invalid`, `absent`/`legacy`/`mismatch` | Revalidated inside the same transaction |

The manual activation keeps ignoring the schedule window and the recurring interval (the worker's
selection rules); it applies everything else. A refused claim never stamps `recurring_last_run`.
A task cannot run twice at once: its row is `active` and its reservation is unique.

An active task that has no reservation (it predates them) counts as exclusive until it is taken
over or finished. Executions whose cleanup the supervisor could not prove (`async-tasks/supervisor/cleanup-holds.json`)
also count, for capacity and resources, until it verifies them (`core/docs/async-supervisor.md`).

## The execution token

A claim returns a random `token` tied to the reservation. `task_complete`, `task_release`,
`task_fail`, `task_await`, `task_record(pid=...)`, the heartbeat and any move out of `active`
need the current token (`--token`, or `SOLAR_TASK_TOKEN` for the CLI); a missing or stale one
raises `StaleToken`. Leaving `active` gives the place back with the status.

The executor (`execute_active.py`) attaches its pid and start time to the reservation and renews
the lease every 30 seconds (`lease_expires_at`, 300 s by default). `task_adopt` replaces the token
only when the previous owner cannot be running: a manual activation no executor attached to yet,
an active task with no reservation, or a lease that ended whose recorded process is gone or is no
longer the process that started. A lease that ended with its process still alive is `owner_alive`
and is left alone; when the process table cannot be asked (denied, timed out, failed) the owner is
`owner_unverifiable` and is also left alone: only a proof that it is gone allows a replacement. A
token cannot fail or finish an execution that already ended (a recurring task back in the queue
included): it raises `StaleToken`. If the heartbeat finds its token replaced, the executor stops
the process group it started before it exits. An old token stops working the moment the new one commits.

The resident supervisor (`core/docs/async-supervisor.md`) is the production executor: it claims through these
same reservations and dispatches each claim by id and token. `start_next.sh` hands the claimed id and token to
the diagnostic worker (`run_worker.sh --diagnostic`) in `$SOLAR_CLAIM_FILE`;
`execute_active.sh --task <id> --token <token>` runs exactly that claim. Without them
(`--once`/`--all`) it adopts what nobody runs. It never takes "the first active task".

## Access declaration and the new material keys

**A declaration alone never makes a task concurrent.** The providers still run with their own
permissions (`bypassPermissions`, `workspace-write`), so `read` does not stop a write. A declared
task is admitted next to others only when its `execution_profile` is listed in the applied
policy's `enabled_reader_profiles`, which starts empty; any other task runs alone, declared or not,
and readers and writers with disjoint scopes alike. Raising the capacity therefore changes nothing
until a profile whose confinement was verified is enabled.

Enabling is necessary but not sufficient: the profile must also have an enforcing
adapter for the task's provider (`VERIFIED_PROFILES` in `solar_state.py`). The registry
contains `text_only_review_v1` for Claude only; Codex, Agent and Agy stay unsupported.
The constructor separately rejects a CLI whose flags or effective managed policy
cannot be validated. No reader profile is enabled in production. See
`restricted-review-profile.md` for the guarded adapter and remaining real-CLI validation.

`access_policy` is JSON: `{"version":1,"mode":"read"|"write","scopes":["/abs/path"],"resources":["name"]}`.
A writer names at least one scope. Paths are absolute and normalized; the digest hashes the
canonical JSON. A task without it is **legacy and exclusive**. An invalid declaration refuses the
approval and the claim: it is never read as a reader.

`MATERIAL_KEYS` gained `access_policy`, `subtask_policy` (bounded policy for children: at most 5,
providers, templates, object/scope/effect, a maximum access), `execution_profile`,
`review_input_digest` and `review_input_manifest`. **The digest version stays `v2:`**: a key is part
of the digest only when the task declares it, so a task that declares none hashes exactly as before
and no standing approval is invalidated. Declaring, changing or removing any of them changes the
digest: `task.update` returns a queued task to draft, and both claims refuse the old approval.
Nothing is converted, and no `v3:` re-approval is needed.

`task_authorizations` records the provenance of a derived (subtask) authorization: parent, parent
digest, manifest digest and key, once per parent and key. A claim of a derived task is refused
(`parent_revoked`) when the parent is cancelled, archived, errored, returned to draft or has a
cancellation request. Children are materialized transactionally through `Session.materialize_children`; their exact approved templates and immutable inputs are revalidated with provenance at claim. See `restricted-review-profile.md`. Subtasks created
before it have no record: `Session.legacy_children()` lists them (read-only, shown by the cutover),
and no record is ever inferred from `parent_task_id`. They remain nonexecutable without provenance.

## The applied policy

`async_policy` has one row (provider names are kept in lowercase, as a task's provider is compared): `revision`, `global_capacity` (1 to 5, initially **1**),
`provider_capacity`, `exclusive_wait_seconds` (60), `enabled_reader_profiles`. Every claim reads it
in its own transaction. Lowering the capacity never stops a running task.

`<runtime>/async-tasks/config/async-execution.json` is only the readable proposal. It is written by
the `async_execution.propose` operation and applied by `async_execution.apply`, both A2 with a
native confirmation; the apply names the revision and the sha256 of the canonical document, and
applies it in one transaction only if the file still holds exactly that and it validates (a higher
revision, known keys, values in range). An invalid or changed file is refused and the applied
revision stays. Nothing else changes capacity: no environment override, nothing in
`.solar/settings.json`. `python3 core/skills/solar-state/scripts/solar_state.py async-policy status`
shows the applied revision and what a pending proposal would change.

## Starvation of exclusive tasks

An eligible exclusive task that cannot start begins a clock. After `exclusive_wait_seconds` it is
the drain target: the first of them in claim order (priority is kept among exclusives). While it is
the target nothing else starts, the running tasks finish and it starts before readers come back.
`audit` records `exclusive_drain_started` once, with what it waited for. Dependencies, schedule or
approval that stop holding reset the clock: they never close the line.

## The maintenance barrier

`<runtime>/maintenance.json` exists from before an update stops anything until the new code, the
new schema and the restarted services are verified. It lives outside the schema, under the control
of `solar-client`, records phase, versions and the services that were running, and is never
released by age. While it exists every claim answers `maintenance`, `ensure_async_tasks.sh`
starts no supervisor (it answers `20 blocked`, reason `maintenance`), a running supervisor dispatches
nothing, and an unreadable file counts as held.

## Update sequence

`solar client update` prepares the target in a staging copy (nothing of the live install changes),
then the target's own `client_update_staged.sh` runs:

1. barrier taken (`maintenance`); ticks paused (LaunchAgent booted out);
2. drain: the resident supervisor is asked to drain through `stop_supervisor.sh --drain --timeout N` (when one
   runs: it stops dispatching, collects its executions and exits; nothing is killed), a one-shot worker of the
   previous design is waited for; 120 s, then the update ends with nothing replaced and the barrier held;
3. the console and gateway stop;
4. `solar_state_cutover.py migrate --apply-hook ...` takes the exclusive lock, revalidates that
   nothing runs, copies the base (`state-backups/pre-update/`), runs the hook that replaces the code,
   migrates and validates (version, integrity, tables, initial policy 1) without releasing the lock;
5. services start, code identity and schema are verified, the ticks resume, the barrier is released.

A failure keeps the services stopped and the barrier held; `solar client update --resume` continues
the same operation from its recorded phase. One process drives it at a time: an operation lock
(`<runtime>/maintenance.lock`, the pid and start time of the driver) is held for the whole sequence,
so a `--resume`, a second update or a sync is refused while the original is alive. A lock whose
process is gone is taken over; one whose owner cannot be verified, now or when the lock was
written, is respected. Only one process takes a stale lock over at a time: it holds an
operating-system file lock on `maintenance.lock.takeover`, which the system releases if the process
dies (the file is never removed, so nobody can take another taker's guard away). `--no-restart` stops after step 4 and holds the
barrier until `--resume`. `--check` writes nothing. The event log (`<runtime>/update-events.jsonl`)
records the order. `solar client sync` uses the same barrier and order without a code replacement.

**First installation from a release older than this one.** The old updater replaces the code
before it stops anything, so it cannot give this order. Prepare the target yourself and run its
entrypoint with explicit paths:

```bash
git clone --branch <tag> https://github.com/Uhorizon-AI/Solar.git /tmp/solar-staging
bash /tmp/solar-staging/core/skills/solar-client/scripts/client_update_staged.sh \
  --install-root <install> --workspace <workspace> --runtime-root <runtime> \
  --stage-root /tmp/solar-staging --mode git --target <tag>
```

## Rollout evidence and operations

See [Async capacity rollout and reversal](async-rollout.md) for prerequisites,
exact proposal/application steps and safe drain/rollback. The
[quality pilot](review-quality-pilot.md) is prepared separately and requires
explicit account and bounded-cost authorization before real inference.
