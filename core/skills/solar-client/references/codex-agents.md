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

`solar__<planet>__<agent>.toml`, each component lowercased with `-` as `_`, at most 96
characters. Header marker lines, then exactly `name`, `description`,
`developer_instructions`. CRLF/CR in the body become LF. The instructions are a short
English wrapper (derived copy, resolve paths from the workspace root, read root and
planet governance, stop when sources are missing or conflict, the source prevails over
this copy, no authority is granted) followed by the verbatim body.

## Ownership and conflicts

Only `.codex/agents/` and its manifest `.solar-managed.json` are written. A file is
ours only if the manifest lists it, the generation mark is present, the parsed `name`
matches and the SHA-256 equals the manifest. A `solar__` prefix alone proves nothing.
Conflicts (reported, the agent is left untouched, exit 3, the rest is applied):
unmanaged or edited file, directory or symlink at the path, case-variant file, two
sources with the same public name, a foreign `.toml` with the same `name`, an
`[agents.<name>]` table in the read-only `.codex/config.toml`, or a foreign `.toml`
that already cites the contract path. Unchanged generated files of agents that are no
longer eligible are deleted; edited ones are kept and reported. A source that could not
be read is never retired. A deleted managed file is restored.

Renaming a contract (letter case, `-` vs `_`, or a new stem) keeps the same public
name: the previous identity is adopted by the new source in a single plan only when
Solar confirms the previous source is gone (the `.md`, its `agents/` dir or its planet
no longer exists). A source that is still present but invalid, unreadable or on an
excluded/unknown planet keeps its published role and is reported as a conflict, so a
contract is never replaced while it still exists. If both the old and the new stem
exist at once, it is a conflict (two sources, same public name) and nothing is
overwritten.

Exit codes: 0 ok, 2 usage or invalid settings, 3 conflicts, 4 lock timeout
(`SOLAR_CODEX_AGENTS_LOCK_TIMEOUT`, seconds), 5 refusal before any write (corrupt
manifest, symlinked `.codex` or `.codex/agents`, `planets/` missing while the manifest
has entries, scan error). In `sync`, exit 3 is a warning; other failures are reported,
the remaining clients still sync and the command ends non-zero.

Writes are serialized with `flock` on `.codex/agents`, go through a transitional
manifest (so a crash converges on the next run), and a run with nothing to change writes
nothing.

## Limits

A new Codex session is needed to see new or changed roles, and Codex must trust the
project. Publishing a role grants no authority. ChatGPT Chat/Work are not covered.
Sessions started from a nested repository inside the workspace are not verified.
