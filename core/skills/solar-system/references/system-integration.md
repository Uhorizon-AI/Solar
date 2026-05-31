# System Integration Notes

## Phase 1: macOS

- Supervisor model: one LaunchAgent (`com.solar.system`) with `StartInterval=60`.
- LaunchAgent binary: `sun/runtime/system/Solar` (compiled from `Solar.c` on install; resolves `run_orchestrator.sh` under `core/`).
- Orchestrator script: `core/skills/solar-system/scripts/run_orchestrator.sh --once`.
- Runtime dir override: `SOLAR_SYSTEM_RUNTIME_DIR` (default `sun/runtime/system`).
- Feature selector: `SOLAR_SYSTEM_FEATURES` (CSV).

## Feature dispatch

Supported `SOLAR_SYSTEM_FEATURES` tokens (orchestrator tick only):

- `async-tasks` -> `core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh`
- `transport-gateway` -> `core/skills/solar-gateway/scripts/ensure_transport_gateway.sh`
- `host` -> `ensure_host.sh` (Host UI `:9000`; workspace API in-process on same port)
- `interface` -> `ensure_interface.sh` (optional dev daemon `:7741`; not started by `host` feature)

## Why check-first recovery

Transport gateway setup is heavier than runtime checks. The orchestrator:
1. checks health first,
2. recovers only on degraded states.

This avoids unnecessary restarts on every scheduler tick.
