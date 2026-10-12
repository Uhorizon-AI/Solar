# Operational report publication

A planet explicitly publishes `operations/leadership/reports/index.json` with
version 1, a `reports` list and an optional `evidence` list. This is derived
metadata, not a second editable source of business facts.

Each report entry requires string fields `path`, `title`, `owner`,
`generated_at`, `period`, `coverage` and `next_decision`. Paths are relative to
that planet and confined to `operations/`; report paths end in `.html`.
Evidence paths end in `.md` or `.txt` and are served as plain text. Missing,
traversing or escaping paths fail closed for that index; a resolved path outside
`operations/`, including through a symlink, is refused. Excluded planets are
not read. Limits: 30 reports, 500 evidence paths, 128 KiB index, 4 MiB file.

The publishing generator escapes business input and declares real coverage.
The console applies a sandbox CSP with no scripts, forms, images, network
subresources or base rewriting, and opens each report in a new tab with
`rel="noopener noreferrer"`. Because `sandbox` omits `allow-top-navigation` and
`allow-popups`, a served report cannot navigate the console away. Reports should
be self-contained with inline CSS; relative links resolve to explicitly published
reports/evidence. No directory browsing, database downloads, approval controls
or mutation routes.

Generation time does not prove data freshness. Each area owns its coverage,
source dates and next decision. Invalid indexes appear as localized errors.
An absent index means unpublished, not empty business activity. Publishing
does not authorize production, contact changes, external sends or recurrence.
