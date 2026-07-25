# Reference: Signal orchestration (signal → closed work)

Behaviour layer above the authority gate: how to turn an inbound signal into
supervised work without creating supervision load. Authority itself is in
`references/authority-gate.md` and the workspace `AGENTS.md`; this reference adds no
authority.

Cycle: Signal → understand → structure → resolve or propose → approve if required →
execute → verify → close or watch.

## Classify the signal

Map each inbound signal to exactly one primary kind. Misclassification is the usual
root cause of noise.

| Kind | When | Next |
|---|---|---|
| `response` | Question answerable in-turn | A0/A1 answer |
| `decision` | Real options with trade-offs | Recommend + one focused question |
| `task` | Discrete actionable work | Structure + owner + close condition |
| `project` | Multi-task objective | Break into tasks; keep one next action |
| `wait` | Blocked on external party/condition | Record the wait; do not mark failed |
| `reminder` | Time-bound nudge | Continuity or daily-log |
| `delegation` | Recurring routine | Only if a valid A3 mandate exists in `sun/delegations/` |

Before creating a task, event, message or artifact: duplicate check (exists / in
progress / closed / same goal rephrased).

## Prioritize

Weigh impact, urgency, reversibility and dependency. Buckets: **now / next /
waiting / someday / closed**. Do not auto-promote new input to *now*; state the
trade-off against what is already there.

## Answer "where are we"

Read state with `scripts/work_status.sh` and answer in three bullets:

1. **Active** — canonical intention + owner
2. **Waiting on the human** — decisions and approvals only, never machine work
3. **Next from Solar** — the next A0–A3 step, no silent A2 formal

## Verify before closing

Attempted is not done. Check proportionally to the claim: file exists and matches
intent; message reached the right recipient (only after A2 formal + domain gate);
calendar entry visible where expected; automation cadence correct; tests or
inspection for technical work. Then update continuity (`completed_actions`, refresh
or clear `pending`).

## Where state lives

Federated, per `references/continuity.md`: machine work in
`sun/runtime/async-tasks/`, human attention in `sun/daily-log/`, canonical intention
in `sun/runtime/continuity/active.json`, mandates in `sun/delegations/`.

Continuity never duplicates the queue: if the next move is machine work, reference the
task instead of restating it in `pending`.

## Cadence belongs to async-tasks

A periodic briefing is a recurring task (`solar-async-tasks`, `scheduled_time` +
`recurring`), not a skill and not a script on a timer. Only add one when a human
actually reads it — an unread periodic artifact is noise with extra steps.
