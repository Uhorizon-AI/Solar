# Async capacity rollout and reversal

This is an operator runbook, not authority to change a runtime. The production
baseline remains capacity **1** and `enabled_reader_profiles: []`. This delivery
adds evidence tools and procedures; it does not enable a profile or change the
applied policy. The design remains the [reservations](execution-reservations.md),
[supervisor](async-supervisor.md) and [restricted review](restricted-review-profile.md)
contracts. Codex, Cursor and Agy reader confinement is outside this rollout.

## Prerequisites and stop conditions

Before requesting an operational change, collect and review:

- Two consecutive full pytest results and 20 isolated repetitions of timing and
  concurrency regressions, with durable start/end events and maximum-gap checks.
  Linux and macOS results must be identified separately; one host proves only
  its own platform. CI Install E2E does not run pytest.
- A successful opt-in real launchd run on macOS: isolated install/workspace/runtime
  under `/private/tmp`, unique `com.solar.test.async.<uuid>`, 60-second interval,
  RunAtLoad and AbandonProcessGroup, supervisor recovery within 75 seconds,
  reconciliation, single dispatch per execution and verified cleanup.
  The accepted PR 4 environment uses the user's active `gui/<uid>` account,
  **a deviation from the earlier separate-account/VM plan**, with temporary
  isolated paths and a private label. Record macOS version, account/uid, paths,
  launchctl permission outcome, timestamps, process identities and cleanup.
- Successful real [quality pilot](review-quality-pilot.md), with account and
  bounded cost authorized separately. Prepared fixtures are not pilot results.
- Resolution of the deferred-release/cleanup-hold follow-up
  [#39](https://github.com/Uhorizon-AI/Solar/issues/39), explicitly identified in
  `async-supervisor.md` as required before enabling 3/5. This runbook neither
  replaces that work nor treats a successful harness as its resolution.
- Known account/model concurrency and consumption headroom for async **plus**
  interactive work, including provider limits, budget and observation window.
  Async provider limits do not reserve quota for interactive channels. If the
  account's available capacity is unknown, stay at 1.
- The actual installed Claude CLI's required flags and effective managed-policy
  inspection pass. Save version and sanitized `claude doctor` output used by the
  restricted constructor. Its remote-policy check currently recognizes only
  `Managed settings (remote): not fetched ...` and
  `Organization policy: not applicable ...`. A CLI upgrade, wording change,
  unknown/unreadable policy, timeout or nonempty managed policy is a stop
  condition, not a reason to loosen the parser. Revalidate after CLI/account
  policy changes; do not infer confinement from model output.

If any prerequisite is absent, record it as unverified and do not apply 3/5.
During observation stop expansion for duplicate dispatch, lost results, stale
sources, policy failures, account throttling, blocked cleanup, unresolved
recovery or excessive gaps. Agree numeric latency/cost limits and an observation
window before applying; simulations cannot establish account performance.

## Inspect and propose 3

Resolve and confirm the intended install, workspace and runtime with `solar paths`.
Use the existing authorized console's **Executions** capacity card and
`GET /api/console/capacity`; this document does not start a console or prescribe
a test port. Read `configuration.applied`, `configuration.pending`,
`configuration.differences`, `capacity`, `running`, `waiting`, `recovery` and the
supervisor projection. Record the current revision and queue state. Read-only
CLI status is also available:

```sh
python3 "$SOLAR_ROOT/core/skills/solar-state/scripts/solar_state.py" async-policy status
bash "$SOLAR_ROOT/core/skills/solar-async-tasks/scripts/check_async_tasks.sh"
```

Through Solar MCP call `solar_execute` with this exact operation shape (omit
`approval_id`; the native approval path binds the destination and arguments):

```json
{"operation":"async_execution.propose","arguments":{"global_capacity":3,"provider_limits":[{"provider":"claude","limit":3}],"enabled_reader_profiles":["text_only_review_v1"]}}
```

The example assumes the account has known headroom for **three** Claude tasks.
If its supported limit is lower, do not use this proposal for three-way rollout.
`provider_limits` replaces the entire map: include every other agreed provider
limit in this array when present, rather than silently dropping it. Other
unnamed fields, such as `exclusive_wait_seconds`, retain applied values. A
proposal writes `async-tasks/config/async-execution.json`; editing it activates
nothing. Review the whole resulting document and the console's pending diff.

After formal approval for that precise revision/digest and destination, call:

```json
{"operation":"async_execution.apply","arguments":{"revision":RETURNED_INTEGER,"proposal_digest":"RETURNED_64_CHARACTER_DIGEST"}}
```

Replace placeholders with the values returned by **this** proposal, not a prior
run. Confirm `applied: true`, the applied revision, capacity 3, intended provider
limits and reader list. A changed/missing proposal or uncertain response requires
read-only state inspection before retrying; never manufacture an approval.
Only a compatible verified Claude profile can share places; other tasks remain
exclusive even when a provider limit is high. Do not change the verified registry
to make another provider concurrent.

## Observe, then propose 5 separately

Run only approved workload. Preserve event timestamps, parent/child provenance,
unique execution tokens, one synthesis, successful results, source freshness,
maximum gaps, elapsed time and usage/cost. The console must show the expected
revision, used/free capacity, provider waits, ready supervisor and no unexplained
recovery. Queued `dependency`, `resource`, `provider` and `capacity` waits can be
legitimate; `starting` is not `ready`, and `blocked` needs investigation. Lowering
capacity may leave `used` above the new limit until existing work finishes.

After the agreed capacity-3 observation window and a new headroom/quality review,
request separate authority and prepare:

```json
{"operation":"async_execution.propose","arguments":{"global_capacity":5,"provider_limits":[{"provider":"claude","limit":5}],"enabled_reader_profiles":["text_only_review_v1"]}}
```

Again retain other agreed provider entries explicitly. Review the fresh diff,
apply using its returned revision/digest with the same `async_execution.apply`
shape, and repeat observation against the capacity-5 limits. Never reuse the
capacity-3 proposal or assume its approval covers expansion.

## Reverse to 1 and drain safely

Request the bounded rollback authority, propose and apply a fresh revision:

```json
{"operation":"async_execution.propose","arguments":{"global_capacity":1,"enabled_reader_profiles":[]}}
```

This preserves provider limits and changes new admissions immediately after
apply. It never kills executions already running or removes their reservations,
tokens or results. Disable profiles as shown so concurrent reader admission
stays off. Record the applied revision and watch existing work complete.

For a complete dispatch pause (for investigation or binary rollback), use the
identified supervisor's documented drain, after applying the baseline policy:

```sh
bash "$SOLAR_ROOT/core/skills/solar-async-tasks/scripts/stop_supervisor.sh" --drain --timeout 300
```

Exit 0 means drained; 1 means still draining (nothing killed), 2 means ownership
could not be verified, 3 means blocked executions remain. Do not remove locks,
kill by name or force release uncertain reservations. A periodic ensure can
relaunch after a manual drain; for a sustained update pause use `solar client
update`'s maintenance/drain/cutover lifecycle, which holds the barrier across
restarts and resumes. Resolve blocked ownership/cleanup before proceeding.

Keep the current schema while dependent processes exist. Never downgrade the
schema or swap older binaries under active executors. A binary rollback needs
an explicitly compatible target, maintenance barrier, verified drain, backup,
cutover, restart/readiness and release through the supported update flow
(`solar client update --resume` after an interrupted update). An older binary
that cannot read the schema is not an operational capacity rollback. Preserve
evidence and backups; do not claim success until runtime identity, policy and
results have been rechecked.
