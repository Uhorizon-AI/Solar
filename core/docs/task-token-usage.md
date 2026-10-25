# Token usage for asynchronous questions

Solar records the token counters reported by each provider CLI for asynchronous
questions using `ask_readonly_v1`, including equivalent declared reads. This does
not measure host IDE sessions, ordinary router calls, repository reviews or work
performed outside Solar. Unsupported or unreported counters stay unavailable.

## Capture and storage

The router requests JSON events from Codex and streaming JSON from Claude,
Cursor and Antigravity. Existing permission flags, selected sessions and the final
plain-text answer remain unchanged. A per-invocation observer writes selected
measurement fields through `solar-state`, before reading the next event. It drains
stderr concurrently and enforces the question's wall deadline. The transport keeps
at most about 1 MiB of each unfinished record in its byte buffer; larger records
spill into a private anonymous temporary file, closed on every exit path. Complete
JSON records are decoded at their boundary, so decoding and the returned answer
still require memory proportional to that record/answer. This is not a hard cap on
answer length. Large terminal/answer records retain their text and measurement;
large intermediate records are skipped and mark measurement incomplete. Temporary
raw data is not a retained measurement archive.
An I/O or ownership failure during event persistence stops the invocation;
previously committed observations stay. A deterministic validation rejection (for
example a selection over 64 KiB) marks `observation_rejected` and continues reading
the answer, without pretending the rejected evidence was saved. If only the final measurement-status write fails after a complete
answer, the answer is returned and the unclosed attempt remains incomplete.

Schema 8 adds a public random execution ID to each activation reservation and
separate attempt/observation tables. Reservation adoption preserves that ID; a new
activation receives another. Each invocation gets an attempt ID and router ID.
Only one unfinished attempt may own an activation at a time. A repeated dispatch
is rejected before launching another CLI; finished attempts permit an explicit
later invocation. Once adoption has proved the old owner and its command group
gone, the same adoption transaction closes its unfinished attempts as failed with
`owner_lost` (preserving an earlier capture error). Evidence stays visible; the new
owner can start another attempt on the same public execution ID. The old private
token cannot write, and completed/abandoned attempts cannot be modified.
The reservation's secret token authorizes writes but is never part of the public
measurement projection. Task configuration and approval snapshots are unchanged.

Each observation has a position, capture timestamp, sanitized original measurement
selection and digest. Replaying an identical position is idempotent; replacing it
with different evidence is rejected. Selected fields retain native counter names,
model/session/event identity and CLI version. Native model names allow brackets
and `@`. If a model key cannot be retained or a model breakdown exceeds the selection
limit, `model_usage_keys_dropped` records that loss and forbids single-model
attribution even if only one model key survives. Prompts, answer text, tool arguments
and arbitrary usage strings are excluded. Numerical future usage fields are kept
within bounded selections; this is not a full raw-event archive.

## Meaning of the numbers

- Zero means the CLI actually reported zero. Missing counters are `null`.
- Input, output, cache read/write and reasoning remain separate native categories.
  Cache and reasoning may overlap other categories; there is no grand token total.
- Exactly one terminal event, successful and containing usage, can supply normalized counters.
  Intermediate events and model breakdowns remain evidence and are never added to
  terminal counters. Every terminal counts towards ambiguity, even without usage;
  multiple terminals are never treated as complete or summed.
- An attempt is complete only after successful execution without capture errors.
  Failed, interrupted or ambiguous attempts retain their observations as partial
  evidence. Their normalized counters are null and they do not enter successful
  subtotals. Unfinished attempts survive a process crash and remain visibly
  incomplete. `terminal_missing` means no terminal was received; `unfinished` means
  a terminal was received but the final measurement-status write is missing.
- Coverage is reported per metric against confirmed CLI launches. The public
  `launch_confirmed` flag uses saved launch metadata, not terminal status: an
  abandoned prepared attempt never invents a confirmed launch. Compatible successful
  subtotals are grouped by provider, observed model and CLI version. An unknown
  model keeps that attempt separate. A multi-model aggregate has no single observed
  model; it never inherits an intermediate model or enters that model's subtotal.
  Requested and observed model are distinct.
- Subscription quota is account-wide and is never attributed through differences.
  A CLI-reported monetary estimate may survive as original evidence; it is neither
  a subscription charge nor an invoice. Manual prices and monetary totals are deferred.

Codex uses `turn.completed.usage`; Claude and Cursor use terminal `result.usage`;
Antigravity uses `result.result.usage`. Claude's intermediate usage and modelUsage
are preserved without double counting. A quota failure, even with zero counters,
does not validate a successful measurement for that provider.

## Read surfaces

Solar Console's task detail includes a token-usage panel: scope, metric coverage,
successful subtotals, execution/attempt identity and expandable measurement evidence.
The same read-only projection is available through Solar MCP:
`solar_search(scope="tasks", task_id="…", view="usage")`.
The usage read also returns the task row_version; this versions the task definition,
not measurement freshness. Public attempts use an explicit field selection and do
not expose the local binary path. Session and router identities remain provenance.
An empty panel means no observed attempts in this scope; it never claims zero use.

## Upgrade and verification

Deploy the schema and reader/writer code together through the existing cutover and
backup workflow. Never migrate the live SQLite database manually. Old installations
must not continue writing after migration. Releasing/installing and client sync are
separate from preparing a PR; no production installation is required for these tests.

Validation uses isolated SQLite databases and fake CLI processes with the observed
provider event shapes. It covers final-answer compatibility, missing versus zero,
partial failures, timeout/pipe draining, replay, owner changes, privacy selection,
existing-version cutover and the shared Console/MCP read model. No test invokes a
real model. Prior real CLI probes establish the shapes, not a live integrated claim.
Evidence reads currently load all stored observations; pagination is deferred.
A successful Antigravity run remains unvalidated until quota permits an authorized
smoke test. A live end-to-end check belongs after an explicitly authorized install.

The CLI version probe invokes only `--version`, under the same wall deadline (at
most five seconds), never a prompt or inference command. Failure leaves version
unavailable and does not fail the question. It is checked per invocation to avoid
assigning a cached version to a replaced binary.

## Console presentation

Tasks show known input and output subtotals as `input → output` below the creation timestamp in the task list’s Created · Tokens column and immediately
in the detail. Coverage, individual attempts, cache, reasoning and original
evidence remain under Measurement details. Distinct provider/model/CLI groups
remain separate. Unmeasured list entries are blank; missing metrics within a measured group use a dash, never zero. Task details explain unavailable measurements.

Recent Runs show separate Input and Output columns matched by the audit router ID. They
never repeat the complete task subtotal on every execution. These read-only lists
reuse the canonical solar-state projection and contain no raw observations.

Runs duration is elapsed router time, separate from token consumption. Restricted
routes record monotonic elapsed milliseconds on success and failure. Historical
rows missing that measurement can display a duration labelled as approximate in its tooltip when one
matching start and an end have valid timezone-aware timestamps in chronological
order. This is a read-only derivation; saved audit rows are not rewritten.
Reconciled rows keep no duration, and provider averages use measured durations only.
