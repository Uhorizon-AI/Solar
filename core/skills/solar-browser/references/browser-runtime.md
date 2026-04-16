# Browser Runtime Pattern

- One persistent browser process per host.
- Remote debugging exposed locally only.
- One dedicated profile directory for the daemon.
- Multiple MCP clients may connect to the same browser via `--browserUrl`.
- Defensive cleanup trims stale browser DevTools MCP helper processes, but should not kill the shared browser if it is healthy.
