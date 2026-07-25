# Reference: A3 mandates (`sun/delegations/`)

Controller: `core/skills/solar-router/scripts/delegation_ctl.py`.
Schema and required controls: `core/docs/authority-model.md`.
Tests: `core/tests/skills/solar-router/test_delegation_ctl.py`.

An **A3 mandate** is written, delegated authority for a recurring routine. It is
unrelated to the router's JIT *delegation* of agents/skills
(`core/docs/jit-delegation-protocol.md`).

## Why this lives in core

`core/` defines `sun/delegations/` as the A3 standard, so the enforcement must ship
with the framework: any workspace, planet, skill script or async task can gate on it
without depending on a planet.

## Command surface

```bash
python3 "$SOLAR_ROOT"/core/skills/solar-router/scripts/delegation_ctl.py status
python3 "$SOLAR_ROOT"/core/skills/solar-router/scripts/delegation_ctl.py check <name> --action <action> [--items N] [--automated]
python3 "$SOLAR_ROOT"/core/skills/solar-router/scripts/delegation_ctl.py record-usage <name> --action <action> --items N
python3 "$SOLAR_ROOT"/core/skills/solar-router/scripts/delegation_ctl.py shadow-log <name> --action <action> --details "…"
python3 "$SOLAR_ROOT"/core/skills/solar-router/scripts/delegation_ctl.py record-result <name> --result success|failure --exit-code N
python3 "$SOLAR_ROOT"/core/skills/solar-router/scripts/delegation_ctl.py activate <name> --i-approve
python3 "$SOLAR_ROOT"/core/skills/solar-router/scripts/delegation_ctl.py revoke <name>
```

Exit codes: `0` ok · `1` mandate not found · `2` refused (fail-closed).

## Fail-closed rules

- `check` validates required fields, `valid_from`/`expires_at`, revoked state, `mode`
  and exact `allowed_actions` membership. Callers must treat a non-zero exit as a hard
  stop, never as a warning.
- While `mode: shadow`, only actions in `shadow_safe_actions` may run (default:
  `status`, `check`, `dry-run`, `validate`, `shadow`). Anything else —
  including `resolve` (writes YAML/salt), `score`, `run`, and free-form write
  phrases — is refused. Mandates may narrow the allowlist with an explicit
  `shadow_safe_actions:` block (intersection with the default); they cannot widen it.
- `--automated` enforces `limits.frequency`. Supported forms: `every N hours` /
  `cada N horas`, `every N days` / `cada N días`. If `frequency:` is present and
  unparseable, automated runs **fail closed** (do not silently skip cadence).
  Interactive requests omit `--automated` (fresh A2, not a cadence breach).
- `max_items_per_day` requires `--items` before execution. Reserve capacity with
  `record-usage` **before** processing a batch: it rechecks under an exclusive lock, so
  splitting a batch cannot bypass the daily cap.
- Stop conditions are independent of cadence: three consecutive `failure` results or a
  `stop_requested` event block execution in any mode.
- `activate` requires `--i-approve` (owner A2 formal) **and** at least one **valid**
  entry in `sun/runtime/delegations/<name>/shadow.jsonl`: JSON object with
  `mode: "shadow"`, `applied: false`, and `intended_action` ∈
  `allowed_actions ∩ shadow_safe_actions`.
  Blank lines, non-JSON, `applied: true`, or actions outside the allowlist do **not**
  count. Never satisfy that prerequisite with test or placeholder entries.
- `shadow-log` refuses actions outside `allowed_actions` / `shadow_safe_actions` and
  refuses `--applied` while `mode: shadow` (always writes `applied: false` in shadow).
- Stop conditions and cadence (`--automated`) apply to **every** executable action
  under the mandate (including non-mutating ones such as `score` when active).
  Callers must fail closed on non-zero exit.
- Prefer short action tokens in `allowed_actions` (`score`, `dry-run`), not prose
  sentences — the gate matches exact strings.

## Evidence

- `shadow.jsonl` — intended actions while in shadow (`applied: false`).
- `events.jsonl` — `usage_reserved`, `execution_result`, `activated`, `revoked`,
  `stop_requested`.

Runtime paths are overridable via `SOLAR_DELEGATIONS_DIR` and
`SOLAR_DELEGATIONS_RUNTIME` so tests never touch live mandates.
