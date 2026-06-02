---
name: solar-app
description: >
  Solar App local control plane on :9000.
---

# Solar App (`solar-app`)

Preferred human entrypoint for local operations UI/API on `:9000`.

## Required MCP

None

## CLI

```bash
solar app start|stop|status|open
solar app workspace list|add|remove|use <path>
```

## Runtime ownership

- Runtime scripts are canonical in `core/skills/solar-app/scripts/`.
- `solar-interface/scripts/solar` dispatches `app` to this runtime.
