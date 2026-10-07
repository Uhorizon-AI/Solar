# Capability discovery

Search accepts `query`, `limit` (an integer of at least 1, default 5), and
optional `preferred_namespace`. A limit above 10 is applied as 10 and the
response includes `limit_capped: true`. A limit below 1 or a non-integer is
refused. Explicit IDs rank first. The namespace is a preference, not an access
scope; transversal capabilities remain reachable. Each description is at most
120 characters. Longer text is cut on a word boundary and ends with `…`; text
that already fits is unchanged. The ellipsis counts toward the 120 characters,
and a single token with no whitespace is cut so the ellipsis still fits.
Results contain ID, namespace, instruction type, that description, match
terms, source hash and unknown dependency availability. Result JSON is bounded
below 8 KiB. `truncated` means the byte cap dropped a further hit.

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
