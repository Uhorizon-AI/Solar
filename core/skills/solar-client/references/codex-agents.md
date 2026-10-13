# Codex native agents (opt-in)

`scripts/codex_agents.py` publishes planet agent contracts as Codex roles. It is
called by `sync-clients.sh` (Codex client) and by `solar client sync codex-agents ...`.
Python 3.11 or newer is required to publish (the generated TOML is round-tripped
through `tomllib`); without it enable, `preview --contents` and publish refuse.

## Commands

```bash
solar client sync codex-agents status [--json]           # enabled flag and exclusions; reads no planet
solar client sync codex-agents preview [--json]          # scope only: planet names and classification
solar client sync codex-agents preview --contents [--json]  # full plan, dry run, never writes
solar client sync codex-agents enable | disable
solar client sync exclude list|add|remove --client codex [<planet>|<planet>:<agent>]
solar client sync --codex-only                           # publishes (also part of a full sync)
```

Settings live in `.solar/settings.json` under `codex_agents`:
`{"enabled": false, "exclude_planets": [], "exclude_agents": []}`. Absent means
disabled. Unknown subkeys, wrong types and ids outside `[A-Za-z0-9_.-]+` are
rejected (exit 2). Disabling stops publication but leaves published files.

## Naming scheme

The published role is `<planet>:<agent>`, with the contract `name` (which must equal the
file stem) kept as is: hyphens stay hyphens, letter case is preserved. Examples:
`uhorizon:uh-backend-dev`, `louis:lou-ai`. This is the same string Client already uses
as the canonical identity in the exclusions (`exclude add --client codex
uhorizon:uh-sales`); both come from one function (`canonical_identity`).

The file is named like the role, `<planet>:<agent>.toml`, and the TOML `name` field is
the same string. Verified for this scheme: Codex CLI and the Desktop engine discover and
invoke roles whose file name and `name` field are both `<planet>:<agent>` on macOS. It is
not verified that the file name may differ from the `name` field, so Solar never makes
them differ.

Valid components: only `[A-Za-z0-9._-]`, starting with a letter or digit (no leading
`-`, `.` or `_`), no `:` and no `/`, at most 64 characters each (so a name is at most 129
characters). A leading `_` is rejected because `_*.md` files are templates that the scan
always skips, so such a contract could never be published. Anything else is omitted with
a reason (`omitted: <source>: agent name contains ':' ...`) and is never substituted or
normalized; rename the file or the planet.

Collisions are conflicts: two sources whose names differ only in letter case (`Lead` and
`lead`), a foreign `.toml` with the same name or file (including case variants) and an
`[agents.<name>]` table in `.codex/config.toml`. `uh-sales` and `uh_sales` are different
roles and both publish. On a case-insensitive volume (default macOS) `Lead.md` and
`lead.md` are the same file, so only one source can exist there.

Renaming a contract only by letter case (`Lead` to `lead`) is a retire plus an add. The
guard against case-variant files defers the new role by one run: the first sync retires
the old file (an unchanged generated file) and reports a conflict (exit 3) for the new
one, and the next sync publishes it.

Exclusions are deliberately wider than the names: `exclude add <planet>:<agent>` matches
case-insensitively and treats `-` and `_` as equal, so excluding `uhorizon:uh-sales` also
excludes `uhorizon:uh_sales`. Excluding more than strictly needed is the privacy-safe
direction.

Known limits: `:` is not allowed in Windows file names, so a workspace with these files
cannot be checked out onto Windows. The publisher itself already needs POSIX (`fcntl`
locking), so it never runs on Windows; there is no extra Windows check. The scheme
targets macOS and Linux.

## Before enabling when a personal or private planet exists

Run in this order, with `<personal-planet>` replaced by that planet:

```bash
solar client sync exclude add --client codex <personal-planet>
solar client sync exclude list --client codex
solar client sync codex-agents preview            # scope only: confirm the planet shows as excluded
solar client sync codex-agents preview --contents
solar client sync codex-agents enable
solar client sync --codex-only
```

`exclude add <planet>` without `--client` is a different, wider decision: it also hides
the planet from the agents, commands and skills of every other client. The Codex-specific
exclusion keeps the other clients as they are. Global exclusions always apply to Codex
agents too (excluded = global plus Codex lists).

Be aware that existing skill publication already scans planet skill folders for all
clients. The Codex agent exclusion only governs this new agent publisher.

## What is read

An excluded planet is never listed, stat-ed or opened (only the names under `planets/`
are listed). For the others only `planets/<p>/agents/*.md` at the top level is read;
nested agents (under `skills/`, `continuidad/`, `lecciones/`, ...) are never looked at.
Skipped: `README.md`, names starting with `.` or `_`, symlinks and non-regular files,
files over 256 KiB, invalid UTF-8 or NUL. Symlinked planets are skipped unless they
point at another non-excluded planet directly under `planets/`.

A contract is published only if frontmatter has `name` (equal to the file stem) and
`description` (at most 1024 characters) and the body is not empty; other reasons are
reported as `omitted: <source>: <reason>`. A contract that exists but does not
validate (broken frontmatter, empty body, serialization failure, unsafe/non-regular
file) is `kept: contract is invalid`: its already-published `.toml` is **not** retired,
so editing a contract never deletes the role. It is retired only when the `.md`
disappears or the agent/planet becomes excluded. An agent whose text references an
excluded planet (`planets/<P>`, `../<P>/`, `<P>:<name>`) is omitted without opening
that planet. An identity in `exclude_agents` (`planet:agent`, case-insensitive, `-`
equals `_`) is omitted before its file is opened.

## Excluding a planet after it was published

Disabling (`codex-agents disable`) stops publication but does not remove files already
written; `publish` returns before scanning, so a later `exclude add --client codex`
alone will not retract them. To retract a planet you already published, re-enable,
sync (the publisher retires its unchanged files now that the planet is excluded), then
disable again:

```bash
solar client sync codex-agents enable
solar client sync --codex-only        # retires the now-excluded planet's files
solar client sync codex-agents disable
```

If a `.toml` you edited by hand stays behind, delete it yourself; Solar never removes a
file it does not own.

## Generated files

`<planet>:<agent>.toml` (see Naming scheme). Header marker lines, then exactly `name`,
`description`, `developer_instructions`. CRLF/CR in the body become LF. The instructions
are a short English wrapper (naming the role, derived copy, resolve paths from the
workspace root, read root and planet governance, stop when sources are missing or
conflict, the source prevails over this copy, no authority is granted) followed by the
verbatim body.

`preview --contents --json` lists `items` that all have the same keys: `action`, `file`,
`source`, `identity` and `reason` (`null` unless the action needs one, such as
`migrated to <name>` on the retirement of an old `solar__` file).

## Ownership and conflicts

Only `.codex/agents/` and its manifest `.solar-managed.json` are written. A file is
ours only if the manifest lists it, the generation mark is present, the parsed `name`
matches and the SHA-256 equals the manifest. A name or prefix alone (including `solar__`)
proves nothing.
Conflicts (reported, the agent is left untouched, exit 3, the rest is applied):
unmanaged or edited file, directory or symlink at the path, case-variant file, two
sources with the same public name, a foreign `.toml` with the same `name`, an
`[agents.<name>]` table in the read-only `.codex/config.toml`, or a foreign `.toml`
that already cites the contract path. Unchanged generated files of agents that are no
longer eligible are deleted; edited ones are kept and reported. A source that could not
be read is never retired. A deleted managed file is restored.

Renaming a contract (a new stem or planet) changes the public name: the new role is
published and the old one is retired when its source is gone (a source that still exists
but is invalid, or is unreadable, or sits on an excluded planet keeps its role, and an
excluded planet is never read).

Exit codes: 0 ok, 2 usage or invalid settings, 3 conflicts, 4 lock timeout
(`SOLAR_CODEX_AGENTS_LOCK_TIMEOUT`, seconds), 5 refusal before any write (corrupt
manifest, symlinked `.codex` or `.codex/agents`, `planets/` missing while the manifest
has entries, scan error). In `sync`, exit 3 is a warning; other failures are reported,
the remaining clients still sync and the command ends non-zero.

## Migrating from `solar__<planet>__<agent>`

Earlier versions (manifest format 1) published `solar__<planet>__<agent>.toml` with
`name = "solar__<planet>__<agent>"` (components lowercased, `-` as `_`). The manifest is
now format 2; format 1 is still read. The first run of `solar client sync --codex-only`
(or a full sync) with publication enabled migrates, per agent, in the same run, under the
same lock:

1. The new role is written (atomically, through a transitional manifest that lists the old
   entry as `retiring`).
2. The old file is deleted **only** when the manifest lists it, the generation mark is
   present, its parsed `name` matches the entry and its SHA-256 equals the manifest, i.e.
   it is unchanged generated output.
3. The final manifest (format 2) lists only the new roles.

Anything else is a conflict that is reported and left alone, and the new role of that
agent is not published until the old file is gone (so there is never a duplicate role):
an old file you edited, one that lost its mark or whose `name` changed, one that is not a
file. A `solar__*.toml` that no manifest lists is never ours (the prefix proves nothing)
and is not touched; if it quotes the contract path it blocks the new role as an unmanaged
file does. If the old file was already deleted by hand, only its manifest entry is dropped.

To resolve a conflict, delete the old file (or restore the generated text) and sync again.
A crash in the middle converges on the next run: both files may exist for a moment, never
neither, and the second run changes nothing. An older Solar Client refuses a format 2
manifest (exit 5) rather than misreading it, so update every checkout that shares the
workspace.

Writes are serialized with `flock` on `.codex/agents`, go through a transitional
manifest (so a crash converges on the next run), and a run with nothing to change writes
nothing.

## Limits

A new Codex session is needed to see new or changed roles, and Codex must trust the
project. Publishing a role grants no authority. ChatGPT Chat/Work are not covered.
Sessions started from a nested repository inside the workspace are not verified.
A file name different from the `name` field is not verified with Codex, so Solar never
generates one. `:` in file names is not portable to Windows. Codex invoking roles published with this
scheme by a Solar sync, using a real model, is verified by hand on macOS after installing;
the offline tests here do not run Codex.
