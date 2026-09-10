---
name: solar-app
description: >
  Read-only Solar console on :9000. Inspect runtime health, async tasks, gateway
  failures, continuity freshness and router executions with injected context.
---

# Solar Console

Open `http://localhost:9000/app`. The existing status, logs and activity views
read task Markdown files and router `audit.jsonl` directly. No conversation
store, voice runtime, execution worker or mutation endpoints are provided.

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
