---
name: solar-host
description: >
  Solar Host — local control plane UI (default :9000): workspace health, approvals inbox,
  and scoped operations. Primary human entry (not IDE chat on :7741). Backend uses solar-interface daemon.
---

# Solar Host

## Purpose

Single **localhost** control plane for the active workspace:

- health dashboard (`solar status`),
- human-in-the-loop approvals (proxy to interface API),
- deep link to IDE for code work.

**Not:** generalist chat, code editor, or M2M webhooks (see `solar-gateway`).

## Required MCP

None

## Ports

| Service | Default | Role |
|---------|---------|------|
| **Solar Host** | `127.0.0.1:9000` | Human UI |
| **solar-interface** | `:7741` per workspace | Daemon/API backend |
| **solar-gateway** | `:8787` per workspace | Webhooks M2M |

## CLI

```bash
solar host start|stop|status|open
bash core/skills/solar-host/scripts/onboard_host_env.sh
```

## Validation

```bash
bash -n core/skills/solar-host/scripts/host_lib.sh
python3 -m py_compile core/skills/solar-host/scripts/host_server.py
bash core/skills/solar-host/scripts/start_host.sh
bash core/skills/solar-host/scripts/check_host.sh
```

## Frontera

| Layer | Rol |
|-------|-----|
| **IDE** | Code, refactors |
| **Solar Host** | Operations, approvals, governance overview |
| **solar-interface** | Daemon/DB/API (backend) |
| **solar-client** | init, sync, bundle |

## Voice (planned)

`solar voice once` — see [solar-host-plan](../../../../sun/plans/2026/05/2026-05-29_solar-host-plan.md). MVP ships UI first; voice is a follow-up slice.
