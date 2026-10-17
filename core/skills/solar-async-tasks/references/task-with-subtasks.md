# Reference: Task with Subtasks

A parent declares an approved batch, waits for its independent children, then
synthesizes their terminal results in the same task. Independence alone does
not permit parallel execution: all claims share capacity, resources and access
admission. Production capacity is 1 and reader profiles are disabled.

## Prepare and approve before execution

Capture evidence in a separately authorized preparation step. Build canonical
review envelopes with `execution_profiles.build_review_envelope_v1`, then include
the complete immutable catalog and its digest in the parent's material fields.
Approve a bounded `subtask_policy`: three initial children, never more than five,
allowed providers, exact instruction templates and input digests, object, scope,
effect and maximum access. A legacy parent without this policy authorizes no
new children.

The catalog shape, template inputs and execution restrictions are specified in
[restricted text review](../../../docs/restricted-review-profile.md). Initially,
materialization supports read-only Claude `text_only_review_v1` envelopes.
Other-provider restricted readers remain unsupported.

## Declare only those approved definitions

Close execution 1 with one JSON block:

```text
<subtasks>
[
  {"title":"Review 0","body":"<exact approved instructions>","provider":"claude"},
  {"title":"Review 1","body":"<exact approved instructions>","provider":"claude"},
  {"title":"Review 2","body":"<exact approved instructions>","provider":"claude"}
]
</subtasks>
```

The title and body must identify one unique approved template. An omitted
provider uses its approved envelope's provider. Arbitrary instructions,
providers, inputs, access or extra fields do not create children. The parser
also enforces title/body length, a hard cap of five, and a single JSON list;
if several blocks appear the last one is parsed.

The worker calls `Session.materialize_children` with the parent's current token.
Solar-state validates and commits the whole batch, each child's own approval,
links and provenance, the saved declaration and `subtask_ids` atomically. Retrying
that declaration cannot duplicate rows or authorize changed children.
`subtask_authorization_required` rejects the batch at the parent; children do
not each notify. Do not write the queue or dispatch providers yourself.

## Wait and synthesize

The wrapper parks the parent with `blocked_by_task_ids`. The supervisor admits
each child through the common gate; the restricted worker verifies its approved
sources before launch. Children return text and consumption, with no new
subtasks, delivery actions or conversation/continuity writes. Changed or missing
evidence returns to preparation rather than granting the reader tools.

Only after all children are terminal does the worker serve `## Subtask results`
to the parent, one section per child with its status and output. Failed children
remain visible as failures. A missing child is reported explicitly. Result text
is bounded at 4000 characters and marked when truncated.

A transactional marker allows one synthesis attempt. An interrupted attempt
requires explicit recovery (`subtask_synthesis_uncertain`), not silent replay.
The parent produces the final artifact and delivery, identifying any failed or
uncovered part. The children never deliver to the origin chat.

`subtask_ids` is the durable batch identity. `blocked_by_task_ids` is only the
wait condition and is removed on unblock; do not use it as an execution-2 signal.
`## Subtask results` is the synthesis input. Depth is one; a restricted child's
`<subtasks>` text is inert. Legacy children without recorded provenance do not
become executable merely because they name a parent.
