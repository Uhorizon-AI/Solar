---
name: solar-app
description: >
  Read-only Solar console on :9000. Inspect runtime health, async tasks, gateway
  failures, continuity freshness and router executions with injected context.
---

# Solar Console

Open `http://localhost:9000/app`. Status, logs and activity come from the views in
`state.sqlite` (`runtime_views`). No conversation store, voice runtime, execution
worker or mutation endpoints are provided.

## Required MCP

None

## CLI

```bash
solar app start|stop|status|open
solar app workspace list|add|remove|use <path>
solar status
```

The global dispatcher is `core/skills/solar-client/scripts/solar`.
`app_http.py` serves the console; `app_solar.py` reads its canonical sources.
`host_registry.py` and `host_workspace_context.py` retain workspace selection.
The console port is fixed at 9000. The registry and metrics keep their current
machine-local paths; runtime files remain under `<runtime root>/`.

Health requires a fresh source read. Task failures describe the task, not the
health of Solar. A router start without a recent end is not proof of a live
process. History turns and summaries are traceability, not a contamination detector.
A missing gateway probe is unverified, not healthy. Recorded failures retain their
date. The browser marks readings older than 120 seconds as unverified.

## Console data

Eight read-only routes under `/api/console/`: `health`, `tasks`, `executions`,
`continuity`, `mandates`, `ides`, `ingress`, `requester`. `console_data.py`
answers them. Database rows come from `read_session()` in solar-state. Files
outside the database (owner, cutover, pass stamp, daily backups, IDE trees,
gateway stamp, mandate YAML, MCP gate audit) are read through solar-paths.
These routes create no runtime file.

`verdict` is `calm`, `fault`, or `unverified`. A fresh pass stamp is healthy
only when local `/health`, the connector, and the ws, http, and tunnel
processes are all up. A stamp older than five minutes is a fault. No stamp
leaves the pass and the gateway unverified. Quiet time is not a fault by itself.
The host refuses to bind when `SOLAR_APP_HOST` is not a loopback address.

## Validation commands

```bash
python3 -m unittest discover -s core/tests/skills/solar-app -p 'test_*.py'
python3 -m py_compile core/skills/solar-app/scripts/host_server.py
bash -n core/skills/solar-client/scripts/solar
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-app /tmp
```

## Laptop runtime note

Host sleep stops availability. Only one active host should serve the same public
route. This console is local and does not replace the gateway or transports.
