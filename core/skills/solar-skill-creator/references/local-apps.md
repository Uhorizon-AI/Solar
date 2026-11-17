# Skills That Ship a Local App

Use this when a skill includes a small local web app (a dashboard, a triage page, a review UI). The app is a view over the skill's logic, never the home of it.

## Where each thing lives

| Thing | Location |
|---|---|
| Business logic, rules, calculations, queries | `scripts/` of the skill (importable modules, no server code) |
| Data and state (databases, decisions, caches) | The workspace data directory of the owning domain, never inside the skill |
| Server and its page | Exception: a thin entrypoint that only parses requests, calls the skill's modules and renders. Document it in `SKILL.md`; no rules or calculations in it |
| Tests | Outside the skill, following the host's convention (core: `core/tests/skills/<skill>/`; planets: the planet's documented test path) |

Decision rule: if a rule could be reused by a script, another agent or a test without starting the server, it belongs in `scripts/`. If it lives only in the server file, it is untestable and will drift.

## Safe defaults

- Read-only by default. Add a write endpoint only for a named, documented effect.
- Bind to `127.0.0.1` only. Never `0.0.0.0`, never a public tunnel by default.
- Check that `Host` is loopback on every request.
- Every write also requires: loopback `Origin`, `Content-Type: application/json`, and a per-process token generated at startup and served only with the page (`Cache-Control: no-store`).
- No CORS headers.
- Logs must not contain names, URLs, message text or notes.
- Never write secrets or personal data into the skill folder; skills are synced to clients.

## Documenting it in `SKILL.md`

Keep it to a short subsection, with detail in `references/`:
- the command to start the server and its port,
- which endpoints are read-only and which write, and what each write changes,
- where the data lives,
- which module in `scripts/` holds the logic each screen uses.

If the app stays up as a long-running service, add the `Laptop runtime note (optional)` required in `SKILL.md`. Do not restate it here.

## Tests

- Test the `scripts/` logic directly; test the server only for its guards (origin, token, read-only paths).
- Register every test file in the skill's runner so the host's full-suite command runs it.
- Tests must use a temporary database or fixtures, never real data.

## After changing the skill

- Run `solar client sync` when skills, agents or commands changed, and check the synced client folders.
- Validate with `package_skill.py` as described in `SKILL.md`.

## Final checklist

1. No business rule lives in the server file or in the data directory.
2. The data directory holds only data and state; the skill holds no data.
3. Read-only by default; each write endpoint is documented and guarded.
4. Binds to `127.0.0.1`, no CORS, loopback `Host` always, token and `Origin` checks on writes.
5. `SKILL.md` documents start command, endpoints, data location and logic modules.
6. Tests live outside the skill, are registered in the runner and pass.
7. Skill validated and synced.
