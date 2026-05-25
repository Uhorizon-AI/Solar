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
solar client upgrade              # migrate v0.9.0 workspaces (removes .solar/core/)
solar client sync
solar client doctor
solar status                      # 5 blocks: interface, sun, system, router, browser
solar paths                       # @path hints for IDE
```

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
