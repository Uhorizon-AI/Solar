# System Integration Notes

## Phase 1: macOS

- Supervisor model: one LaunchAgent (`com.solar.system`) with `StartInterval=60`.
- Orchestrator entrypoint: `core/skills/solar-system/scripts/run_orchestrator.sh --once`.
- Feature selector: `SOLAR_SYSTEM_FEATURES` (CSV).

## Feature dispatch

- `async-tasks` -> `core/skills/solar-async-tasks/scripts/run_worker.sh --once`
- `transport-gateway` -> `core/skills/solar-transport-gateway/scripts/ensure_transport_gateway.sh`

## Why check-first recovery

Transport gateway setup is heavier than runtime checks. The orchestrator:
1. checks health first,
2. recovers only on degraded states.

This avoids unnecessary restarts on every scheduler tick.
