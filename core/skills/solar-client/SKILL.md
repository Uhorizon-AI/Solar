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
| Codex | `.agents/skills` | copy, skills only, shared with Antigravity |
| Claude | `.claude/{skills,agents,commands}` | symlink |
| Cursor | `.cursor/{skills,agents,commands}` | copy |
| Gemini | `.gemini/skills`, `.gemini/commands` | symlink; commands become toml |
| Antigravity | `.agents/skills` | copy, skills only |

Antigravity and Codex do not receive commands, workflows or rules. Solar records the names it copies in `.agents/skills/.solar-managed` and removes only those when they leave the index. `--codex-only` publishes those same copies. Sync does not write `.codex/skills`. Symlinks already there that point at `core/skills` of `SOLAR_ROOT` (including the portable bundle) or at `planets/*/skills` in this workspace are removed; other files and links stay. An empty `.codex/skills` is removed. `.codex/` stays when it still holds something else. A `CODEX_HOME` that points at another directory is not written and not deleted.

## Reduced publication (opt-in)

Native remains the default. `solar client sync profile set discovery --codex-only --dry-run`
previews the essential catalog and checks the registered Codex Solar MCP before
any settings or published copies change. `set discovery --codex-only` saves settings through the canonical atomic
Client writer; run `solar client sync --codex-only` to publish. Mandatory essentials are
`solar-mcp`, `solar-client`, `solar-paths`; add task-specific essentials explicitly.
Search/Describe still sees eligible unpublished skills. Only managed copies are
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
bash core/tests/skills/solar-client/test_client_language.sh
bash core/tests/skills/solar-client/test_install_solar_client.sh
bash core/tests/skills/solar-client/test_update_notice.sh
bash core/skills/solar-client/scripts/smoke-solar-client.sh "$PWD"
```

## CLI (via `solar` entrypoint)

Canonical entry: `core/skills/solar-client/scripts/solar`

Resolve paths first (`resolve_solar_paths.sh` + `solar_paths.py`, in `solar-paths`):

```bash
solar client init
solar client update [options]
# common: --check | --repair | --ref/--tag | --bundle | --reinstall-launchagent | --no-restart | --restart
# --check is read-only (incompatible with --reinstall-launchagent; never restarts services,
#   so --restart / --no-restart do not apply to it)
solar client upgrade [--check|--restructure]
solar client sync profile show
solar client sync profile set discovery --codex-only --dry-run
solar client sync profile set discovery --codex-only [--essential planet:skill]
solar client sync profile set native
solar client sync [--portable]
solar client sync exclude list
solar client sync exclude add <planet>
solar client sync exclude remove <planet>
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

When the installed version changes, a real update restarts the long-running
services that are already running (transport gateway, console on :9000) so they
load the new code; nothing that is stopped gets started, and the async-tasks
worker needs no restart. `--no-restart` skips this; `--restart` forces it even
when the version did not change. If a restart fails, the update still applies,
the manual command is printed and the command exits non-zero.

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
