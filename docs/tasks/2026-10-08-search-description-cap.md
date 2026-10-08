# Task spec: search description cap

**Triage level:** standard
**Date:** 2026-10-08
**Status:** completed

## Objective

Cut capability-search payloads so a query returns a short description and never fails just because the caller asked for more than ten hits.

## Scope

- Files to modify: `core/skills/solar-mcp/scripts/capability_registry.py`, `core/skills/solar-mcp/references/discovery.md`, `core/tests/skills/solar-mcp/test_discovery.py`, `core/docs/capability-discovery-design.md` (search contract row), `CHANGELOG.md`, this task spec
- Files explicitly out of scope: `describe` behavior, `mcp_server.py` tool schemas, Client profiles, the installed runtime, `~/.codex`, `solar client update`, `solar client sync`, release, push

## Acceptance criteria

- [x] Each search description is at most 120 characters, cut on a word boundary, with `…` only when the text was cut
- [x] `limit` still defaults to 5; a value above 10 is applied as 10 and the response sets `limit_capped`; a value below 1 or a non-integer is refused
- [x] The 8 KiB result cap, exact-id ranking, `revision`, and `truncated` stay in place
- [x] Tests cover the clip, the default limit, the cap, unchanged exact-id ranking, and a before/after byte comparison on a 30-skill fixture
- [x] `CHANGELOG.md` records the change under Unreleased

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-mcp -q
uv run --project core/tests pytest core/tests/skills/solar-client -q
```

## References

- Repo policy: `CONTRIBUTING.md`
- RFC or context doc: `core/docs/capability-discovery-design.md`, `core/skills/solar-mcp/references/discovery.md`

## Implementation notes (optional)

- The ellipsis counts toward the 120 characters. A token with no whitespace inside that budget is cut at 119 characters.
- `limit_capped` is present only when the caller asked for more than 10. `truncated` still means the 8 KiB cap dropped a hit.
- The byte comparison serializes all 30 fixture matches in the search result shape, once with the previous 400-character slice and once with the new clip, so the delta is the description cut and not the page size.

## Completion evidence (optional)

- Validation:
  - `uv run --project core/tests pytest core/tests/skills/solar-mcp -q` -> 110 passed
  - `uv run --project core/tests pytest core/tests/skills/solar-client -q` -> 9 passed
- Files changed:
  - `core/skills/solar-mcp/scripts/capability_registry.py`
  - `core/skills/solar-mcp/references/discovery.md`
  - `core/docs/capability-discovery-design.md`
  - `core/tests/skills/solar-mcp/test_discovery.py`
  - `CHANGELOG.md`
- Notes:
  - Byte comparison, 30 synthetic skills, search-result JSON (`indent=2`, `sort_keys=True`): **before 21,223 bytes** (descriptions sliced at 400 characters) **after 12,853 bytes** (120-character word clip). Saved 8,370 bytes on that fixture. A live `search(..., limit=30)` returns 10 rows, `limit_capped: true`, and every description ends with `…`.
