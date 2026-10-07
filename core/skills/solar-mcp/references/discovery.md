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

Describe accepts `id`, optional `revision` from Search, optional `reference`
selected from the registered Markdown keys, optional `section` (the exact
heading title), and optional `full`. `section` and `reference` do not accept
a path: `..`, a backslash, or an absolute path is refused, and `section` also
refuses `/`. `section` together with `full=true` is refused.

A selected unit of 4 KiB (4096 bytes) or less returns the complete text, as
does `full=true`. A larger unit returns an outline instead of the body: id,
the skill description, the skill-file revision, every column-0 level-2 and
level-3 heading with its level and UTF-8 byte size, and the registered
reference keys. The outline also copies governance sections in full. A heading
is governance when its title contains, without regard to case, any of
`authority`, `gate`, `governance`, `safety`, `never`, or `approval`. The match
is a substring, so a title such as `Aggregate` counts because it contains
`gate`. Each matching heading is its own original slice: a level-2 slice runs
until the next level-2 heading and includes its level-3 children, and a
matching child is included again on its own. Nothing is summarized or
rewritten. Headings inside fenced code blocks are not sections. When two
headings share a title, `section` returns the first. A missing title raises
an error that lists the titles. `revision` remains the skill-file hash;
`unit_revision` hashes the selected unit, or the returned section when
`section` is set.

Source units above 60,000 bytes or result JSON above 64 KiB refuse. A
governance section is never cut to fit: the response is refused instead.
Do not treat retrieval as execution, authority, dependency verification or
multiuser RBAC.

Discovery reads a live shared Client inventory. It respects `sync: false` and
both settings exclusion lists; hidden IDs cannot be described. Namespaces use
core IDs or `planet:skill`, with deterministic first-match nested duplicates.
Canonical containment is checked for skills and references. Arbitrary paths,
URLs, traversal and symlink escapes are not selectable. The existing gate can
log read verdicts, but discovery does not persist a registry or initialize state.
