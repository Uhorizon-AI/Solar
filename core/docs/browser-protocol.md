# Chrome DevTools MCP — Browser on Demand

Goal: keep `browserUrl` shared for multi-agent stability, without keeping Chrome on all day.

## Required Flow (no user prompt)

1. Before first Chrome DevTools MCP call in a task (or after MCP connect error), run:

```bash
bash core/skills/solar-browser/scripts/ensure_browser.sh --start
```

2. Reuse the same runtime during the browser workflow (do not stop between MCP tool calls).

3. At natural completion of that browser workflow, run:

```bash
bash core/skills/solar-browser/scripts/ensure_browser.sh --stop
```

4. Never ask the user to keep Chrome/debugging running 24/7.
5. `--stop` should block only when **other** MCP clients are active (safe default assumes your current session). If blocked, do not force-close by default; use `--stop --force` only when you are sure no other active workflow should keep the shared runtime.

If sandbox blocks `ensure_browser.sh` (for example `ps: Operation not permitted`), re-run the same command with full permissions.
