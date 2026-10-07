# Discovery publication profile

`solar client sync profile show` previews the current profile.
`solar client sync profile set discovery --codex-only --dry-run` checks and previews without
writing. `set discovery --codex-only [--essential ID]` saves `agents_skill_profile` through
the canonical `solar_client_write_settings_v12` atomic writer, refreshing
Client identity and removing stale portable keys. Portable-mode profile changes
refuse rather than silently converting the workspace. It does not publish: run `solar client sync --codex-only` next.
Each set replaces the optional essential list; mandatory entries are always
solar-mcp, solar-client and solar-paths. Unknown/excluded essentials refuse.
`set native` then sync restores full publication without requiring MCP.

`client_profile.py` implements these commands. `skill_inventory.py` is the
shared scanner imported by sync and MCP; its CLI emits the publication index.
These are internal Client modules; use the Client entrypoint to change settings.

Before discovery-mode publication, Client reads the actual Codex user MCP
registration (honoring CODEX_HOME), validates its workspace environment, starts
that registered stdio command and probes tools/list with a ten-second timeout.
The registration is trusted local configuration. Search/Describe must both be
present. Missing registration refuses before pruning the catalog. The probe
checks registration and tool presence; it does not prove harness invocation or
validate every query. Existing exclusions and ownership rules still apply.

Discovery currently supports Codex only. `.agents` is shared with Antigravity,
whose MCP registration is unsupported. Set requires `--codex-only` and prints
an explicit shared-surface warning. Every sync including Antigravity refuses
before any publication or pruning; use `--codex-only` or restore native. Do not
open this workspace in Antigravity while reduced exposure is active. Other
client destinations keep full eligible publication when synced individually.
Only `.solar-managed` resources can be pruned. Unmanaged essential collisions
refuse rather than silently omitting the bootstrap. Unsafe individual sources
warn and skip in both sync and discovery; valid packages remain available.

The report measures UTF-8 bytes of IDs and full frontmatter descriptions.
It excludes tool schemas, harness formatting, prompts, turns and selected
bodies. It is neither a tokenizer nor proof of billed savings. Compare fresh
sessions on the same tasks before rollout. The maintainer sets and accepts
baseline-derived latency/cost targets independently of implementation.


## Baseline and required fresh-session experiment

Read-only baseline on 2026-10-07: **160 eligible packages, 68,386 UTF-8 bytes**
(ID plus full description, approximately 427 per package). An in-memory preview
of three mandatory essentials gives **823 bytes**; it neither activates the
profile nor verifies the real harness. At four bytes/token the full catalog is
roughly 17,000 tokens, an illustrative conversion rather than tokenizer data.

| Measurement | Full fresh Codex session | Reduced fresh Codex session |
|---|---|---|
| Eligible inventory bytes | 68,386 (source measurement) | 68,386 (same sources) |
| Initial publication preview bytes | 68,386 | 823 (three essentials) |
| Actual initial harness catalog/tokens | unknown | unknown |
| Input / cached / output tokens | unknown | unknown |
| Calls / latency / billed cost | unknown | unknown |
| Selection success / task completion | unknown | unknown |

The framework maintainer fixes the task set and latency/cost acceptance targets
before comparison. In an isolated workspace and installed candidate, register
its Solar MCP and publish native, then start a genuinely fresh Codex session.
Use one exact-ID task, one natural-language discovery task and one transversal
task requiring a reference and deterministic local work. Record the requested
artifact and completion outcome, initial catalog, selected reads, calls, elapsed
time and available provider metrics without recording private content. Close
the session; use Client's dry-run then Codex-only discovery publication and a
fresh session on the same tasks, model, instructions and essentials. Restore
native after the comparison and verify normal invocation in another session.
Keep cold/warm cache conditions comparable and record any unavailable metric
as unknown. Tool schemas, prompts, selected bodies and extra calls must count
in the comparison. Do not infer billed savings from byte reduction alone.

This experiment has not been run; passing isolated tests does not complete it.
