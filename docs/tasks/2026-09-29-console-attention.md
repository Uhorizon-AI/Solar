# Task spec: console attention line

**Triage level:** standard
**Date:** 2026-09-29
**Status:** completed

## Objective

Make the Solar console say what needs attention, in plain language, without the page deciding the verdict line or showing internal codes. Console copy is English by default. Spanish is a second catalog, selected when workspace settings set `language` to `es`. That key is written by `solar client language`, not by editing `.solar/` by hand.

## Scope

- Files to modify: `core/skills/solar-app/scripts/console_data.py`, `core/skills/solar-app/assets/app.js`, `core/skills/solar-app/assets/app.css`, `core/skills/solar-app/assets/app.html`, `core/skills/solar-app/SKILL.md`, `core/tests/skills/solar-app/test_console_read.py`, `core/tests/skills/solar-app/test_console_ui.py`, `core/skills/solar-client/scripts/client_lib.sh`, `core/skills/solar-client/scripts/client_language.sh`, `core/skills/solar-client/scripts/solar`, `core/skills/solar-client/SKILL.md`, `core/tests/skills/solar-client/test_client_language.sh`, `CHANGELOG.md`
- Files explicitly out of scope: continuity payload shape, hand edits under `.solar/`, push

## Acceptance criteria

- [x] `/api/console/health` returns `attention`: calm lists only non-zero counts; fault names the cause; unverified names what is missing
- [x] The summary shows that sentence and does not compose it
- [x] Continuity screen and summary card explain the record; the active intention is labeled as stored text; continuity data is unchanged
- [x] Delegation modes are named; a revoked row is dimmed, shows `revoked_at`, and is not in `active`
- [x] Console copy does not contain authority codes A0–A4 or "Mandatos A3"
- [x] Console copy is English when `language` is missing. `"language": "es"` (also `es-ES` or `spanish`) selects Spanish. Health returns that `language`. The page follows it, including the browser title. Those aliases live in `console_language.py`
- [x] `solar client language set es` writes `language` in `.solar/settings.json`. `solar client update` keeps the key. A missing key stays English
- [x] solar-app, solar-state, and solar-client checks pass

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state -q
python3 -m py_compile core/skills/solar-app/scripts/console_data.py
bash core/tests/skills/solar-client/test_client_language.sh
bash -n core/skills/solar-client/scripts/client_language.sh
bash -n core/skills/solar-client/scripts/client_lib.sh
bash -n core/skills/solar-client/scripts/solar
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-app /tmp
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-client /tmp
```

## References

- Repo policy: `CONTRIBUTING.md`
- RFC or context doc: N/A

## Implementation notes (optional)

- English is the default. This workspace has no `language` key, so the console stays English until someone runs `solar client language set es`. Do not edit `.solar/settings.json` by hand.
- Quiet days are whole days since the newest of router, task, and mandate activity. Under one day, or no timestamp, the clause is omitted.
- A filled `revoked_at` forces mode `revoked` in `defined`, `modes`, and `active`, including when the file still says `mode: active`.

## Completion evidence (optional)

- Validation:
  - `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state -q` -> pass (200)
  - `bash core/tests/skills/solar-client/test_client_language.sh` -> passed=10 failed=0
  - `core/tests/skills/solar-client/test_*.sh` -> exit 0
  - `package_skill.py` for `solar-app` and `solar-client` -> packaged
- Files changed: listed in Scope
- Notes: local review only; no commit
