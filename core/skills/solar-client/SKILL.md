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

## Required MCP

None

## Validation commands

```bash
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-client /tmp
bash -n core/skills/solar-client/scripts/client_lib.sh
bash -n core/skills/solar-client/scripts/client_doctor.sh
bash -n core/skills/solar-client/scripts/resolve_solar_paths.sh
python3 -m py_compile core/skills/solar-client/scripts/solar_paths.py
bash core/tests/skills/solar-client/test_resolve_solar_paths.sh
bash core/tests/skills/solar-client/test_solar_paths_py.sh
bash core/tests/skills/solar-client/test_sync_clients_prune.sh
bash core/tests/skills/solar-client/test_sync_exclude.sh
bash core/tests/skills/solar-client/test_install_solar_client.sh
bash core/skills/solar-client/scripts/smoke-solar-client.sh "$PWD"
```

## CLI (via `solar` entrypoint)

Canonical entry: `core/skills/solar-client/scripts/solar`

Resolve paths first (`resolve_solar_paths.sh` + `solar_paths.py` in this skill):

```bash
solar client init
solar client update [--check|--repair|--ref|--tag|--bundle]
solar client upgrade [--check|--restructure]
solar client sync [--portable]
solar client sync exclude list
solar client sync exclude add <planet>
solar client sync exclude remove <planet>
solar client bundle create|verify
solar client doctor [--strict]
solar client self-update
solar setup                # onboarding facade
solar uninstall            # remove wrapper; optional --remove-install
solar status               # compact health; system = check_orchestrator verdict
solar paths
solar app …                # delegates to solar-app
```

`solar client update` invokes `migrate_workspace_env_agy.py` internally when a
workspace still lists the retired `gemini` provider; do not run the helper as a
normal operator workflow.

`solar status` maps orchestrator `HEALTHY|PARTIAL|DOWN` → `OK|WARN|FAIL`. On WARN/FAIL, the `system` line points to `check_orchestrator.sh` for detail (no inline remediations).

Validation:

```bash
bash -n core/skills/solar-client/scripts/solar
bash -n core/skills/solar-client/scripts/solar_status.sh
bash -n core/skills/solar-client/scripts/solar_paths.sh
```

## Workspace modes (`core_source`)

| Mode | Enter | `client doctor` |
|------|-------|-----------------|
| **global** | `solar client init` | OK without `.solar/bundle/` |
| **workspace-snapshot** | `solar client bundle create` | OK without global `SOLAR_ROOT` |

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
| **solar-app** | Control plane UI/API + voice runtime |
