# CLI client limitations for Solar questions

**Scope:** Solar framework — asynchronous questions (`ask_readonly_v1`) and how
they relate to host CLI harnesses (Claude Code, Cursor Agent, Codex, Antigravity).
**Purpose:** State what Solar does and does not control about model input size,
so operators do not attribute opaque CLI context to the Solar envelope.
**Investigation:** [Uhorizon-AI/Solar#80](https://github.com/Uhorizon-AI/Solar/issues/80).

Related: [token budget protocol](token-budget-protocol.md),
[token usage for asks](task-token-usage.md),
[questions in repository-readonly-review](repository-readonly-review.md#questions-ask_readonly_v1).

---

## What Solar does not do by default

Solar does **not** strip or replace the user's CLI session for ordinary questions.

- `ask_readonly_v1` launches the selected provider with the caller's environment
  (HOME, config, MCP catalogs, plugins, hooks) and asks for that client's native
  read-only mode. It does not enforce isolation.
- Solar does not remove MCP servers, skills catalogs, or vendor tool schemas from
  the user's default CLI configuration.
- Sandbox / plan / ask modes are **permission** requests. They are not a promise
  of smaller prompts (`sandbox ≠ tokens`).

Restricted profiles (`text_only_review_v1`, `repository_readonly_v1`) isolate for
reviews. That isolation is **not** the default ask path.

---

## Ask envelope vs CLI ambient context

| Layer | Role in a minimal ask |
|---|---|
| Solar ask envelope | Prompt + absolute start folder (+ optional model). On the order of hundreds of bytes. `system_prompt` empty. |
| Provider CLI harness | System instructions, tool/MCP schemas, project rules (`AGENTS.md` / `CLAUDE.md`), advertised skills, plugins, session defaults. |

**Measured result (#80):** for Cursor, Codex, Antigravity and Claude,
`ask_readonly_v1` ≈ the same CLI invoked directly in the same folder (delta ≈ 0
within noise). Solar does not inflate the first request beyond the CLI.

---

## Measured floors (minimal “PRUEBA TOKENS OK” class prompts)

Figures are provider-reported attempt counters from controlled runs in October 2026.
Claude reports tiny `input_tokens` with large cache fields; **effective** below means
`input + cache_read + cache_creation` for that client. Other clients use their
reported input token field. Do not treat rows as billing quotes.

| Client | Empty / isolated floor | Ask or project cwd (default session) | Notes |
|---|---:|---:|---|
| Cursor (`agent`) | ~8.4k | ~12.6k | Post-hygiene (no duplicate `.cursorrules`; reduced synced skills). |
| Codex | ~16.4k (~13.7k strongly isolated) | ~22–25k | Workspace `.codex` trim can shave ~2–3k; not the floor. |
| Antigravity (`agy`) | ~9.3k | ~17.1k | Private-HOME lite auth may fail closed. |
| Claude Code | ~24.8k effective | ~32–35k effective | Default session is the heaviest floor. |

**Claude lite-style launch** (restricted flags, empty tools/MCP, empty setting
sources — same family as review isolation, not default ask): ~**5.7k** effective
on a minimal prompt. That path is the only well-documented tool-catalog strip
among the four CLIs.

**AGENTS.md alone** (Cursor, empty cwd vs cwd with only that file): ~**+2k**.
It does not auto-inject `MEMORY.md` / profile when the prompt forbids tools.
**Skill-catalog hygiene** (large sync excludes): on the order of **~1.6–3k** on
Cursor/Codex project asks — useful, not the dominant floor.

---

## Hygiene vs harness

| Lever | Typical effect | Enough for “cheap hello”? |
|---|---|---|
| Remove duplicate project rules (e.g. `.cursorrules` ≡ `AGENTS.md`) | ~1–2k on Cursor | Partial |
| Shrink always-on synced skill catalogs | ~1.6–3k | Partial; diminishing returns |
| Trim workspace Codex apps/plugins | ~2–3k observed | Partial |
| Expect Solar envelope trim | ~0 | No |
| Expect sandbox flags to cut tokens | ~0 | No |

The residual after hygiene is mostly **opaque CLI harness cost** (tools, system,
vendor defaults). Solar cannot remove that without an explicit isolated profile.

---

## Gaps

- **Cursor / Codex:** no documented first-class “lite ask” that empties tool/MCP
  catalogs the way Claude’s restricted + empty `--tools` / `--mcp-config` can.
  Private HOME / `--ignore-rules` alone did not match Claude’s lite savings.
- **Claude:** composable flags exist; default ask remains expensive without them.
- **Antigravity:** review-style private HOME can fail authentication; treat as
  fail-closed until credential copy is proven.

---

## Operator policy (until product tiers ship)

1. **Trivial asks** (“hello”, smoke OK): prefer **Cursor** (~12.6k project ask) —
   lowest default among the four.
2. Avoid **Codex** or **Claude default** for trivial asks when cost matters.
3. When an opt-in **`ask_lite_v1`** (or equivalent) is available: prefer **Claude
   lite** for cheap isolated questions (acceptance target on the order of ≤~6k
   effective vs ~25–35k default). Other providers may expose the same profile
   contract with weaker measured savings — do not assume Claude’s delta.
4. Keep `ask_readonly_v1` as the **full-session** default (user MCP/skills intact).

---

## Follow-ups (out of scope for #80)

| Item | Status |
|---|---|
| Ship opt-in `ask_lite_v1` (success metric: Claude lite vs default) | Follow-up issue / PR |
| Product tiers: Fast classify / Low-context (lite) / Full (`ask_readonly`) | Backlog design |
| Fast tier via direct API / NexIA | **Deferred** — not in current delivery |

#80 closes as the **investigation** of overhead attribution. Implementation of
lite and tiers is tracked separately.

---

## Governance

Owned by `core/`. Update this document when a new provider is verified for asks
or when a measured floor changes by a material amount after a harness release.
Do not treat this file as a substitute for `ask_readonly_v1` contracts in
[repository-readonly-review.md](repository-readonly-review.md).
