# Task spec: Console planet dashboards

**Triage level:** standard
**Date:** 2026-10-13
**Status:** implemented locally; human acceptance pending

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

This change is delivered **on PR #32 itself** (`feat/console-dashboards-catalog`,
on top of `6b276e2`), which it supersedes in place: the removal of `index.json`
and the report routes is a breaking change, so it must not land as a separate
commit beside the report version. There is no second branch to close; #32 is
updated and stays the single PR for this work.

The pending `uhorizon` work (stable-name generator plus the three declared views:
`attention`, `sales`, `marketing`) is **local and versioned separately**; it is
not part of this repository and is not committed here. Framework and planet land
together in the same window, once this change is approved.

## Completion evidence

- `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-client -q`: 132 passed, 40 subtests passed (before this review round; the review regressions below raise the count).
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

### Review round 2 (Codex + Claude)

- `seed --force` no longer follows a planted `dashboards.json.bak` symlink:
  `_write_backup` creates a brand-new backup with `O_CREAT|O_EXCL|O_NOFOLLOW`,
  skipping to `.bak.2`, `.bak.3`, … and never replacing an earlier backup.
  Regressions: symlink not followed, earlier backup preserved.
- `mode: []`/`{}` no longer raises `TypeError` and discards the whole planet: the
  mode is checked with `isinstance(mode, str)` and a single bad entry is isolated
  with a valid one beside it (regression added).
- A malformed registration block no longer hides the views: the registration error
  is kept and declared views are still published (regression added).
- An uppercase `.HTML` suffix is refused in `dashboard_file`, matching `seed`, so
  an entry can no longer list as valid and then 404 (regression added).
- The console reads the registration through `_settings_path`, with the same
  legacy `manifest.json` fallback as the CLI (regression added).
- `write_config` no longer rewrites `scope`/`layout`: it uses `setdefault`, so a
  `register` never silently changes keys owned by `client_lib.sh` (regression
  added).
- `_freshness` receives the already-validated rows, so a planet with N views is
  O(N) instead of O(N²).
- CLI copy updated: `enable`/`disable` no longer mention reports and state that a
  disabled block lists no dashboards at all; `seed` says the example entries are
  invalid until filled.
