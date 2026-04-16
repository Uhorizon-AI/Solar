---
name: solar-browser
description: >
  Provide a shared browser runtime for Solar using one persistent browser with
  remote debugging enabled and safe cleanup of leaked browser DevTools MCP helper processes.
---

# Solar Browser

## Purpose

Provide one reusable browser runtime layer for Solar:
- keep a shared browser instance alive with remote debugging enabled,
- expose a stable `browserUrl` target for MCP clients,
- trim leaked DevTools MCP helper processes defensively,
- give Solar a consistent health check for browser automation prerequisites.

## Scope

- Shared local browser process with `--remote-debugging-port`.
- Safe detection and cleanup of stale DevTools MCP helper processes.
- Runtime health checks for orchestrated host use.
- No browser automation logic for WhatsApp, Zoho, LinkedIn, etc. Those stay in their own skills.

## Required MCP

None

## Validation commands

```bash
# Validate skill structure
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-browser /tmp

# Shell checks
bash -n core/skills/solar-browser/scripts/onboard_browser_env.sh
bash -n core/skills/solar-browser/scripts/setup_browser.sh
bash -n core/skills/solar-browser/scripts/ensure_browser.sh
bash -n core/skills/solar-browser/scripts/check_browser.sh

# Sync core changes to local clients
bash core/scripts/sync-clients.sh
```

## Runtime configuration

This skill manages a compact `.env` block:

```bash
bash core/skills/solar-browser/scripts/onboard_browser_env.sh
```

Block format:

```dotenv
# [solar-browser] required environment
SOLAR_BROWSER_DEBUG_HOST=127.0.0.1
SOLAR_BROWSER_DEBUG_PORT=9222
SOLAR_BROWSER_PROFILE_DIR=/tmp/com.solar.browser-profile
SOLAR_BROWSER_LOG_PATH=/tmp/com.solar.browser.log
SOLAR_SYSTEM_MAX_BROWSER_MCP_PROCS=3
```

Optional:

```dotenv
SOLAR_BROWSER_BINARY=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

## System activation (via solar-system)

Enable the feature in the Solar system block:

```dotenv
# [solar-system] required environment
SOLAR_SYSTEM_FEATURES=browser
```

Or combined with other features:

```dotenv
SOLAR_SYSTEM_FEATURES=browser,async-tasks,transport-gateway,interface
```

Then install or update the LaunchAgent:

```bash
bash core/skills/solar-system/scripts/install_launchagent_macos.sh
```

## Workflow

1. Bootstrap env block:
   - `bash core/skills/solar-browser/scripts/onboard_browser_env.sh`
2. Set up and verify runtime:
   - `bash core/skills/solar-browser/scripts/setup_browser.sh`
3. Ensure runtime is healthy:
   - `bash core/skills/solar-browser/scripts/ensure_browser.sh`
4. Check current health:
   - `bash core/skills/solar-browser/scripts/check_browser.sh`

## Design notes

- `solar-system` should orchestrate this skill, not reimplement it.
- MCP clients should point to the shared browser using `--browserUrl http://127.0.0.1:9222`.
- This skill owns the browser runtime only, not the consumer skill logic that uses DevTools.
