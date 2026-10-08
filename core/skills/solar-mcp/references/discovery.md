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
does `full=true`. A larger unit returns an outline instead of the body, unless
that outline's response JSON is at least 85% of the complete-body response
JSON. Both sizes are the UTF-8 length of the JSON object with `indent=2` and
`sort_keys=True`, the same encoding as the 64 KiB limit. At or above 85%,
Describe returns the complete body, as it does for a small unit. The outline
contains the id, the skill description, the skill-file revision, every column-0 level-2 and
level-3 heading with its level and UTF-8 byte size, the registered reference
keys, and the preamble. The preamble is the original text after the frontmatter
and before the first level-2 heading, including a level-1 heading when one is
there. It is copied whole. A unit with no frontmatter takes the preamble from
the start of the file. A unit with no level-2 heading uses the whole body as
the preamble.

The outline response includes `usage`, a fixed hint: read only the sections
you need with `section=<title>`, and use `full=true` only if the outline is
not enough. This hint is 103 characters. Complete-body responses and
single-section responses omit `usage`. The field is part of the outline JSON,
so it counts in the 85% comparison.

The outline also copies governance sections in full. A heading is governance
when its title contains any of these substrings, without regard to case:
`authority`, `gate`, `governance`, `safety`, `never`, `approval`, `autoridad`,
`gobernanza`, `seguridad`, `nunca`, `aprobaci`, `obligatori`, `prohib`,
`regla`, `límite`, `limite`, `dependencia`, `antes de`. Accents are not folded,
so `límite` and `limite` are both listed. A title such as `Aggregate` counts
because it contains `gate`, and `Reglas duras` counts because it contains
`regla`. Each matching heading is its own original slice: a level-2 slice runs
until the next level-2 heading and includes its level-3 children, and a
matching child is included again on its own. Nothing is summarized or
rewritten. Headings inside fenced code blocks are not sections. A fence
is indented by at most three spaces and closes only on the same character
repeated at least as many times as the opening line, with nothing else on
that line. Four spaces, a tab, a shorter run, the other character, or
backticks inside a paragraph do not open or close it. When two
headings share a title, `section` returns the first. A missing title raises
an error that lists the titles. `revision` remains the skill-file hash;
`unit_revision` hashes the selected unit, or the returned section when
`section` is set.

Source units above 60,000 bytes or result JSON above 64 KiB refuse. A
governance section and the preamble are never cut to fit: the response is
refused instead.
Do not treat retrieval as execution, authority, dependency verification or
multiuser RBAC.

Discovery reads a live shared Client inventory. It respects `sync: false` and
both settings exclusion lists; hidden IDs cannot be described. Namespaces use
core IDs or `planet:skill`, with deterministic first-match nested duplicates.
Canonical containment is checked for skills and references. Arbitrary paths,
URLs, traversal and symlink escapes are not selectable. The existing gate can
log read verdicts, but discovery does not persist a registry or initialize state.
