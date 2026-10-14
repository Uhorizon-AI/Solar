# Planet dashboards (declaration + client registration)

A dashboard is a surface a planet owns: a local tool it declares and this machine
registers. Two sources describe it, and Solar never merges them on disk:

- **Declaration** — `planets/<planet>/.solar/dashboards.json`, owned and
  versioned by the planet. It says *what* the surface is and *where it answers*.
  It is the same shape for every planet and carries no machine state.
- **Registration** — the `dashboards` block in `.solar/settings.json`, owned by
  Solar Client on this machine. It says *which* declared surfaces are active
  here and, when the surface needs one, *how* to start it. A start command
  carries local paths, so it cannot live in the versioned declaration.

The console reads both, shows the intersection and stays read only. It never
starts or probes a tool; the start command is copyable text.

## Declaration (planet)

`planets/<planet>/.solar/dashboards.json`, version 1, at most 30 entries:

```json
{
  "version": 1,
  "dashboards": [
    {
      "name": "triage",
      "title": "Triaje comercial",
      "description": "Revisar contactos y registrar decisiones comerciales.",
      "owner": "uh-sales",
      "updated_at": "2026-10-13",
      "url": "http://127.0.0.1:8777/",
      "mode": "interactive"
    },
    {
      "name": "attention",
      "title": "Atención diaria",
      "description": "Resumen del periodo, generado por el planeta.",
      "owner": "uh-ceo",
      "updated_at": "2026-10-13",
      "file": "operations/leadership/reports/daily.html",
      "mode": "read_only"
    }
  ]
}
```

- `name`: **the stable identity**, `[A-Za-z0-9_-]+` (a single URL-safe segment,
  **no dots**), unique in the file. The public id is `<planet>:<name>`. Changing
  the `url` or `file` an entry points at **keeps** the id, so
  `/dashboards/<planet>/<name>` never changes.
- `title`, `description`, `owner`, `updated_at`: non-empty, at most 2000 chars.
- `mode`: `read_only` or `interactive`. `interactive` means the surface may
  change data *inside itself*; the console still only links to it. A `file` view
  is always `read_only` (an `interactive` view is refused).
- **Exactly one** of:
  - `url`: a tool. Exactly `http://localhost:<port>/` or
    `http://127.0.0.1:<port>/`, port 1–65535 with **no leading zero** (a `:080`
    is refused). No HTTPS, no other loopback spelling, no path, query, fragment,
    credentials or other scheme. It is a surface this machine **registers** and
    starts by hand.
  - `file`: a generated view. A path to an HTML page inside the planet's own
    `operations/` (for example `operations/leadership/reports/daily.html`),
    **lowercase `.html`**, no symlink hop, at most 4 MiB. It is read only, needs
    no registration and **must not** change on its own: declare a stable name, not
    a date-stamped one, because the declaration is versioned.

  A view's link in the console is built from the planet and the entry name
  (`/dashboards/<planet>/<name>`), never from the declared path: the route
  re-resolves the file against the declaration, confines it to `operations/`,
  requires a `.html` suffix and serves it under a restrictive CSP. Declaring a
  `file` is how a planet publishes a view now that the report concept is gone.

- **A bad entry never hides a good one.** A single malformed entry is reported in
  `errors` with its own id and the valid entries of the same planet still list.
  Only a structurally broken file (bad JSON, wrong version, more than 30 entries)
  reports the whole planet.

The file lives in the planet's **own** `.solar/` (a repo-owned dot-directory,
like `.claude`), **not** under `operations/` and **not** in the workspace
`.solar/`, which stays Client-managed. Because the path is not under
`operations/`, the declaration carries its own confinement rather than inheriting
one: the resolved path must stay inside the planet, be a regular `.json` file
reached without a symlink hop, and the planet's `.solar` entry itself must not be
a symlink. A planet versioning the file is expected: it is a contract, not
generated output.

**Governance exception.** The workspace rule that says "`.solar/` is read-only,
only Solar Client writes it" is about the **workspace** `.solar/settings.json`.
A planet's `.solar/dashboards.json` is different: it is the planet's own versioned
declaration, and Solar Client writes it **only** through `seed` (never through
`register`, `enable` or `disable`, which touch settings only). Distinguish the two:
workspace configuration is Client-owned and not edited by hand; the planet
declaration is planet-owned, travels with the planet repository, and is created or
replaced by `seed` alone.

> **`.gitignore` warning.** If a planet ignores `.solar/`, that planet cannot
> version its declaration: the file will exist locally but never travel with the
> repository, and `solar client sync dashboards seed` will keep recreating it on
> each machine.

## Seeding the declaration (client)

`seed` is the only subcommand that writes inside a planet. It creates or
validates `planets/<planet>/.solar/dashboards.json`:

```bash
solar client sync dashboards seed <planet>            # create if absent, validate if present
solar client sync dashboards seed <planet> --force    # overwrite an existing file with the template
```

- **Absent** → writes the template (one `example` entry, `read_only`, port 8777)
  and prints how to fill it in and register it. The template is a placeholder:
  its empty `title`/`description`/`owner`/`updated_at` are deliberately not
  valid, so the console reports the declaration as invalid and never lists a
  bogus surface while the operator fills it in. Re-running `seed` before filling
  it therefore exits 2 naming the missing fields, which is expected.
- **Present** → validates it against the same shape the console enforces and
  writes nothing. An invalid file exits 2 and is left untouched.
- **`--force`** with a present file → writes a timestamped backup
  (`dashboards.json.bak`) next to it first, then overwrites with the template. It
  refuses when git tracks the file and reports it modified, unless
  `--allow-dirty` is passed, so a versioned declaration is never lost silently.
- The planet name must be `[A-Za-z0-9_.-]+`, must resolve inside `planets/`, and
  the planet directory must exist. A `.solar` directory or a `dashboards.json`
  that is a symlink is refused (exit 5, nothing written), so the write can never
  escape the planet.

## Registration (client)

```bash
solar client sync dashboards status [--json]     # enabled flag and how many are registered
solar client sync dashboards list [--json]       # id + start command, no planet is read
solar client sync dashboards register <planet>:<name> [--start-command CMD]
solar client sync dashboards unregister <planet>:<name>
solar client sync dashboards enable | disable
```

Settings live in `.solar/settings.json` under `dashboards`:
`{"enabled": true, "registered": [{"id": "<planet>:<name>", "start_command": "..."}]}`.
Absent means enabled with nothing registered. Unknown keys, wrong types, invalid
ids, duplicate ids and commands that are empty or longer than 4000 characters are
rejected (exit 2). `disable` hides every declared surface from the console and
keeps the registration. `unregister` on an absent id is not an error.

**Three registration states** are distinguished, keyed by the stable `id`
(`<planet>:<name>`), so the command is never a second source of truth for the
surface itself:

- **declared, not registered** — the console shows the tool with "Not registered"
  and how to register it; a view is unaffected (views never register).
- **registered, no command** — the console shows "No start command registered".
- **registered with a command** — the console shows the command as escaped,
  copyable text.
- **registered, no declaration** — a stale registration: the console reports it
  as `registered_dashboard_not_declared` rather than hiding it.

Registering is a settings-only action: it never starts a tool, never probes a
port and never reads or edits a planet file. The `start_command` is displayed as
plain text and is never interpreted by the console or by a shell on its behalf.
Starting a registered surface is a separate, explicit action by the operator
(copy the command and run it).

## What the console shows

`GET /api/console/dashboards` returns `dashboards` and `errors`. Each item is a
`tool` (declared with a loopback `url`, carrying `registered` and the registered
`start_command` when there is one) or a `file` (a generated view, always read
only, carrying `freshness`). The UI groups by planet, opens a link in a new tab
with `rel="noopener noreferrer"` and marks the mode; a registered tool prints its
start command as escaped copyable text.

A **view's freshness** is the file's own mtime, read here, never a date the HTML
claims: with a stable name a view is always "the latest", and the mtime says when
the file was written on this machine, not that the underlying data is current.
The view and its owner still state their own coverage.

A tool is only a link when its URL is an exact loopback root; a file is only a
link when its href is `/dashboards/<planet>/<name>`; anything else is listed
without a link. An unreadable or invalid declaration is reported in `errors` and
never hides a valid one, and an unreadable or invalid `dashboards` block degrades
to no tools. The operational-report contract was retired: `/api/console/reports`,
`/reports/…` and the navigation id `reportes` no longer exist, the navigation id
is now `dashboards`, and a generated view is published by declaring it as a
`file` entry — served read only from `/dashboards/<planet>/<name>` under
`default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none';
form-action 'none'; frame-ancestors 'none'; sandbox`.

## Tests

```bash
uv run --project core/tests pytest core/tests/skills/solar-app -q
uv run --project core/tests pytest core/tests/skills/solar-client/test_dashboards.py -q
```
