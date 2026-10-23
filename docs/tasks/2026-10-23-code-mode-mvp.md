# Task spec: isolated Code Mode evaluation

**Triage level:** standard
**Date:** 2026-10-23
**Status:** completed (experimental implementation; adoption undecided)

## Objective

Make the search + execute(code) mechanism reviewable before deciding whether to integrate it into Solar.

## Scope

- Add a standalone synthetic MCP experiment under `core/experiments/code-mode/`, tests and an evaluation guide.
- No changes to the production MCP, registry, gates, task profiles, scheduler, installed clients or credentials.
- No AI-provider launches or real customer data. No merge, deployment or release.

## Acceptance criteria

- Search exposes typed read-only fixture methods and closed input schemas.
- Execute runs generated JavaScript in a restricted subprocess/worker with host-validated RPC.
- Return a compact summary and host-recorded trace; reject host access, invalid arguments and budget overruns.
- Demonstrate a real stdio MCP search/execute flow and compare response bytes with direct calls.
- Explain limitations, adoption costs, and why this does not replace the task machinery behind ask.

## Checks to run

The core governance permits framework scripts and pytest in the centralized test project.

```bash
uv run --project core/tests pytest core/tests/experiments/test_code_mode.py -q
python3 core/experiments/code-mode/demo.py
```

## References

- Repository policy: `CONTRIBUTING.md`, `core/AGENTS.md`.
- Issue: https://github.com/Uhorizon-AI/Solar/issues/67
- User authorized an MVP and draft PR to evaluate adoption; installation is outside scope.

## Completion evidence

- `uv run --project core/tests pytest core/tests/experiments/test_code_mode.py -q`: 23 passed on Python 3.14.8 and Deno 2.9.6.
- `python3 core/experiments/code-mode/demo.py`: correct summary; direct fixture responses 4,740 bytes, Code Mode response including trace 307 bytes.
- Negative tests cover file, environment, network, subprocess and remote-import access, invalid RPC arguments, forged unknown method calls, infinite loops and call/output budgets.
- Initial test run exposed cleanup of an already-exited process group; cleanup now targets the owned Deno process, whose workers are threads and whose subprocess permission is denied.
- A read-only agent review found malformed-params handling and console/protocol mixing; both were fixed with regression tests. Independent provider reviews and real LLM/client usage are not performed. No production integration or deployment is claimed.
