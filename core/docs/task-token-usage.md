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
stderr concurrently, bounds event size and enforces the question's wall deadline.
A persistence failure during event capture stops the invocation; previously committed
observations stay. If only the final measurement-status write fails after a complete
answer, the answer is returned and the unclosed attempt remains incomplete.

Schema 8 adds a public random execution ID to each activation reservation and
separate attempt/observation tables. Reservation adoption preserves that ID; a new
activation receives another. Each invocation gets an attempt ID and router ID.
The reservation's secret token authorizes writes but is never part of the public
measurement projection. Task configuration and approval snapshots are unchanged.

Each observation has a position, capture timestamp, sanitized original measurement
selection and digest. Replaying an identical position is idempotent; replacing it
with different evidence is rejected. Selected fields retain native counter names,
model/session/event identity and CLI version. Prompts, answer text, tool arguments
and arbitrary usage strings are excluded. Numerical future usage fields are kept
within bounded selections; this is not a full raw-event archive.

## Meaning of the numbers

- Zero means the CLI actually reported zero. Missing counters are `null`.
- Input, output, cache read/write and reasoning remain separate native categories.
  Cache and reasoning may overlap other categories; there is no grand token total.
- Exactly one successful terminal usage event can supply normalized counters.
  Intermediate events and model breakdowns remain evidence and are never added to
  terminal counters. Multiple terminal candidates are ambiguous, not summed.
- An attempt is complete only after successful execution without capture errors.
  Failed, interrupted or ambiguous attempts retain their observations as partial
  evidence. They do not enter successful subtotals. Unfinished attempts survive a
  process crash and remain visibly incomplete.
- Coverage is reported per metric against launched attempts. Compatible successful
  subtotals are grouped by provider, observed model and CLI version. An unknown
  model keeps that attempt separate. Requested and observed model are distinct.
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
