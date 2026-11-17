# State homes

Solar keeps two kinds of things apart, and the split is physical, not a
convention people are asked to respect.

| Home | What | Where | Git |
|---|---|---|---|
| Workspace context | Preferences, plans, memory, daily log, A3 mandates | `sun/` | Versioned |
| Framework runtime | Queue, router, gateway, host, continuity, security map, A3 enforcement evidence, index | `SOLAR_RUNTIME_ROOT`, else `<app data>/Solar/runtime/` | Never |
| Planet state | Machine state produced by a planet skill | `<app data>/Solar/planets/<bucket>/<skill>/` | Never |

`<app data>` is `~/Library/Application Support` on macOS, `%APPDATA%` on
Windows, and `$XDG_DATA_HOME` (else `~/.local/share`) elsewhere. It is
overridable with `SOLAR_APP_DATA`, which is what tests use.

## The two homes of a planet

Every planet has *what it knows* and *what it keeps and generates*.

- **What it knows** lives in its repository: governance, procedure, non-secret
  configuration, and artifacts the user opens. It is versionable.
- **What it keeps and generates** to work lives outside the workspace: local
  credentials, identities, caches, compiled binaries, and other files the user
  never opens. It is never versioned.

A planet does not invent a path inside its own repository, and does not mix its
state into the framework runtime. It asks for its home by workspace, planet and
skill identity.

## No silent fallback

There is no fallback to `sun/runtime/`. Code that needs a different location
must be told explicitly through an override (`SOLAR_RUNTIME_ROOT`,
`SOLAR_TASK_ROOT`, `SOLAR_ROUTER_RUNTIME_DIR`, `SOLAR_HOST_RUNTIME_DIR`,
`SOLAR_SYSTEM_RUNTIME_DIR`, `SOLAR_GATEWAY_RUNTIME_DIR`,
`SOLAR_DELEGATIONS_RUNTIME`). A missing home is an error, not a reason to write
inside the workspace.

## Identity is the physical path

Identity is never computed on the string received. `expanduser` and `realpath`
are applied first, and only the resolved physical path enters hashes,
comparisons and keys. Opening the same workspace or planet through a symlink and
through its real path must produce **one** identity, not two.

`host_registry.stable_hash()` keeps `cksum` so paths that were already canonical
keep the ports they had, but it now digests the resolved path. The
`workspaces.json` loader builds a canonical view in memory: entries that resolve
to the same directory collapse into one, the oldest entry wins and keeps its
label, and `active_path` resolves to that same identity. The file itself is not
rewritten.

## Planet buckets

`<app data>/Solar/planets/index.json` is the stable registry of physical
assignments. Its key is the SHA-256 of the real path of
`<workspace>/planets/<planet>`; its value records the canonical path, the
logical name and the physical bucket.

The first planet to claim a name keeps the readable name. A physically different
planet with the same name gets `<name>-<12 hash chars>`. Two paths that resolve
to the same planet reuse the same bucket.

This file is the registry of assignments, not the derived SQLite index the
console reads. It holds no credentials and no skill content.

## Resolvers

- Python: `core/skills/solar-paths/scripts/solar_runtime.py` —
  `runtime_root()`, `runtime_dir(*parts)`, `planet_state_dir(path, skill)`,
  `canonical(path)`.
- Bash: `core/skills/solar-paths/scripts/solar_runtime_paths.sh` —
  `solar_runtime_root`, `solar_runtime_dir`, `solar_planet_state_dir`,
  `solar_canonical_path`.

Both expose the same CLI through `solar_runtime.py`:

```bash
python3 core/skills/solar-paths/scripts/solar_runtime.py runtime async-tasks
python3 core/skills/solar-paths/scripts/solar_runtime.py planet /path/to/planets/<planet> <skill>
```

## Unattended tasks and their state home

A task launched by the router runs inside each client's own sandbox, which denies writes to the
planet state home. A skill whose state must live there opts in, on both sides:

1. The skill's `SKILL.md` frontmatter says `state_home: true`.
2. The task says `state_home: <skill>` (with its `planet`). It is part of what the user approves:
   changing it needs a new approval; a task that does not declare it hashes as before.

Before the provider starts, the worker resolves the folder with `planet_state_dir(path, skill,
create=True)` so a missing home fails the task early, then sends the router only the names
(`{"planet": ..., "skill": ..., "workspace": ...}`, never a path). The router derives the same
official folder itself with the same function, so no request can name another folder. It accepts
the names only on `async-task` requests that are not restricted, and only when the workspace is its
own. It gives the folder to the provider through one table, `STATE_HOME_GRANTS` in
`core/skills/solar-router/scripts/providers/base.py`:

| Client | Grant | Where the prompt goes |
|---|---|---|
| claude | `--add-dir <home>` | before the option (it is variadic and would swallow the prompt) |
| codex | `--add-dir <home>` | after it, before `--` |
| agent | `--add-dir <home>` | after it |
| agy | `--add-dir <home>` | after it, before `--print <prompt>` |

Only that `<skill>/` folder is opened: not the planet bucket, not a sibling skill, not
`~/Library/Application Support/Solar` or `~/.local/state/solar`. A client that is not in the table
(ollama) refuses the task. Without a declaration, no provider command changes.

**No fallback.** If the skill did not opt in (`state_home_not_declared`), the names are not plain
(`state_home_invalid`) or the folder cannot be created (`state_home_unavailable`), the task fails
with that code; nothing is written elsewhere. The grant opens a folder; it does not replace the
authority levels, `access_policy` or any domain gate. A task that cannot hold a grant fails with
`state_home_invalid` instead of ending as a success that never had it: a restricted review or
question, an `app` or `voice` preparation task (read-only), and an `executor: local` task (a script
Solar runs itself, with no client sandbox to open).

**Who validates what.** The worker validates the approval of the task. The router trusts its local
caller: `channel` and `workspace` bound the request but do not identify the worker. The gateway
rebuilds the router payload from explicit fields and leaves `state_home` out, so a caller on
Telegram, n8n or the WebSocket cannot declare one (regression test in
`core/tests/skills/solar-gateway/test_websocket_n8n_cut.py`).

### Manual verification

The sandbox itself is the client's, so the denial can only be seen with the real clients (versions
measured in issue #175: claude 2.1.323, codex-cli 0.167.0, Cursor agent 2026.11.13, agy 1.5.9). For
each client, run a task with `state_home` that (a) writes and reads `probe.txt` in the home,
(b) tries to write in a sibling skill folder, in the planet bucket and in `~/.local/state/solar`,
and expect (a) to succeed and every write in (b) to fail with `operation not permitted`. Record the
client version and the observed result. Automated tests only check the command Solar builds.

Result of 2026-11-17, through `run_router.py` with each client's production flags. A throwaway
planet with one skill that has `state_home: true` was created; for each client an `async-task`
request with `state_home` asked it to write `probe.txt` in the home and to try the three forbidden
writes. The check read the disk, not what the client said, and removed the throwaway planet after:

| Client (version) | Write in the skill's home | Sibling skill | Planet bucket | `~/.local/state/solar` |
|---|---|---|---|---|
| claude 2.1.323 | written | denied | denied | denied |
| codex-cli 0.167.0 | written | denied | denied | denied |
| Cursor agent 2026.11.13 | written | denied | denied | denied |
| agy 1.5.9 | written | denied | denied | denied |

For agy the request ended `failed` (`provider_locked_failed`): the probe asked it to try the three
forbidden writes, `write_file` was auto-denied in headless mode and the client returned no output. The
disk shows the isolation held; a real task that writes only in its home does not hit that path.
