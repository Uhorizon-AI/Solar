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

## Codex failed-terminal correction — 2026-10-25

Code commit: `ca9d550`. `turn.failed` is now retained as a Codex terminal with
`successful=False`, whether or not it carries usage. A completed/failed terminal
sequence is ambiguous; all normalized counters are null and no subtotal is added.
The ambiguity reason takes precedence over the generic failed status.

Four subprocess regressions cover a failed terminal alone and after completion,
with and without counters, through transport, selection and projection. On this
code, **86 tests pass** (10.14 s): router `test_ask_metering.py`, state
`test_token_usage.py`, MCP `test_task_views.py`, Console `test_console_ui.py` and
`test_task_detail.py`. Router/state skill packages and diff whitespace checks pass.
No real provider was invoked by these tests. Earlier broad results above apply
to `864a25b`, not to this later code commit.

Completed review results: Claude approved `1ef14cf` at 94%; Codex required this
additional correction at 89%. Agent's 86% review concerns the older `6b78bc6`;
its findings were already addressed in `1ef14cf`. None is a final approval of
`ca9d550`. The PR remains draft pending revalidation.

## Final-review corrections — 2026-10-25

Code commits: `5578ff4`, `0aecfa3`, `409af6e`.

- Retain model IDs with brackets/`@`; mark dropped/truncated model keys so a
  surviving key can never receive an incomplete multi-model aggregate.
- Preserve large answer/terminal records using anonymous private temporary files;
  close them on normal, malformed and error paths. Transport buffering is bounded;
  JSON decoding and the final answer still consume memory proportional to size.
- Close abandoned attempts only after the existing adoption checks prove the old
  owner/groups gone; keep evidence and execution identity while allowing a new
  attempt. Count confirmed launch metadata, not failed status, in coverage. A
  prepared attempt abandoned before launch cannot inflate the denominator.
- Continue after deterministic observation rejection, including a real >64 KiB
  selection; stop on persistence I/O or ownership failures.
- Keep normalized counters null for partial attempts; retain native counters as
  evidence. Show translated missing-terminal, unfinished and capture-error reasons
  alongside the generic incomplete-capture notice in Console.

Validation (isolated runtime and fake CLIs, no real inference):

| Commit | Scope | Result |
|---|---|---|
| `5578ff4` | Full solar-state, solar-router, solar-app; MCP task views; approved/reservation worker integration | 1,387 passed, 4 skipped, 50 passing subtests (230.57 s) |
| `0aecfa3` | Full solar-state; router metering; MCP task views; Console UI/task detail | 628 passed, 1 skipped (28.33 s) |
| `409af6e` | Router metering, state token usage, MCP task views, Console UI/task detail | 105 passed (10.38 s) |

All four skill packages, JavaScript syntax and whitespace checks pass. The final
documentation-only commit does not change tested code. Broad results are not
silently attributed to later code revisions.

Latest independent reviews of `5578ff4`: Codex 89% (prepared-adoption coverage
issue, corrected and regression-tested in `0aecfa3`); Claude 95% (the same coverage
issue and hidden UI reasons, corrected in `0aecfa3` and `409af6e`); Cursor review
is still pending at this checkpoint. No independent approval of the last two code
commits is claimed. The default two review rounds were used; PR remains draft.

Revalidation tasks: Codex `ba520857-0874-4c3c-971d-39c934100301`, Claude
`5f020115-884d-45d7-bc2f-ed4ead3d1eec`, Cursor
`28fd5746-7efa-47eb-83d3-c685ca31e79c`. No live installation or migration occurred.
