---
name: solar-interface
description: >
  Provide a local interactive entrypoint for Solar through a daemon-backed CLI and
  local web-ready API. Use when implementing or operating the interactive layer
  for threads, runs, approvals, and local runtime state over solar-router.
---

# Solar Interface

## Purpose

Provide the interactive runtime layer for Solar:
- local daemon with HTTP + JSON + SSE-ready interface,
- thin CLI wrapper (`solar`) over the same daemon,
- runtime state in `sun/runtime/interface/`,
- execution delegated to `solar-router`,
- host lifecycle supervised by `solar-system`.

## Scope

- Local single-user MVP.
- Health/status, threads, runs, and basic approvals lifecycle.
- Runtime initialization and schema migrations.
- No web UI build pipeline in v0.

## Required MCP

None

## Validation commands

```bash
# Validate skill structure
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-interface /tmp

# Shell checks
bash -n core/skills/solar-interface/scripts/interface_lib.sh
bash -n core/skills/solar-interface/scripts/onboard_interface_env.sh
bash -n core/skills/solar-interface/scripts/setup_interface.sh
bash -n core/skills/solar-interface/scripts/start_interface_daemon.sh
bash -n core/skills/solar-interface/scripts/stop_interface_daemon.sh
bash -n core/skills/solar-interface/scripts/check_interface.sh
bash -n core/skills/solar-interface/scripts/ensure_interface.sh
bash -n core/skills/solar-interface/scripts/status_interface.sh
bash -n core/skills/solar-interface/scripts/solar

# Python syntax
python3 -m py_compile core/skills/solar-interface/scripts/interface_server.py
```

## Runtime configuration

This skill manages a compact `.env` block:

```bash
bash core/skills/solar-interface/scripts/onboard_interface_env.sh
```

Block format:

```dotenv
# [solar-interface] required environment
SOLAR_INTERFACE_HOST=127.0.0.1
SOLAR_INTERFACE_PORT=7741
SOLAR_INTERFACE_RUNTIME_DIR=sun/runtime/interface
```

## Solar Client (workspace lifecycle)

Resolve paths before any command (`resolve_solar_paths.sh` exports `SOLAR_WORKSPACE`, `SOLAR_ROOT`; `solar_core_dir` → `$SOLAR_ROOT/core`):

```bash
solar client init                 # new workspace (manifest + sun; no .solar/core/)
solar client update               # update SOLAR_ROOT (full git repo by default)
solar client update --check       # compare global vs workspace manifest
solar client update --repair      # fix .solar/manifest.json (OneDrive conflicts)
solar client update --tag vX.Y.Z  # checkout tag in SOLAR_ROOT
solar client update --bundle      # rsync core/ only (no .git install)
solar client upgrade              # workspace manifest + prune SOLAR_ROOT IDE artifacts
solar client upgrade --check
solar client upgrade --restructure   # mv full framework repo -> solar/ (sun/, planets/, .solar/ stay at workspace root)
solar client sync
solar client sync --portable   # sync IDE + bundle create (opt-in portable publish)
solar client bundle create [--check]
solar client bundle verify
solar client doctor
solar client self-update         # alias: solar client update (global install)
solar status [--verbose]          # 5 blocks; verbose adds router detail + MCP hint
solar paths
```

### Workspace modes (`core_source`)

| Mode | Command to enter | `doctor` expectation |
|------|------------------|----------------------|
| **global** (default) | `solar client init` | OK without `.solar/bundle/` |
| **workspace-snapshot** | `solar client bundle create` | OK on machine **without** `SOLAR_ROOT` |

**OneDrive:** primary runs `update` + optional `bundle create`; secondary runs `doctor` only (do not edit manifest). Manifest conflicts → `update --repair`.

**Install (no monorepo clone):**

```bash
bash core/scripts/install_solar_client.sh
# or: curl -fsSL .../bootstrap_solar_client.sh | bash
```

After `update` on `SOLAR_ROOT`: `solar client sync` in each `SOLAR_WORKSPACE`.

Solar Client go/no-go smoke (v1.1 layout):

```bash
bash core/scripts/smoke-solar-client.sh ~/Solar/solar
# Ends with GO or NO-GO. Fast iteration: --skip-slow (skip client sync)
```

## Workflow

1. Bootstrap env block:
   - `bash core/skills/solar-interface/scripts/onboard_interface_env.sh`
2. Initialize runtime structure:
   - `bash core/skills/solar-interface/scripts/setup_interface.sh`
3. Start daemon manually:
   - `bash core/skills/solar-interface/scripts/start_interface_daemon.sh`
4. Check health:
   - `bash core/skills/solar-interface/scripts/check_interface.sh`
   - `bash core/skills/solar-interface/scripts/status_interface.sh`
5. Use CLI wrapper:
   - `bash core/skills/solar-interface/scripts/solar status`
   - `bash core/skills/solar-interface/scripts/solar ask "...""`

## Design notes

- `solar-interface` is the interactive layer, not the AI execution layer.
- `solar-router` remains the single source of truth for providers and execution.
- `solar-async-tasks` remains the subsystem for deferred work, not the default path for interactive runs.
- `solar-system` should supervise this feature when enabled.
