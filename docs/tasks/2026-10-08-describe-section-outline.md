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

- [x] `describe(id, revision?, reference?, section?, full?)` returns a heading outline for a unit larger than 4 KiB: id, description, revision, level-2 and level-3 titles with byte sizes, registered references, and governance sections copied in full
- [x] A unit of 4 KiB or less returns the complete body, as before
- [x] `section` returns only that exact heading; a missing title errors with the title list; `full=true` returns the complete body, including the existing 64 KiB response limit
- [x] Governance is a case-insensitive substring of the heading: `authority`, `gate`, `governance`, `safety`, `never`, `approval`. Text is an original slice, never a summary. Gates are not dropped to save space
- [x] `section` and `reference` do not accept paths. Revision and containment checks stay in place
- [x] Tests cover a large outline, a present and a missing section, `full=true`, governance text, a small skill, and the outline-versus-body byte comparison. The seven existing tool wire tests stay green
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

## Completion evidence (optional)

- Validation:
  - `uv run --project core/tests pytest core/tests/skills/solar-mcp -q` -> 114 passed
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
  - Byte comparison on the large fixture, response JSON (`indent=2`, `sort_keys=True`): **outline 1,414 bytes**, **complete body 6,120 bytes**. Saved 4,706 bytes. The outline includes the approval-gate and "Never rewrite" slices in full and omits the ordinary notes body. A fenced `## Approval gate` is not treated as governance.
