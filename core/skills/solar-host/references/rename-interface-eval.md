# Host-4: rename `solar-interface` → backend under `solar-host`

**Status:** deferred — evaluate after v0.19.0 when API contract is stable.

## Breaking surface

- Skill path `core/skills/solar-interface/` used in bundle allowlist, CLI `solar` entrypoint, LaunchAgent `interface` token
- `SOLAR_INTERFACE_*` env vars across workspaces
- IDE sync paths and docs

## Recommendation

Keep `solar-interface` as daemon/API skill name; Host remains human UI on `:9000`. Merge only if duplicate scripts cause drift.

## Metrics

Local append-only log: `~/Library/Application Support/Solar/host-metrics.jsonl` (see `host_registry.record_metric`).
