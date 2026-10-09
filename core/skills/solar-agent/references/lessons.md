# Approved learning

## One destination per learning

| Learning | Canonical destination | Limit |
|---|---|---|
| Applies to one agent and has no other home | Lessons section of `planets/<planet>/agents/<agent>.md` | 10 lessons; one sentence and approval date each |
| Needed by several agents of the planet | `planets/<planet>/MEMORY.md` | 20 records and 100 total lines, whichever is reached first; one line per record |
| A reusable capability or procedure | An existing skill where possible, otherwise a new skill | Follow `solar-skill-creator` |

Planet memory is optional, versioned and created only with the first approved
cross-agent learning. It neither reads nor references workspace content. Keep
only stable operational rules, never identity data, secrets, CRM copies,
accounting records, conversations or task logs. Load only relevant learning.

## Template ownership

`core/templates/planet-MEMORY.md` is the authoritative memory template in the
framework. `assets/memory.md` is its packaged copy for portable skill use, not a
second source of truth. When changing the source, refresh the packaged copy and
verify byte equality before packaging. Limits and record rules are defined here;
templates point to this reference rather than restating the limits.

## Propose, approve, persist

1. Derive a stable rule from verified evidence. Check the agent contract,
   applicable skills, planet `AGENTS.md` and optional `MEMORY.md` for an existing
   home or equivalent rule. Improve the canonical source instead of duplicating
   it. Conflicts with governance require resolution before affected work.
2. Choose one destination using the table. At a limit, do not append: propose
   prioritizing, redefining, consolidating or promoting, and let the responsible
   human decide. For overflowing planet memory, propose promoting stable
   governance to planet `AGENTS.md`, or a capability to a skill. Never increase
   authority merely by moving a rule.
3. Keep the pending proposal in the conversation only. Show the exact rule,
   destination path and section, approval date, and any replacement or removal.
   Obtain approval of both text and persistence at that destination. Agreement
   with an idea is not permission to save it. If approval arrives in another
   conversation, recover the exact text and scope or ask; never infer them.
4. For promotion to a skill, use `solar-skill-creator` and extend an existing
   skill first when it fits. Validate the resulting skill and check a concrete
   use case showing that the approved behavior remains available. Only after
   that succeeds, remove the old rule under approval covering that removal.
   If validation fails, keep the old rule and report the unfinished promotion.
   Other promotions likewise preserve the behavior before removing its old
   home. A promotion ends with one canonical rule, not two maintained copies.
5. Persist only the approved change. For agent lessons use
   `- YYYY-MM-DD: <One-sentence approved rule.>` below the Lessons framing.
   For planet memory use the same one-line format and the
   [memory template](../assets/memory.md); resolve its placeholders and never
   create an empty memory file. On replacement, use the new approval date.
   Git history, when available, holds earlier versions; do not embed a log.
6. Re-read the result, verify exact text, approval date, destination, limits
   and absence of duplicate rules. After editing a contract, update routing
   or ownership if affected and run `solar client sync` under applicable
   authority: Cursor receives a copy that otherwise stays stale. Skill changes
   also require publication through sync. If sync is not authorized or fails,
   report that client copies are pending; do not claim they are updated.
7. For contract changes, check exported continuity as described below. Report
   the persisted result separately from pending publication or renewal.

## Renew exported continuity after a contract change

Every approved lesson changes the hash of the whole contract. Existing
`agents/continuidad/<agent>.md` copies can consequently report
`contract hash differs`; `restore --apply` refuses unresolved issues. Do not
edit an envelope hash or bypass integrity checks to make an old copy pass.

1. Inspect the old portable copy with `continuity restore` without `--apply`.
   Re-read the current contract, source task, responsibility, evidence hashes
   and decision validity; decide whether the recorded context is still valid.
2. If renewal is needed, obtain scoped authority to replace the named exported
   file, verifying its old hash first. Preserve a recoverable copy outside the
   active destination before removing the old export. There is no automatic
   replace or cleanup command; do not assume `export` overwrites conflicts.
3. Use `continuity export` with explicit planet, agent, responsibility and task
   ID against the reviewed live checkpoint. Then run read-only `continuity
   restore` to verify the new contract hash, references and validity. If export
   fails, preserve or recover the old copy without representing it as current.
4. Incorporation requires separate authority and `restore --apply`. A different
   already incorporated record refuses; report that conflict for a separately
   reviewed replacement rather than deleting shared state or inventing a CLI
   flag. Renewal never transfers permissions or activates tasks.

See [runtime memory](runtime-memory.md) for the existing commands and boundaries.

## Legacy compatibility

If a planet has `agents/lecciones/<agent>/`, read relevant approved content as
legacy learning; never write new lessons there. Propose migrating each rule to
one destination above, checking duplicates and limits. Obtain approval of the
text, destination and removal before migrating; do not silently delete files.
