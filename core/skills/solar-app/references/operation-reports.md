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

## Dashboard catalogs

Publish tools in the versioned `operations/leadership/dashboards.json`, separate
from the generated, potentially ignored report index. Version 1 has a `dashboards`
list (maximum 30). Each entry requires nonempty bounded strings `title`,
`description`, `owner`, `updated_at`, and `start_command`, plus `mode` set to
`read_only` or `interactive` and `url`. The command is displayed as escaped,
copyable text; it is never executed. No availability checks are made.

URLs must match exactly `http://localhost:<port>/` or
`http://127.0.0.1:<port>/`, with an explicit port from 1 to 65535. External hosts,
HTTPS, credentials, other loopback spellings, paths, queries, fragments and other
schemes are refused. Tools open with `target="_blank"` and
`rel="noopener noreferrer"`. Interactive tools may modify their own data;
Console remains read only. Catalog files share report size, confinement and
planet exclusion checks. A bad tool catalog does not hide valid reports.

`GET /api/console/dashboards` combines tools and reports, tagging entries with
`kind`, `mode`, and `planet`. Reports have mode `read_only`. The existing
`/api/console/reports`, `/reports/…`, and navigation id `reportes` remain
compatible. The UI groups entries by planet. Catalogs contain no business records.
