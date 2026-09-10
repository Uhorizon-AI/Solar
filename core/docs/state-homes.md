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

- Python: `core/skills/solar-client/scripts/solar_runtime.py` —
  `runtime_root()`, `runtime_dir(*parts)`, `planet_state_dir(path, skill)`,
  `canonical(path)`.
- Bash: `core/skills/solar-client/scripts/solar_runtime_paths.sh` —
  `solar_runtime_root`, `solar_runtime_dir`, `solar_planet_state_dir`,
  `solar_canonical_path`.

Both expose the same CLI through `solar_runtime.py`:

```bash
python3 core/skills/solar-client/scripts/solar_runtime.py runtime async-tasks
python3 core/skills/solar-client/scripts/solar_runtime.py planet /path/to/planets/louis calendar-sync
```
