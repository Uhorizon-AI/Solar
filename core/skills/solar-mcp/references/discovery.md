# Capability discovery

Search accepts `query`, `limit` (1–10, default 5), and optional
`preferred_namespace`. Explicit IDs rank first. The namespace is a preference,
not an access scope; transversal capabilities remain reachable. Results contain
ID, namespace, instruction type, bounded description, match terms, source hash
and unknown dependency availability. Result JSON is bounded below 8 KiB.

Describe accepts `id`, optional `revision` from Search, and optional `reference`
selected from the registered Markdown keys returned by Describe. It returns
complete instructions, hashes, bounded reference keys and governance guidance.
Source units above 60,000 bytes or result JSON above 64 KiB refuse. Do not treat
retrieval as execution, authority, dependency verification or multiuser RBAC.

Discovery reads a live shared Client inventory. It respects `sync: false` and
both settings exclusion lists; hidden IDs cannot be described. Namespaces use
core IDs or `planet:skill`, with deterministic first-match nested duplicates.
Canonical containment is checked for skills and references. Arbitrary paths,
URLs, traversal and symlink escapes are not selectable. The existing gate can
log read verdicts, but discovery does not persist a registry or initialize state.
