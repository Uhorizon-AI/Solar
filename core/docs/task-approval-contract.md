# Task approval contract

What a queued task was approved with, and what the worker checks before it claims one.

## What is approved

`task.approve` (and creating a task already queued) records, in the task's frontmatter:

- `approved_digest`: `v2:` + sha256 of the material fields and the definition.
- `approved_definition`: the definition as approved (the snapshot).
- `approved_at`, `approved_row_version`.

Material fields: `solar_state.MATERIAL_KEYS`, including `executor`, `local_command` and
`local_timeout` (a different command is a different task). Not material: run counters,
`recurring_last_run`, claims, notification status.

**Definition** = the body without a first line `# {title}` that equals the stored title, with
leading blank lines and trailing whitespace removed. Renaming rewrites the title and that
heading together, so it does not change the digest.

## What the claim does

`task_claim` and `task_claim_next` compare the current digest with `approved_digest` inside the
claim transaction, after block, schedule and recurrence, before `queued -> active`:

- With a snapshot, the body must be the snapshot followed by nothing, or by sections the runtime
  wrote (`## Delivery`, `## Subtask results`, `## Execution Error`, `## Result`). From the first
  such heading on, everything is generated content, headings of its own included.
- Without a snapshot, `definition_body()` removes those sections, each up to the next `## `.
- No digest (`absent`), a digest without the `v2:` prefix (`legacy`) or a different one
  (`mismatch`): the task stays `queued`, the next candidate is tried and
  `approval_digest_mismatch` is written to `audit` (once per task, reason and row version), to the
  log and to the console. Nothing is converted: approve it again with `task.approve`.
  `python3 core/skills/solar-state/scripts/solar_state.py task list-unapproved` lists them.

## Decisions and limits

- **Title is a label.** Renaming keeps the approval. The title still reaches the provider
  (`Task Title:` in the prompt, and the heading of the body), so a rename can change what the
  provider reads. The rename is itself an approved A2 operation whose approval text shows the new
  title, which is the human check. If a stricter rule is wanted, put `title` back in
  `MATERIAL_KEYS`; renames then return the task to draft.
- **Created queued = approved by the creator.** `task_create(status="queued")` stamps the approval
  (queue scripts, subtasks of an approved parent). `task_import` does not.
- **Runtime sections.** Text placed under a runtime heading after the first result is not
  protected. `task.update` refuses new instructions that reuse those section names while results
  are recorded, and treats them as an instruction change otherwise.
- **Two snapshots, on purpose.** `approved_definition` belongs to the approval: the digest binds it,
  the claim compares it, and a withdrawn approval removes it. `definition_snapshot` only records
  where the results begin; it is not an approval and survives a withdrawal.
- **Where the results begin.** `definition_snapshot` records the definition the body starts with. It is
  kept when an approval is withdrawn, so results (with headings of their own) stay apart from the
  instructions through any number of edits and approvals. `approved_definition`, bound by the
  digest, is what the claim compares.
- **Edits.** A queued task keeps its approval only when the digest is unchanged (a rename) and the approval is valid; a queued task whose approval is absent, legacy or mismatching goes to draft on any edit. Any
  other edit returns it to draft in the same transaction and withdraws `approved_*`
  (`task_approval_withdrawn` in `audit`). Counters and `recurring_last_run` are kept.
