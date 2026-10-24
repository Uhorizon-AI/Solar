# Task token usage

Status: implemented in draft PR #74; review of the latest corrections remains pending.

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

## Local validation and review checkpoint

- 2026-10-24: 24 focused storage/transport/integration tests pass after the final
  corrections, including injected measurement-write failures and timeout with an
  earlier malformed event. Console tests: 33 pass. Async executor/reservation tests:
  24 pass. MCP task-view tests also pass (15 tests). No model calls in these checks.
- The broad combined run reached 1,605 passing tests and four skips, then was
  interrupted during an unrelated MCP transport wait. It is not a completed suite.
- All four skill packages validate; JavaScript syntax and whitespace checks pass.
- Claude reviewed `37e263e` and `f2ac657`. Confirmed capture/error-handling findings
  were corrected and regression-tested. The last corrections have not received a
  further Claude approval; two review rounds were used. Cursor review is pending.
- Evidence pagination remains deferred. Antigravity successful real measurement and
  live router-to-Console acceptance remain unvalidated. No installation/client sync
  was performed; deployment is a separate authorized operation.
