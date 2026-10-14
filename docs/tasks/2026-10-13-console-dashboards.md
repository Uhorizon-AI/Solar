# Task spec: Console planet dashboards

**Triage level:** standard
**Date:** 2026-10-13
**Status:** implemented locally; PR review, installation and human acceptance pending

## Objective

Provide a read-only entry point for the tools and generated views each planet
declares, after Tasks, and retire the separate operational-report concept.

## Scope

Solar app assets, the dashboard declaration reader, the client registration and
`seed` commands, HTTP routes, tests and documentation. No installation,
recurrence, external destinations, tool startup or mutations. Runtime catalogs
and plan updates remain in their separate workspace repositories.

## Decisions taken

- **Two layers.** Declaration lives in the planet's **own**
  `planets/<planet>/.solar/dashboards.json` (versionable, like a repo `.claude`
  directory); registration lives in this machine's `.solar/settings.json`
  (`dashboards` block). The core never lives inside the declaration.
- **Seed command.** `solar client sync dashboards seed <planet> [--force]` creates
  or validates the declaration; it is the only client subcommand that writes
  inside a planet.
- **Reports are removed, not lost.** The report concept is retired at Louis's
  request: `/api/console/reports`, `/reports/…`, the navigation id `reportes`, the
  `report` kind and the `operations/leadership/reports/index.json` index no longer
  exist. A view a planet used to publish as a report is now a `file` dashboard
  entry: it keeps its own HTML, and the console serves it read only from
  `/dashboards/<planet>/<name>` under the same restrictive CSP.
- **One source per entry.** A declaration entry carries **exactly one** of `url`
  (a loopback tool) or `file` (a view inside the planet's `operations/`, `.html`).

## Acceptance criteria

- Dashboards replaces Reports after Tasks, with internal id `dashboards`.
- The declaration is `planets/<planet>/.solar/dashboards.json`, with its own
  confinement (inside the planet, regular `.json`, no symlink hop, `.solar` never
  a symlink) rather than the reports `operations/` confinement.
- Tools declare access mode (`read_only` or `interactive`) and a copyable startup
  command; registration supplies the machine-specific `start_command`. Views are
  always read only and need no registration.
- Only explicit loopback HTTP root URLs are allowed for tools; a `file` must be an
  HTML page inside the planet's `operations/`. Client planet exclusions apply.
- A view's `href` is built from the planet and the entry name, never from the
  declared path; the route re-resolves the file against the declaration.
- Links open safely in new tabs; Console never probes or starts tools, and never
  serves a file the declaration did not name.
- The shared publication scoping (exclusions, bounded reads, published-planet
  walk) lives in the neutral `operation_publication.py`, free of report or
  dashboard logic.

## Checks to run

Use solar-app validation commands from SKILL.md, its package validator, and JavaScript syntax check.

## References

- CONTRIBUTING.md
- core/skills/solar-client/references/dashboards.md

## Landing order

This change **supersedes** the earlier PR #32 (`feat(console): add planet
dashboards after Tasks`, commit `6b276e2`), which deliberately kept
`/api/console/reports`, `/reports/…` and the id `reportes`. That PR is reworked
into this one rather than merged beside it: the removal of `index.json` and the
report routes is a breaking change, so the two must not land separately. Until
the pending `uhorizon` work (stable-name generator plus the three declared views)
lands, the console shows the planet's empty state and nothing else; framework and
planet land together in the same window.

## Completion evidence

- `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-client/test_dashboards.py -q`: 132 passed, 40 subtests passed.
- `node --check core/skills/solar-app/assets/app.js` and `py_compile` of the app scripts: passed.
- solar-app skill package validation: passed.
- Sweep `rg -n 'operation_reports|console/reports|/reports/|kind: ?"report"|reportes' core/`:
  only deliberate retirement notices in `solar-app/SKILL.md`,
  `solar-client/references/dashboards.md` and the 404 assertion in
  `test_operation_dashboards.py`.
- The full `core/tests` suite has one pre-existing failure unrelated to this
  change (`test_codex_agents.py::test_disabled_by_default_reads_nothing` also
  fails on pristine `main`).
- Installation and human acceptance remain pending. The runtime catalog and the
  personal plan are outside this framework PR.
