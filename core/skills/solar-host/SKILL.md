---
name: solar-host
description: >
  Solar App (skill solar-host) — local app on :9000: fleet UI, API, voice, approvals.
  Product name Solar App; folder rename to solar-app planned. Primary human entry.
---

# Solar App (`solar-host`)

## Purpose

Machine-local **localhost** control plane:

- **Fleet:** registry of workspaces (`{app_data}/Solar/workspaces.json` via `host_platform/paths`; override tests with `SOLAR_APP_DATA`)
- **Workspace switch:** `solar host workspace use` calls Host `:9000` when running; set `SOLAR_HOST_OFFLINE=1` to force local-only (tests)
- **Health:** semaphores per workspace + `solar status`
- **HitL:** approvals inbox (in-process `InterfaceStore`; legacy `:7741` proxy optional)
- **Async:** job timeline under `sun/runtime/async-tasks/`
- **Runtime:** start interface/gateway, kill switch
- **Scoped chat** and **markdown editor** for `sun/` / `planets/`

**Not:** generalist chat, code IDE, M2M webhooks (`solar-gateway`).

## Required MCP

None

## Ports

| Service | Default | Role |
|---------|---------|------|
| **Solar Host** | `127.0.0.1:9000` | Human UI + in-process workspace API |
| **solar-gateway** | `:8787` + hash per workspace | Webhooks M2M |

## CLI

```bash
solar host start|stop|status|open
solar host workspace list|add|remove|use <path>
solar voice once|paste|command|read
python3 core/skills/solar-host/scripts/host_tray.py   # optional; needs rumps
bash core/skills/solar-host/scripts/onboard_host_env.sh
```

## LaunchAgent

Add `host` to `SOLAR_SYSTEM_FEATURES`. Orchestrator runs `ensure_host.sh` (workspace API in-process on `:9000`; no separate `:7741` daemon).

## Voice (part of this skill)

Scripts: `scripts/voice_cli.py` — not a separate bundle skill (`solar-voice` is a deprecation stub only).

## Validation

```bash
bash -n core/skills/solar-host/scripts/host_lib.sh
python3 -m py_compile core/skills/solar-host/scripts/host_platform/paths.py
python3 -m py_compile core/skills/solar-host/scripts/host_workspace_context.py
python3 -m py_compile core/skills/solar-host/scripts/host_interface.py
python3 -m py_compile core/skills/solar-interface/scripts/interface_store.py
python3 -m py_compile core/skills/solar-interface/scripts/interface_http.py
python3 -m py_compile core/skills/solar-interface/scripts/interface_server.py
python3 -m py_compile core/skills/solar-host/scripts/host_events.py
python3 -m py_compile core/skills/solar-host/scripts/host_server.py
python3 -m py_compile core/skills/solar-host/scripts/host_registry.py
python3 -m py_compile core/skills/solar-host/scripts/voice_cli.py
bash core/tests/skills/solar-host/test_fleet_registry.sh
bash core/tests/skills/solar-host/test_fleet_api_contract.sh
bash core/tests/skills/solar-host/test_host_platform_import.sh
bash core/tests/skills/solar-host/test_workspace_mount.sh
bash core/tests/skills/solar-host/test_host_api_smoke.sh
bash core/tests/skills/solar-host/test_host_interface_routes.sh
bash core/tests/skills/solar-host/test_no_legacy_listener_after_switch.sh
```

## Frontera

| Layer | Rol |
|-------|-----|
| **IDE** | Code, refactors |
| **Solar Host** | Operations, fleet, approvals, governance |
| **solar-interface** | CLI `solar ask` + optional dev daemon; Host uses `InterfaceStore` in-process |
| **voice** (`voice_cli.py`) | Speech → Host API — same skill, not `solar-voice` bundle |
| **solar-client** | init, sync, bundle |

## Rename note

See `references/rename-interface-eval.md` — keep `solar-interface` as API skill until Host-4 review.
