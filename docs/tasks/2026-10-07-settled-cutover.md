# Task spec: settled cutover

**Triage level:** standard
**Date:** 2026-10-07
**Status:** completed

## Objective

Stop `migrate` from treating a finished sqlite runtime as a snapshot of migration day, so a later install identity can record its marker.

## Scope

- Files to modify: `core/skills/solar-state/scripts/solar_state_cutover.py`, `core/skills/solar-state/SKILL.md`, `core/tests/skills/solar-state/test_cutover.py`, `CHANGELOG.md`, this task spec
- Files explicitly out of scope: the machine runtime (`~/Library/Application Support/Solar/runtime`), `solar client update`, `solar client sync`, release, push, files under `*.migrated-*`

## Acceptance criteria

- [x] When `STATE_FORMAT=sqlite` and no old-format file is still in place, `migrate` returns `already` without `_catch_up` or `_note_missing_sources`
- [x] That return still succeeds, so the client can record the new install marker
- [x] Full resume, including refusal of a real file change, stays when old files are still in place
- [x] Fixture tests cover the settled drift case and the interrupted refusal; they never use the machine runtime and never write into an aside directory
- [x] `CHANGELOG.md` has an Unreleased Fixed entry

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-state -q
uv run --project core/tests pytest core/tests/skills/solar-client -q
bash core/tests/skills/solar-client/test_client_update.sh
bash core/tests/skills/solar-client/test_client_bundle.sh
bash core/tests/skills/solar-client/test_client_language.sh
bash core/tests/skills/solar-client/test_client_upgrade.sh
bash core/tests/skills/solar-client/test_client_manifest.sh
bash core/tests/skills/solar-client/test_sync_exclude.sh
bash core/tests/skills/solar-client/test_sync_exclude_skills.sh
bash core/tests/skills/solar-client/test_sync_codex.sh
bash core/tests/skills/solar-client/test_sync_antigravity.sh
bash core/tests/skills/solar-client/test_sync_clients_prune.sh
bash core/tests/skills/solar-client/test_install_solar_client.sh
bash core/tests/skills/solar-client/test_update_notice.sh
bash core/tests/skills/solar-client/test_migrate_workspace_env_agy.sh
bash core/tests/skills/solar-client/test_shell_runtime_guard.sh
```

## References

- Repo policy: `CONTRIBUTING.md`
- RFC or context doc: N/A

## Implementation notes (optional)

- A finished migration is "no old-format file still at its live path". Empty directories recreated afterwards are not files: they are still put away, and they do not reopen catch-up.
- `task-logs/`, `tmp/` and `hooks/` are not the old format.
- The client writes `state-cutover.json` only after `migrate` exits 0. Returning `already` is what lets that write happen. This change does not write the marker itself.

## Completion evidence (optional)

- Validation:
  - `uv run --project core/tests pytest core/tests/skills/solar-state core/tests/skills/solar-client -q` -> 178 passed
  - `core/tests/skills/solar-client/test_*.sh` -> exit 0
- Files changed:
  - `core/skills/solar-state/scripts/solar_state_cutover.py`
  - `core/skills/solar-state/SKILL.md`
  - `core/tests/skills/solar-state/test_cutover.py`
  - `CHANGELOG.md`
  - `docs/tasks/2026-10-07-settled-cutover.md`
- Notes:
  - A finished migration returns `already` with an empty catch-up. The client writes `state-cutover.json` only after that command exits 0.
  - Empty directories recreated in the old places are still put away. A file that appears there again still takes the full resume.
  - No `solar client update`, no `solar client sync`, no release, no push. The machine runtime was not used.
