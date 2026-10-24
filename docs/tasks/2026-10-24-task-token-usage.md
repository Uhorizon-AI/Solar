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

## Review corrections and validation checkpoint

Code corrections: `1ef14cf19c9817525c4fd7c0f58724479e11df3b`.
Main integration: `864a25b` (preserves the upstream restricted-router channel fix).

- Reject every ambiguous terminal sequence, including terminals without usage.
- Keep multi-model aggregates separate from single-model subtotals, including when
  intermediate observations carry different models without a terminal breakdown.
- Drain oversized JSONL events within bounded memory, retain partial-capture status,
  and return a later valid final response.
- Reject simultaneous attempts on one activation. Distinct later CLI invocations
  remain distinct real consumption, not duplicate copies of the same observation.
- Include CLI version in Console subtotal labels, distinguish finished failures
  from unfinished capture, and return row_version in MCP usage reads.
- Use an explicit public attempt field selection; exclude local binary paths.
- Verify populated MCP/Console equality and read-only behavior; upgrade v7 with an
  existing reservation; retain adoption identity coverage already present.

The `--version` probe is kept per invocation to avoid stale identity after a CLI
upgrade. It performs no inference; failed probes leave version unavailable. This
choice and its failure test address the version-probe review finding.

Validation commands from the repository root (isolated runtime fixtures):

```sh
python -m pytest core/tests/skills/solar-state core/tests/skills/solar-router core/tests/skills/solar-app core/tests/skills/solar-mcp/test_task_views.py -q --tb=short
python -m pytest core/tests/skills/solar-router/test_execution_profiles.py core/tests/skills/solar-router/test_ask_metering.py -q --tb=short
```

On fixed commit `864a25b06758c571e24f3c0582baca9cab7f6bf9`, the first command
passes **1,341 tests**, with **4 skips** and **50 passing subtests** (213.36 s).
The second command passes **106 tests** on the same commit. Four skill packages, JavaScript syntax and diff
whitespace checks pass. GitHub reports no CI checks for this branch; these are
local results. The final documentation-only commit does not change tested code. Tests use fake CLIs and isolated databases, not real models.

Independent review of `6b78bc6`: Codex 88%, Claude 82%, both require changes;
Agent has not returned at this checkpoint. Revalidation of `1ef14cf` is requested
from Codex and Claude; no final approval is claimed. Review results are evidence,
not a substitute for the tests above.

Evidence pagination remains deferred. Antigravity successful real measurement and
live router-to-Console acceptance remain unvalidated. No installation/client sync
was performed; deployment is a separate authorized operation.
