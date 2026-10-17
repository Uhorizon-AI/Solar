# Restricted text review

`text_only_review_v1` is a text-evaluation contract for Claude only. It receives
an approved evidence package and returns text and usage. It cannot verify a live
repository. Codex, Cursor Agent, Agy and Ollama are unsupported; no fallback
or provider substitution is permitted.

## Approval and composition

`execution_profiles.build_review_envelope_v1` is pure. It accepts instructions,
a list of rules, evidence entries (`path`, captured UTF-8 `content`, raw-byte
`sha256`), provider and model. It returns `manifest` and `review_input_digest`.
JSON keys and source paths are sorted, text uses LF, and encoding is UTF-8.
The fixed system prompt, exact user prompt, source hashes, profile/composition
versions, provider/model and byte budget are in the manifest. The digest is the
SHA-256 of canonical JSON for the entire manifest, including both prompts.
There is no dynamic channel, task ID, timestamp, history, JIT or continuity in
these prompts. Internal provider defaults are outside Solar's content contract.

Both prompts together may occupy at most 196608 UTF-8 bytes. The manifest records
that bound and the actual size. This conservative input bound is not a token
estimate or a guarantee about the provider's internal context. Oversize input
returns `review_input_too_large`; nothing is trimmed or summarized.

Store the complete canonical manifest JSON in `review_input_manifest`, with its
digest in `review_input_digest`, before approval. A path to a mutable file is
not sufficient. The task's existing material approval digest covers those fields
and `execution_profile`.

## Launch boundary

The worker obtains the profile from the approved definition after proving its
ID/token. The router's internal `execution` object carries `task_id`, `token`
and `profile`; a current reservation and matching approval are mandatory. Both
`route` and `route_stream` take this branch before interactive context loaders.
Only the two verified manifest prompts reach the adapter. Results are never
interpreted as decisions, subtasks or delivery instructions.

`restricted_launch` is the single command/environment constructor for both
adapter paths. It uses a private empty temporary directory (mode 0700), separate
argv entries without a shell, and a fixed JSON result format:

```text
claude -p --no-session-persistence --safe-mode --restricted
  --setting-sources "" --tools "" --strict-mcp-config
  --mcp-config '{"mcpServers":{}}' --settings '{"disableAllHooks":true}'
  --system-prompt <exact-system-prompt> --model <approved-model>
  --output-format json -- <exact-user-prompt>
```

Command overrides (new or legacy), extra flags/arguments/settings and project
configuration for tools, permissions, hooks, MCP or plugins are rejected with
`execution_profile_override_rejected`. The inherited environment is limited to
operational locale/path/home/certificate values and the adapter's API-key/OAuth
credentials. Configuration, prompt, plugin, command-selection and shell-startup
variables are excluded. `--bare` is deliberately absent to preserve OAuth.

Help must advertise the required flags. Effective managed policy must also be
validated: unknown or nonempty policy returns `execution_profile_unsupported`.
The current effective-policy inspection boundary returns **unknown** for real
CLIs. There is no environment or prompt switch to bypass it. Tests substitute a
simulated policy only. Real execution consequently remains unsupported until a
supported effective-policy inspection is implemented and validated.

Claude Code 2.1.285 advertised the flags on 2026-10-17. Its help and the
[CLI reference](https://code.claude.com/docs/en/cli-reference) say managed policy
survives safe/restricted modes. [Managed settings](https://code.claude.com/docs/en/managed-settings)
can have remote and OS sources; inspecting one local file cannot attest them.
No real inference or confinement pilot is claimed by the automated doubles.
The adapter registry records the implemented Claude guard; it does not attest
any host's effective CLI policy or enable the profile in production.

The worker checks raw source hashes and captured text within approved read
scopes before each child. The router checks again immediately before launch,
together with ID/token/snapshot and the final envelope digest. Changed, missing,
out-of-scope or inconsistent inputs return `review_input_mismatch`, release only
the current claim token, and return the task to draft for preparation and approval.
A stale caller cannot release another execution. Logs remain worker-owned.

## Derived children

A parent approves a `subtask_policy` using the existing version-1 schema: maximum
children (initially three, hard limit five), providers, exact templates, inputs,
object/scope/effect and maximum access. Initially only read access and Claude
review envelopes are materialized. Templates are exact, with no arbitrary
provider-generated expansion. The declaration's title/body must match one
unique approved template; its provider must match the approved envelope.

For a batch, the parent's immutable `review_input_manifest` is canonical JSON:

```json
{"version":1,"reviews":[{"key":"review-0","manifest":{},"review_input_digest":"<envelope-sha256>"}]}
```

`manifest` above is the full envelope, not an empty object. Each template's
`inputs` is exactly `["<envelope-sha256>"]`. The parent's `review_input_digest`
covers the entire catalog. Its approved policy and catalog therefore authorize
those exact child inputs before materialization.

`Session.materialize_children(parent_id, declarations, token=...)` validates the
current parent approval, reservation and cancellation state in one transaction.
It commits child rows, their individual snapshots/digests, links, derived
`authorization_record` provenance, the declaration and `subtask_ids` together.
The declaration must cover the complete approved catalog. The template key is idempotent within the parent. A retry never rewrites or
reapproves a child. Out-of-policy declarations create nothing and report
`subtask_authorization_required` once at the parent, without per-child notices.

Every child uses the ordinary claim/admission gate. Parent revocation, changes
or cancellation block further claims. Child edits invalidate authorization.
Legacy children without provenance stay nonexecutable; parent IDs or links are
never backfilled into authority. A provenance record alone is insufficient
without the matching policy, catalog and child definition.

The parent waits for every child to be terminal and includes failed statuses
and errors in its results. A transactional synthesis marker permits one attempt
per approved batch. If that attempt is interrupted, a retry reports
`subtask_synthesis_uncertain` instead of silently invoking synthesis again.
Explicit recovery is required after an uncertain attempt. Only the parent owns
final delivery.

Logical independence does not grant simultaneous execution. Production capacity
remains **1**, with `enabled_reader_profiles` empty. The real managed-policy
inspection, macOS launchd validation, quality pilot and capacity rollout remain
unverified. Other-provider confinement belongs to later extensions.
