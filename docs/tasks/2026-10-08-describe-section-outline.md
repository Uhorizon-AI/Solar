# Task spec: describe section outline

**Triage level:** standard
**Date:** 2026-10-08
**Status:** completed

## Objective

Stop capability describe from returning a whole large skill by default, while keeping governance text intact and still allowing an exact section or the full unit.

## Scope

- Files to modify: `core/skills/solar-mcp/scripts/capability_registry.py`, `core/skills/solar-mcp/scripts/mcp_server.py`, `core/skills/solar-mcp/references/discovery.md`, `core/docs/capability-discovery-design.md` (describe contract), `core/tests/skills/solar-mcp/test_discovery.py`, `core/tests/skills/solar-mcp/test_server_wire.py`, `CHANGELOG.md`, this task spec
- Files explicitly out of scope: search clipping, Client profiles, the installed runtime, `~/.codex`, `solar client update`, `solar client sync`, release, push

## Acceptance criteria

- [x] `describe(id, revision?, reference?, section?, full?)` returns a heading outline for a unit larger than 4 KiB when that outline's response JSON is under 85% of the complete-body response JSON. Otherwise it returns the complete body. The outline carries id, description, revision, level-2 and level-3 titles with byte sizes, registered references, and governance sections copied in full
- [x] A unit of 4 KiB or less returns the complete body, as before
- [x] `section` returns only that exact heading; a missing title errors with the title list; `full=true` returns the complete body, including the existing 64 KiB response limit
- [x] Governance is a case-insensitive substring of the heading. The markers are `authority`, `gate`, `governance`, `safety`, `never`, `approval`, `autoridad`, `gobernanza`, `seguridad`, `nunca`, `aprobaci`, `obligatori`, `prohib`, `regla`, `límite`, `limite`, `dependencia`, and `antes de`. Text is an original slice, never a summary. Gates are not dropped to save space
- [x] The preamble, from after the frontmatter through the character before the first level-2 heading, is copied whole into the outline. A response that does not fit in 64 KiB is refused
- [x] `section` and `reference` do not accept paths. Revision and containment checks stay in place
- [x] Tests cover a large outline, a present and a missing section, `full=true`, governance text, a small skill, Spanish rule titles, a complete preamble, a refused oversized preamble, every marked title in `core/` skills larger than 4 KiB, an outline kept when it is under 85% of the body, an outline replaced by the body when it is larger, and the outline-versus-body byte comparison. The seven existing tool wire tests stay green
- [x] `CHANGELOG.md` records the change under Unreleased

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-mcp -q
uv run --project core/tests pytest core/tests/skills/solar-client -q
```

## References

- Repo policy: `CONTRIBUTING.md`
- RFC or context doc: `core/docs/capability-discovery-design.md`, `core/skills/solar-mcp/references/discovery.md`
- Previous delivery: `docs/tasks/2026-10-08-search-description-cap.md`

## Implementation notes (optional)

- 4 KiB means 4096 bytes of the selected unit (the skill, or the reference when one is selected).
- A section runs from its heading through the character before the next heading of the same or higher level. Only column-0 ATX headings of level 2 and 3 count, and headings inside fenced code blocks do not.
- A level-2 slice includes its level-3 children. Each matching governance heading is included as its own slice, so a matching parent can repeat a matching child.
- The first exact title wins when two headings share a name. `section` together with `full=true` is refused.
- `revision` stays the skill-file hash. `unit_revision` hashes the selected unit, or the returned section when `section` is set.
- Accents are not folded. `límite` and `limite` are separate markers. `aprobaci` matches `aprobación` without listing the accented ending.
- Rebased onto `main` after pull request 12, so this branch no longer carries the search-cap commit.
- The 85% check compares response JSON bytes (`indent=2`, `sort_keys=True`). An outline that is not strictly under 85% of the complete body is discarded and the complete body is returned.

## Completion evidence (optional)

- Validation:
  - `uv run --project core/tests pytest core/tests/skills/solar-mcp -q` -> 118 passed
  - `uv run --project core/tests pytest core/tests/skills/solar-client -q` -> 9 passed
- Files changed:
  - `core/skills/solar-mcp/scripts/capability_registry.py`
  - `core/skills/solar-mcp/scripts/mcp_server.py`
  - `core/skills/solar-mcp/references/discovery.md`
  - `core/docs/capability-discovery-design.md`
  - `core/tests/skills/solar-mcp/test_discovery.py`
  - `core/tests/skills/solar-mcp/test_server_wire.py`
  - `CHANGELOG.md`
- Notes:
  - Byte comparison, response JSON (`indent=2`, `sort_keys=True`). Large fixture: **outline 1,474 bytes**, **complete body 6,120 bytes** (24.1% of the body, so the outline is returned). Spanish fixture (`Dependencia obligatoria · la voz`, `Reglas duras`): **outline 1,247 bytes**, **complete body 5,013 bytes** (24.9%, outline returned). Heavy-rules fixture (`Reglas duras` plus `Prohibido resumir`): **outline 11,792 bytes**, **complete body 5,942 bytes** (198.5%). That outline is not under 85%, so describe returns the 5,942-byte body.
  - Read-only check of the 106 eligible skills larger than 4 KiB, out of 160. With the previous English-only markers and no preamble, the outline saved 77.0% of response bytes in total (median 75.8% per skill). With the expanded markers and the full preamble, it saves **62.3% in total** and **69.3% at the median**. The median is the "about 70%" estimate. The total is lower because long governance sections weigh more than a typical skill. 93 large skills had no governance section under the old markers; 61 still have none. `anthropic:skill-creator` has a 1,978-byte preamble and `juan:informe-marketing` a 1,864-byte one; both are copied whole.
