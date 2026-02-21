---
name: solar-system
description: >
  Integrate Solar runtime with the host system. Install and manage a single macOS
  LaunchAgent that orchestrates enabled Solar features from one entrypoint.
---

# Solar System

## Purpose

Provide one system-level control point for Solar runtime operations:
- install and manage a single LaunchAgent on macOS,
- orchestrate enabled features in one periodic tick,
- keep feature ownership inside existing skills.

## Scope

- Phase 1: macOS (`launchd`) support.
- Orchestrate enabled features from `.env`:
  - `async-tasks`
  - `transport-gateway`
- Keep orchestration deterministic and non-overlapping.

## Required MCP

None

## Validation commands

```bash
# Validate this skill
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-system /tmp

# Basic shell checks
bash -n core/skills/solar-system/scripts/run_orchestrator.sh
bash -n core/skills/solar-system/scripts/install_launchagent_macos.sh
bash -n core/skills/solar-system/scripts/check_orchestrator.sh

# Sync core changes to local clients
bash core/scripts/sync-clients.sh
```

## Runtime configuration

This skill manages a compact `.env` block:

```bash
bash core/skills/solar-system/scripts/onboard_system_env.sh
```

Block format:

```dotenv
# [solar-system] required environment
SOLAR_SYSTEM_FEATURES=async-tasks
```

`SOLAR_SYSTEM_FEATURES` is a CSV selector. Supported values:
- `async-tasks`
- `transport-gateway`

**Note:** `SOLAR_SYSTEM_FEATURES` is also read by `solar-router` to determine if `async-tasks` is available for async draft creation. Keep this value consistent with your active runtime configuration.

## Workflow

1. Bootstrap runtime env block:
   - `bash core/skills/solar-system/scripts/onboard_system_env.sh`
2. Install or update LaunchAgent:
   - `bash core/skills/solar-system/scripts/install_launchagent_macos.sh`
3. Check current status:
   - `bash core/skills/solar-system/scripts/status_launchagent_macos.sh` — supervisor only (plist + launchctl + logs)
   - `bash core/skills/solar-system/scripts/check_orchestrator.sh` — full orchestrator + feature health (daily operational check)
   - `bash core/skills/solar-system/scripts/diagnose_launchagent.sh` — deep troubleshooting when there is an incident
4. Uninstall LaunchAgent (if needed):
   - `bash core/skills/solar-system/scripts/uninstall_launchagent_macos.sh`

## Orchestrator behavior

`run_orchestrator.sh --once`:
1. loads `.env`,
2. reads `SOLAR_SYSTEM_FEATURES`,
3. acquires a lock to avoid overlapping ticks,
4. runs enabled features in order:
   - async tasks: `run_worker.sh --once`
   - transport gateway: `core/skills/solar-transport-gateway/scripts/ensure_transport_gateway.sh`

## Design notes

- Uses one LaunchAgent label: `com.solar.system`.
- Avoids calling full transport setup on every tick when not needed.
- Keeps transport and async logic in their own skills.

## Laptop runtime note (optional)

- This skill can orchestrate long-running local runtime endpoints indirectly (through transport gateway feature).
- If the active host is a laptop, host sleep can stop runtime availability.
- This is a host operations concern, not a mandatory dependency.
- If multiple laptops are used, only one active host should serve the same public route at a time.
