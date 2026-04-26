# Browser Runtime Pattern

- One shared browser runtime per host, started/stopped on demand.
- Remote debugging exposed locally only.
- One dedicated profile directory for the daemon.
- Multiple MCP clients may connect to the same browser via `--browserUrl`.
- Defensive cleanup trims stale browser DevTools MCP helper processes.
- Safe teardown default: `ensure_browser.sh --stop` refuses to stop only if other MCP clients are detected; `--stop --force` is explicit override.