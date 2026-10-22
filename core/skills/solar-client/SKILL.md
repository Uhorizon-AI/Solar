---
name: solar-client
description: >
  Solar Client workspace lifecycle: init, sync, update, upgrade, bundle, and client-only
  doctor. Use when operating workspace settings, IDE sync, portable bundle, or global
  install hygiene.
---

# Solar Client

## Purpose

Manage the relationship between **SOLAR_WORKSPACE** and **SOLAR_ROOT**:

- workspace settings (`.solar/settings.json`),
- IDE/agent sync (`sync-clients`),
- portable bundle (`workspace-snapshot`),
- global install update and self-update,
- **client-only** doctor (settings, bundle, symlinks, ports).

Workspace content health (`sun/`, `planets/`) is **`solar-workspace`** — use `solar workspace doctor`.

## IDE sync

| Client | Destination | How |
|--------|-------------|-----|
| Codex | `.agents/skills`; `.codex/agents` (opt-in) | skills: copy, shared with Antigravity; agents: derived roles, off by default |
| Claude | `.claude/{skills,agents,commands}` | symlink |
| Cursor | `.cursor/{skills,agents,commands}` | copy |
| Gemini | `.gemini/skills`, `.gemini/commands` | symlink; commands become toml |
| Antigravity | `.agents/skills` | copy, skills only |

Antigravity and Codex do not receive commands, workflows or rules. Solar records the names it copies in `.agents/skills/.solar-managed` and removes only those when they leave the index. `--codex-only` publishes those same copies. Sync does not write `.codex/skills`. Symlinks already there that point at `core/skills` of `SOLAR_ROOT` (including the portable bundle) or at `planets/*/skills` in this workspace are removed; other files and links stay. An empty `.codex/skills` is removed. `.codex/` stays when it still holds something else. A `CODEX_HOME` that points at another directory is not written and not deleted.

## Codex native agents (opt-in)

Off by default. When enabled, `solar client sync` (Codex client) also writes derived
roles `<planet>:<agent>.toml` into `.codex/agents/` from the top-level
`planets/<planet>/agents/*.md` contracts. The role `name` is `<planet>:<agent>`
(for example `uhorizon:uh-backend-dev`), with the contract `name` kept as is. Contracts
stay the only editable source. Roles published by earlier versions as
`solar__<planet>__<agent>` migrate automatically on the next `sync --codex-only`.

- Generated files carry only `name`, `description` and `developer_instructions`
  (a short wrapper plus the verbatim contract body). Never sandbox, approval, MCP,
  tools, network, model or credentials. Never edit them.
- Ownership is the manifest `.codex/agents/.solar-managed.json` plus a content hash
  and a generation mark. Edited, unmanaged, case-variant, symlinked or colliding files
  are reported as conflicts and never overwritten; only unchanged generated files are
  retired. Only `.codex/agents/` is written (never `.codex/config.toml` or `CODEX_HOME`).
- Exclusions: global `sync_exclude_planets` also applies; Codex-specific
  `exclude add|remove|list --client codex <planet>|<planet>:<agent>`. An excluded
  planet is never opened by the agent publisher, and agents that reference it are omitted.
- Before enabling, exclude any personal or private planet and run both previews, in
  this order (detail: [references/codex-agents.md](references/codex-agents.md)):

  ```bash
  solar client sync exclude add --client codex <personal-planet>
  solar client sync exclude list --client codex
  solar client sync codex-agents preview            # scope only; the planet must show as excluded
  solar client sync codex-agents preview --contents
  solar client sync codex-agents enable
  solar client sync --codex-only
  ```

  Global `exclude add <planet>` (no `--client`) is a wider decision: it hides the planet
  from every other client too.
- Planet and agent names may use only `[A-Za-z0-9_.-]`, must start with a letter or
  digit and are at most 64 characters each; other names are rejected with a reason,
  never rewritten. `:` in file names is not portable to Windows (known limit).

## Dashboards

A planet **declares** its surfaces in its own `planets/<planet>/.solar/dashboards.json`
(what a tool is and where it answers: name, title, description, owner, `updated_at`,
loopback `url`, `mode` of `read_only` or `interactive`). The declaration lives in the
planet's own `.solar/`, not in `operations/` and not in the Client-managed workspace
`.solar/`; a planet that `.gitignore`s `.solar/` cannot version it. This machine
**registers** the declared ids in the `dashboards` block of `.solar/settings.json`
(which are active here and the machine-specific start command, if any). The console
joins both, is read only and shows the start command as copyable text; it never starts
or probes a tool.

```bash
solar client sync dashboards status [--json]
solar client sync dashboards list [--json]
solar client sync dashboards seed <planet> [--force]
solar client sync dashboards register <planet>:<name> [--start-command CMD]
solar client sync dashboards unregister <planet>:<name>
solar client sync dashboards enable | disable
```

`register` writes settings only: it never starts a tool, never probes a port and never
reads or edits a planet file. `seed` is the only subcommand that writes inside a planet:
it creates the declaration if absent, validates an existing one without writing, and
overwrites only with `--force`; a symlinked `.solar` or declaration is refused. `disable`
hides tool declarations from the console and keeps the registration. Detail:
[references/dashboards.md](references/dashboards.md).
- Codex must trust the project and a new Codex session is needed to see new or changed
  roles. Publishing a role grants no authority. ChatGPT Chat/Work are not covered, and
  sessions started from a nested repository are not verified.

## Reduced publication (opt-in)

Native remains the default. `solar client sync profile set discovery --codex-only --dry-run`
previews the essential catalog and checks the registered Codex Solar MCP before
any settings or published copies change. `set discovery --codex-only` saves settings through the canonical atomic
Client writer; run `solar client sync --codex-only` to publish. Mandatory essentials are
`solar-mcp`, `solar-client`, `solar-paths`; add task-specific essentials explicitly.
`solar_search` and `solar_docs` still see eligible unpublished skills. Only managed copies are
pruned; personal resources remain. Revert with `profile set native` and sync.

This changes the shared `.agents` surface. Antigravity MCP registration is
unsupported: discovery requires the Codex-only choice, warns against using
Antigravity on this workspace, and refuses syncs that include Antigravity.
Other IDE catalogs remain full. Profile changes currently require global mode.
Details and byte-preview limits: [references/discovery-profile.md](references/discovery-profile.md).

## Required MCP

None

## Validation commands

```bash
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-client /tmp
bash -n core/skills/solar-client/scripts/client_lib.sh
bash -n core/skills/solar-client/scripts/client_doctor.sh
bash -n core/skills/solar-paths/scripts/resolve_solar_paths.sh
python3 -m py_compile core/skills/solar-paths/scripts/solar_paths.py
bash core/tests/skills/solar-paths/test_resolve_solar_paths.sh
bash core/tests/skills/solar-paths/test_solar_paths_py.sh
bash core/tests/skills/solar-client/test_sync_clients_prune.sh
bash core/tests/skills/solar-client/test_sync_exclude.sh
bash core/tests/skills/solar-client/test_sync_codex_agents.sh
uv run --project core/tests pytest core/tests/skills/solar-client/test_dashboards.py -q
uv run --project core/tests pytest core/tests/skills/solar-client/test_codex_agents.py -q
python3 -m py_compile core/skills/solar-client/scripts/codex_agents.py
bash core/tests/skills/solar-client/test_client_language.sh
bash core/tests/skills/solar-client/test_install_solar_client.sh
bash core/tests/skills/solar-client/test_update_notice.sh
bash core/skills/solar-client/scripts/smoke-solar-client.sh "$PWD"
```

The smoke runs offline against disposable install copies and workspaces, with a
separate runtime per workspace and simulated service/LaunchAgent controls. The
smoke does not write to the source install; it does not enforce filesystem
read-only access for shell suites run from that checkout. Failures include
captured command output. Inherited `SOLAR_TEST_*` opt-ins are cleared; run
optional suites separately.

## CLI (via `solar` entrypoint)

Canonical entry: `core/skills/solar-client/scripts/solar`

Resolve paths first (`resolve_solar_paths.sh` + `solar_paths.py`, in `solar-paths`):

```bash
solar client init
solar client update [options]
# common: --check | --repair | --ref/--tag | --bundle | --reinstall-launchagent | --no-restart | --restart | --resume
# --check is read-only (incompatible with --reinstall-launchagent; never restarts services,
#   so --restart / --no-restart do not apply to it)
# Output is a short summary; the full output is in <runtime>/update-logs/ (--verbose prints it).
# After a verified update, sync and doctor run in the workspace (--no-sync skips them).
solar client upgrade [--check|--restructure]
solar client sync profile show
solar client sync profile set discovery --codex-only --dry-run
solar client sync profile set discovery --codex-only [--essential planet:skill]
solar client sync profile set native
solar client sync [--portable]
solar client sync exclude list
solar client sync exclude add <planet>
solar client sync exclude remove <planet>
solar client sync exclude list|add|remove --client codex [<planet>|<planet>:<agent>]
solar client sync codex-agents status [--json]
solar client sync codex-agents preview [--contents] [--json]
solar client sync dashboards status|list [--json]
solar client sync dashboards seed <planet> [--force]
solar client sync dashboards register <planet>:<name> [--start-command CMD]
solar client sync dashboards unregister <planet>:<name>
solar client sync dashboards enable|disable
solar client bundle create|verify
solar client language
solar client language set en|es
solar client doctor [--strict]
solar client self-update
solar setup                # onboarding facade
solar uninstall            # remove wrapper; optional --remove-install
solar status               # compact health; system = check_orchestrator verdict
solar paths
solar agent --workspace <workspace> continuity show|export|restore ...
solar agent --workspace <workspace> facts init|append|read|backup|restore ...
solar mcp                  # stdio MCP server (IDE child)
solar mcp print|install|uninstall # user-level registration; install supports --dry-run
solar app …                # delegates to solar-app
```

`solar client language` prints the console language. It prints `en` when
`.solar/settings.json` has no `language` key. `solar client language set es`
writes `"language": "es"` there. That is how the console selects Spanish.
Do not edit that file by hand. `solar client update` keeps the key.

`solar client update` invokes `migrate_workspace_env_agy.py` internally when a
workspace still lists the retired `gemini` provider; do not run the helper as a
normal operator workflow.

On macOS, `solar client update --check` and a normal update **report** LaunchAgent
`SOLAR_ROOT` binding (read-only). `--reinstall-launchagent` is only valid on a real
update (not with `--check`): it rewrites the plist and restarts the transport
gateway; if gateway restart fails after a successful LaunchAgent reinstall, the
command exits non-zero.

A real update prepares the target version in a staging copy first (the live install is not
touched), then runs the target's own `client_update_staged.sh`: a maintenance barrier refuses every
claim and launcher, the ticks are paused, the async work drains (120 s; a timeout aborts before
anything is replaced), the console and gateway stop, and under the exclusive state lock the
runtime is backed up, the code is replaced and the schema migrated and validated. Only then are
the services that were running started, the code and schema verified, the ticks resumed and the
barrier released (`async-supervisor` is among the services detected and drained). A failure keeps
the services stopped and the barrier held; `solar client update --resume` continues the same
operation. `--no-restart` stops after the migration and holds the barrier until `--resume`;
`--check` writes nothing. `solar client sync` takes the same barrier. A first installation from
a release older than this one runs the staged entrypoint by hand with explicit paths. Details:
`core/docs/execution-reservations.md`.

`solar status` maps orchestrator `HEALTHY|PARTIAL|DOWN` → `OK|WARN|FAIL`. On WARN/FAIL, the `system` line points to `check_orchestrator.sh` for detail (no inline remediations).

Validation:

```bash
bash -n core/skills/solar-client/scripts/solar
bash -n core/skills/solar-client/scripts/solar_status.sh
bash -n core/skills/solar-client/scripts/solar_paths.sh
```

## Workspace modes (`core_source`)

| Mode | Enter | Leave | `client doctor` |
|------|-------|-------|-----------------|
| **global** | `solar client init` | — | OK without `.solar/bundle/` |
| **workspace-snapshot** | `solar client bundle create` | `solar client bundle remove` | OK without global `SOLAR_ROOT` for IDE reads. `update`, `sync` and the LaunchAgent use the global install; the bundle only publishes IDE links |

## Install

**Contract:** macOS supported; stable = GitHub Release `latest` (API + `curl`); smoke uses absolute wrapper path; no silent profile edits. Default: `~/.local/share/solar` + `~/.local/bin/solar`; workspace = any folder. Details: `core/docs/installation.md`.

```bash
curl -fsSL https://raw.githubusercontent.com/Uhorizon-AI/Solar/v0.19.2/core/skills/solar-client/scripts/bootstrap_solar_client.sh | bash
mkdir -p ~/Solar && cd ~/Solar && solar setup
solar uninstall [--remove-install]
```

Smoke / E2E: `bash core/tests/skills/solar-client/test_install_solar_client.sh`
(invokes the wrapper **without** `bash` so mode `100644` is detected)

Packaging backlog: `core/docs/packaging.md`

## Frontera

| Skill | Rol |
|-------|-----|
| **solar-client** | Manifest, bundle, IDE sync, install, **`solar` CLI entry** |
| **solar-workspace** | Doctors `sun/` + `planets/` |
| **solar-app** | Read-only status, activity and execution logs on :9000 |
