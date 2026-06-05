---
name: solar-app
description: >
  Solar App local control plane on :9000 — dashboard, fleet, governance editor, voice (tray + CLI via solar app voice).
---

# Solar App (`solar-app`)

Preferred human entrypoint for local operations UI/API on `:9000`.

## Required MCP

None

## CLI

```bash
solar app start|stop|status|open
solar app workspace list|add|remove|use <path>
solar app voice once|paste|command|read|ask|doctor   # ops/debug; primary UX = Solar.app tray
```

Global dispatcher: `core/skills/solar-client/scripts/solar` (`solar client *`, `solar status`, chat REPL).

## Runtime ownership

- Runtime scripts: `core/skills/solar-app/scripts/`
- Shared runtime modules: `interface_http.py`, `interface_store.py` (in-process on `:9000`)
- Voice: `voice_*.py`, macOS tray under `host_platform/macos/`
- `solar-interface` skill **removed** — legacy `:7741` daemon sunset

## Validation commands

```bash
bash core/tests/skills/solar-app/test_host_governance_tree.sh
bash core/tests/skills/solar-app/test_host_chat_e2e.sh
bash core/tests/skills/solar-app/test_host_api_smoke.sh
bash core/tests/skills/solar-app/test_host_fleet_client_actions.sh
bash core/tests/skills/solar-app/test_fleet_registry.sh
bash core/tests/skills/solar-app/test_workspace_mount.sh
bash core/tests/skills/solar-client/test_client_bundle.sh
python3 -m py_compile core/skills/solar-app/scripts/host_server.py
python3 -m py_compile core/skills/solar-app/scripts/interface_http.py
bash -n core/skills/solar-client/scripts/solar
```
