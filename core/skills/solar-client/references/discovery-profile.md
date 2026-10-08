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


## Experiment record: the reduced profile did not lower session cost

**Outcome (2026-10-09): closed.** The reduced profile stays an opt-in option,
not enabled, with `native` as the default. It is not extended to other clients.
The experiment was run and it did not show a saving; this section records it so
the same path is not repeated without a new hypothesis.

Read-only baseline on 2026-10-07: **160 eligible packages, 68,386 UTF-8 bytes**
(ID plus full description, approximately 427 per package); three mandatory
essentials give **823 bytes**. At four bytes/token the full list would be
roughly 17,000 tokens. That conversion overstated the saving: the harness does
not announce full descriptions.

Measured in fresh Codex sessions from the session log (`token_count` events),
same task set, same folder (`~/Solar`), reduced profile against full catalog:

| Round | Change under test | Total input | Uncached input |
|---|---|---|---|
| 1 | Discovery profile (search and describe as first built) | +24 % | +33 % |
| 2 | Same, five tasks | -14 % | -28 % |
| 3 | Shorter search results, describe outline (0.34.0) | -10 % | +13 % |
| 4 | Describe discourages `full=true` (0.34.1) | **+20 %** | **+68 %** |
| Mean | | about +5 % | about +22 % |

One session per mode and round, one model, one client, no billing comparison.

What held in every round: the reduced catalog saves about **4,200 tokens per
request** (about 12 % of the first request: 35,065 against 30,879 in round 4).

What the follow-up changes achieved: round 4 had `full=true` on 0 of 6
`describe` calls, against 3 of 3 before; the model used the outline. The change
worked as designed and did not change the result.

**Why.** Without the names in the catalog the model takes more steps to find and
read each skill (16 requests against 13 in round 4), and every request resends
the whole context. That cost exceeds the catalog saving. Shorter `search` and
`describe` outputs reduced bytes per call, not the number of steps.

**What stays useful.** Inside a planet (its own git repository) Codex does not
see Solar skills in its catalog, with or without the profile; the MCP search is
the only way to find them, across all planets.

**To reopen it**, start from a hypothesis about the number of steps, not the
size of the catalog, and measure this way:

- Read tokens and tool calls from the session log. The model's own report of its
  calls was wrong in several rounds.
- Check the working folder in the log before interpreting a pair. One round ran
  inside a planet by mistake, so both sessions had the same visible catalog.
- Repeat each mode several times. The total changed sign between rounds.
- Judge the total of the session, not the catalog bytes. Keep cold and warm
  cache conditions comparable and count tool schemas, prompts, selected reads
  and extra calls.
