# Explicit runtime memory

## Inputs, destinations and authority

Resolve a workspace with Client settings, an owning planet and its canonical
`agents/<agent>.md` before calling the CLI. Names are data, not identity proof.
Read operations need authorized context; mutations require a mandate naming
the local object, destination and effect. Never turn a signal into a write.
The entry is `solar agent --workspace <workspace> ...`; the script entry is
`python3 core/skills/solar-agent-creator/scripts/agent_memory.py --workspace <workspace> ...`.
Arguments selecting another planet are an explicit scope choice, not a default.
No MCP mutation tool is added in this release; clients use Solar's CLI.

## Continuity

- `continuity show --planet P --agent A --responsibility R --task-id T` reads
  one task's recorded checkpoint through `solar-state.read_session()`, requiring
  matching workspace/planet/agent/responsibility and canonical contract. It does
  not mark a task complete or verify a previous effect.
- `continuity export` with those same arguments writes only
  `planets/P/agents/continuidad/A.md`, a versioned JSON envelope in Markdown.
  References become planet-relative. A digest detects corruption, not malicious
  authorship; verify the origin before trusting the copy. Unknown checkpoint
  extensions refuse; known execution metadata and task links are omitted.
  Identical exports are unchanged; different content refuses rather than
  silently overwriting another responsibility. Move the planet separately.
- `continuity restore --planet P --agent A` reads the portable copy without
  touching state. It checks format, identity, contract hash, artifact hashes,
  bounded references and decision validity. Missing or changed evidence and
  expired/future decision validity return `ready=false` and issues for the human.
  Relative paths remain scoped to the same named planet in the destination.
- Adding `--apply` explicitly incorporates a validated copy into the existing
  shared continuity document's `portable_agents` map. It preserves original
  workspace/task provenance while naming the destination workspace. Permission
  is not imported. A different existing record refuses; identical imports do
  not create duplicates. No task is created, queued, retried or activated.

The source task remains the live record. The portable map is imported context,
not a new automatically maintained responsibility checkpoint service. Review
an existing dedicated checkpoint implementation separately before adopting it.
When the source evolves, remove/replace an exported copy only under an explicit
mandate after verifying its old hash; v1 never silently selects the newest task.

## Minimal execution facts

No database is created by agent loading, continuity reads or missing-data
fallbacks. Approve an observed need for execution-history queries first. CRM
draft volume alone is not that need. Before initialization, governance must
distinguish the planet's fact memory from Client-owned workspace-root `.solar/`.
If the planet is a Git repository, its `.gitignore` must include `.solar/`.

The observable textual criterion is: multiple verified execution facts from the
agent, a repeated history query across sessions, and evidence that existing
files cannot answer it without duplicating canonical records. The responsible
human records those observations and explicitly approves initialization for the
named planet and destination in a plan or Markdown mandate. Counts of CRM drafts
or the length of a CLI argument never satisfy this criterion.

`--need` must name that existing approval entry, for example
`sun/plans/<plan>.md#execution-memory-approval` or
`sun/delegations/<mandate>.md#execution-memory-approval`. The CLI verifies the
file and heading and records its hash as provenance. That check is not proof of
authorship or automatic authority: the calling workflow must validate the human
approval, its scope and current validity before initialization. The reference is
historical provenance only: the metadata approval path and hash are not a
dependency on the originating workspace. After moving the planet, that path may
no longer resolve and is not revalidated when reading portable facts. Any new
action still requires authority in the destination workspace.

Commands (all require `--planet P --agent A`):

- `facts init --need sun/plans/<plan>.md#execution-memory-approval`: explicitly creates
  `planets/P/.solar/agent-memory.sqlite`, schema 1, private permissions. Refuses
  an existing database. Never run this on real data just to test the feature.
- `facts append --responsibility R --event-id E --result succeeded|failed|corrected
  --source <planet-relative-file> --observed-at <timezone-aware-instant>`: stores
  only a result, evidence reference/hash and date. No message body or CRM copy.
  The event key is scoped to agent/responsibility. Same fact is idempotent;
  conflicting reuse refuses. The source must exist inside the owning planet.
- `facts read --responsibility R`: reads only that agent/responsibility's facts,
  reporting whether each referenced source still matches. No implicit writes.
- `facts backup`: makes and verifies a SQLite backup inside `.solar/backups/`.
- `facts restore --source .solar/backups/<backup>.sqlite
  --expected-current-sha256 <hash>`: requires an exact current-state hash,
  validates the backup, preserves the previous database before atomic replacement.
  Does not erase facts to force rollback. Explicitly authorize this replacement.

All readers/writers coordinate using the planet directory lock; writes also use
SQLite transactions. Unsupported schema versions refuse; no automatic upgrade
is implemented. Future migrations need a separately reviewed version and a
verified backup before changing the existing schema. Reverting framework code
must preserve new memory and backups; removing code is not restoring data.

## Validation boundaries

Use temporary planets/runtimes for writes, concurrent operations, corruption,
conflicts, restore and isolation tests. A real pilot first reads an existing
task and verifies sources without exporting or initializing real memory.
Installing, migrating and activating real memory remain separate effects.
