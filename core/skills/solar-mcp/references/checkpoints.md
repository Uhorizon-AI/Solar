# Responsibility checkpoints

**Status:** independent deferred draft; deployment requires existing-state
recovery evidence and explicit maintainer acceptance.

Checkpoint Get accepts `agent` and `responsibility`. Identity keys select state
inside the one trusted workspace; they do not authenticate an agent. Put adds
`expected_version` and `checkpoint`: required status (`active`, `waiting`,
`blocked`, `completed`), summary and next_step; optional task_id and up to twenty
artifact_refs. Text fields are bounded, references at most 512 characters each,
serialized data at most 8 KiB. Unknown fields and booleans as versions refuse.

Version 0 creates. Read current state and pass its version for every update.
Put uses native A2 confirmation or an existing exact-call approval, consumed
before execution; stale versions refuse and require a fresh approved call.
Approval never implies task activation. Get/Put go through solar-state.
Checkpoints persist across sessions but neither train a model nor carry consent.
The router loads only explicitly supplied agent/responsibility metadata;
planet agents use `planet:agent`. Task frontmatter forwards these fields through
the async worker. Completion does not automatically write a checkpoint.

There is no physical database per agent. Schema v5 appends the checkpoint table
in the shared SQLite store. The legacy SQLite-to-files rollback refuses while
checkpoints exist because the file format cannot preserve them. Native catalog
rollback is independent and remains available. Preserve the SQLite runtime and
backup when reverting framework versions; do not delete checkpoints to force a
legacy rollback. Keep credentials and canonical domain data out of summaries.
