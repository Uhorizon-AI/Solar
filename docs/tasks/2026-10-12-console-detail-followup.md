# Task spec: console task detail follow-up

**Triage level:** standard
**Date:** 2026-10-12
**Status:** pending_review

Follow-up to `docs/tasks/2026-10-12-console-task-context.md` (merged in v0.40.0). It fixes minor findings from the final reviews and changes no public contract.

## Objective

Close the remaining small gaps in the console task detail: link authority validation, one missing field, shape checks in the page, and a visible destination for the 503 warning.

## Scope

- `core/skills/solar-app/scripts/task_markdown.py`: port range 1 to 65535; bracketed IPv6 with optional port is a valid host; internationalized (non-ASCII) hosts are not linked. Decision: do not punycode-encode them. Encoding would show a link whose visible host differs from the real one (look-alike hosts), so the limitation is documented in the skill under "Not supported, by design"; the punycode form typed by the author is a normal link.
- `core/skills/solar-app/assets/app.js`: show `workspace_id` (English and Spanish); read `context` and `configuration` only when they are plain objects.
- `core/skills/solar-app/scripts/host_server.py`: `configure_logging()` at start. Finding: the host silenced request logs and configured no logging, so the `solar.app` warning would only reach Python's last-resort handler. A single idempotent stderr handler is added, matching how the host already reports errors.
- `core/skills/solar-app/SKILL.md`, `CHANGELOG.md` (Unreleased, Fixed).
- Tests: `core/tests/skills/solar-app/test_task_detail.py`, `test_console_ui.py`.

Out of scope: MCP, solar-state, the reports and channels change, uppercase port notation (no change needed: ports are digits).

## Decision: shared frontmatter decoding helper (left as debt)

`console_task_detail` decodes the frontmatter in three lines from the raw row, tolerating undecodable JSON. `console_tasks` does not decode frontmatter at all (it reads columns), and `solar_state._task_dict` is strict by contract. A shared tolerant helper would add public API to solar-state for one caller and touch a module this follow-up otherwise does not need. Revisit if a second tolerant caller appears.

## Acceptance criteria

- [x] `:0`, `:99999`, `:65536` are not links; `:1`, `:65535`, `[::1]`, `[2001:db8::1]:8080` are.
- [x] `https://münchen.de` stays text; a test pins it.
- [x] `workspace_id` appears in both languages.
- [x] `context: []`, `configuration: "x"` and similar shapes leave the block, the history and the note intact.
- [x] The 503 warning reaches stderr with the exception class only; a test pins it.

## Checks to run

```bash
uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider
node --check core/skills/solar-app/assets/app.js
python3 -m py_compile <changed .py files>
git diff --check
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/<skill> <dir outside repo>
```

## Completion evidence

- From the repository root: `uv run --project core/tests pytest core/tests/skills/solar-app core/tests/skills/solar-state core/tests/skills/solar-mcp -q -p no:cacheprovider` -> 551 passed (loopback port available). Without `ps` and a writable `$HOME`, three tests (`test_cutover`, two in `test_mcp_cli`) cannot run and the count is 548.
- `node --check`, `py_compile` of the four changed Python files and `git diff --check`: passed. solar-app, solar-state and solar-mcp validated and packaged outside the repository.
- Not verified: installed acceptance (no install or sync performed).
