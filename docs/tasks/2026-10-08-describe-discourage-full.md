# Task spec: discourage full on capability describe

**Triage level:** standard
**Date:** 2026-10-08
**Status:** completed

## Objective

Parameter names, types, and defaults stay unchanged. The 85% threshold includes `usage`, so an outline that was just under that line can now return the complete body.

## Scope

- Files to modify: `core/skills/solar-mcp/scripts/mcp_server.py`, `core/skills/solar-mcp/scripts/capability_registry.py`, `core/skills/solar-mcp/references/discovery.md`, `core/docs/capability-discovery-design.md` (describe contract row), `core/tests/skills/solar-mcp/test_server_wire.py`, `core/tests/skills/solar-mcp/test_discovery.py`, `CHANGELOG.md`, this task spec
- Files explicitly out of scope: search, the seven earlier tools, parameter names, types, and defaults, Client profiles, the installed runtime, `~/.codex`, `solar client update`, `solar client sync`, release, push

## Acceptance criteria

- [x] The `solar_capability_describe` tool text tells the caller that a skill over 4 KiB returns an outline by default, to ask next with `section="<exact title>"`, and to use `full=true` only when that outline is not enough because it costs many more tokens. Skills of 4 KiB or less stay complete
- [x] `section`, `full`, `reference`, and `revision` each have a property description. Names, types, and defaults are unchanged
- [x] An outline response includes a fixed `usage` hint of at most 200 characters. Complete-body and section responses omit it. The 85% comparison counts `usage` as part of the outline. Governance sections and the preamble are still copied whole
- [x] Search and the seven earlier tools are unchanged
- [x] `CHANGELOG.md` records the change under Unreleased
- [x] `references/discovery.md` states what `usage` is, when it appears, and that it counts in the 85% comparison. The measurement stays in this task spec

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-mcp -q
uv run --project core/tests pytest core/tests/skills/solar-client -q
```

## References

- Repo policy: `CONTRIBUTING.md`
- RFC or context doc: `core/docs/capability-discovery-design.md`, `core/skills/solar-mcp/references/discovery.md`
- Previous delivery: `docs/tasks/2026-10-08-describe-section-outline.md`

## Implementation notes (optional)

- Measured on the reduced profile: the model called `solar_capability_describe` with `full=true` on 3 of 3 calls in the last session. That returns the complete body, so the outline saved nothing on those calls. Without `full=true` the outline already works. The previous tool text presented `full` as an ordinary option ("full returns the complete unit"). A repeat on Codex is still pending. This change does not claim that `full=true` calls will fall.
- `usage` is the fixed sentence "Read only the sections you need with section=<title>; use full=true only if this outline is not enough." It is 103 characters and is added only to the outline dict, before the 85% check.
- The field adds 118 bytes to outline response JSON (`indent=2`, `sort_keys=True`). Large fixture: outline 1,592 bytes, complete body 6,120 bytes. Spanish fixture: outline 1,365 bytes, complete body 5,013 bytes. The heavy-rules outline is 11,910 bytes, 200.4% of its 5,942-byte body, so describe still returns the body.
- Boundary fixture (`example:edge`, 4,735 ordinary notes): outline without `usage` is 6,827 bytes, under 85% of the 8,170-byte body. With `usage` it is 6,945 bytes, which is not under 85%, so describe returns the complete body.

## Completion evidence (optional)

- Validation:
  - `uv run --project core/tests pytest core/tests/skills/solar-mcp -q` -> 119 passed, re-run after the review fixes
  - `uv run --project core/tests pytest core/tests/skills/solar-client -q` -> 9 passed on the previous commit. This follow-up does not touch solar-client
- Files changed:
  - `core/skills/solar-mcp/scripts/mcp_server.py`
  - `core/skills/solar-mcp/scripts/capability_registry.py`
  - `core/skills/solar-mcp/references/discovery.md`
  - `core/docs/capability-discovery-design.md`
  - `core/tests/skills/solar-mcp/test_server_wire.py`
  - `core/tests/skills/solar-mcp/test_discovery.py`
  - `CHANGELOG.md`
- Notes:
  - No parameter name, type, or default changed. Search and the seven earlier tools were not edited. The installed runtime, `~/.codex`, and Client profiles were not touched. No `solar client update`, `solar client sync`, push, or release.
