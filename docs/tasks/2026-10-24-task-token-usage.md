# Task token usage

Status: local implementation; review and PR validation pending.

## Outcome

Show the token counters reported by each provider CLI in Solar Console for
asynchronous questions, linked to the existing task, execution and invocation.
Tokens are the primary outcome; subscription quota and monetary pricing are outside
this delivery. See [the contract](../../core/docs/task-token-usage.md).

## Acceptance

- Structured CLI events preserve the existing final plain-text answer and permissions.
- solar-state owns durable, incremental observations outside task approval snapshots.
- Missing counters, reported zero, failed attempts and incomplete coverage differ.
- Console and MCP expose the same projection without summing overlapping categories.
- Existing databases upgrade through cutover with backup; no live manual migration.
- Isolated tests and independent code reviews are recorded against the reviewed commit.

## Evidence and limits

The design uses controlled CLI probes from 2026-10-24 (Codex 0.162.1, Claude 2.1.310,
Cursor 2026.10.22-27dcf5f and Antigravity 1.4.6). Their private source artifacts are
not copied into this repository. Synthetic fixtures reproduce event shapes only.
The first three returned terminal usage; Antigravity returned a quota error and
zero counters, so its successful measurement is not validated. No live installation,
release, host-session measurement or real-provider integration claim is included.

A separate backlog issue was not created because the approval reviewer declined
that additional publication. The authorized implementation and draft PR continue.
