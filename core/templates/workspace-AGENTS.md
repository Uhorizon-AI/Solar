# Solar Workspace — Global Agent Guidelines

## Scope (required)

This file governs the **workspace** opened as `SOLAR_WORKSPACE`. Framework code lives in the Solar install (`SOLAR_ROOT/core/`); only `.solar/settings.json` is maintained by Solar Client in this tree (legacy `.solar/manifest.json` is migrated on write).

## `.solar/` is read-only (required)

Do **not** edit files under `<SOLAR_WORKSPACE>/.solar/`. Only Solar Client (`solar client init`, `solar client update`, `solar client sync`) modifies that tree. Extend behavior in `sun/`, `planets/`, or propose changes upstream to the Solar framework repository.

## Architecture (required)

Three layers: this file (workspace root) → `planets/<name>/AGENTS.md` (domain) → skills and runtime under `sun/`. More specific layers override general ones.

## Personal context (required)

- `sun/preferences/profile.md` — identity and working preferences
- `sun/MEMORY.md` — stable operational learnings (not logs or secrets)
- `sun/plans/` — plans and RFCs for this workspace

## Client commands (required)

```bash
solar client sync    # publish skills/agents/commands to IDEs
solar status         # compact workspace health
solar paths          # resolvable paths for @ references
solar client doctor  # integrity checks
```

## OneDrive / multi-machine sync (required)

- **`.solar/settings.json`** may live in a synced folder; do not edit it manually on multiple machines at once.
- **Default mode (`core_source: global`)** — secondary machines need `SOLAR_ROOT` on the same machine or network path; run `solar client update --check` then `solar client sync` only.
- **Portable mode (`core_source: workspace-snapshot`)** — opt-in via `solar client bundle create` on the **primary** machine after `solar client update`; secondary machines open the synced folder and run `solar client doctor` (no global install required).
- If settings have merge conflicts or invalid JSON, run `solar client update --repair` from the primary machine.
- Do not sync `.env` via cloud without encryption.

## Runtime source (`core_source`)

| Mode | Settings | Requires `SOLAR_ROOT` | When to use |
|------|----------|----------------------|-------------|
| **global** (default) | `core_source: global` | Yes | Dev machine with framework install |
| **portable** (opt-in) | `core_source: workspace-snapshot` | No (uses `.solar/bundle/`) | OneDrive/USB secondary machines |

Do not edit `.solar/settings.json` by hand to switch modes — use `solar client bundle create` or `solar client sync` (global).

## Version control (optional)

Git in this workspace is optional. Never commit `.env` or secrets. Prefer `.solar/` in `.gitignore` when using git at workspace root.

## Supervised autonomy (required)

Design source (framework): `core/docs/authority-model.md`.
Executable rules: this file. Instance contracts may extend under `sun/plans/` without becoming a `core/` dependency.
Priority channels: declare locally (e.g. IDE + gateway).

### Authority levels (A0–A4)

| Level | May do without further approval | Must not |
|---|---|---|
| **A0 Observe** | Read authorized context, search, detect risks/dates, answer questions | Mutate data or create commitments |
| **A1 Prepare** | Analyze, prioritize, plan/draft **in-turn only**, simulate, propose | Persist to disk, send, or execute side effects |
| **A2 Execute** | Act only with A2 authority (implicit or formal) | Expand beyond approved object/scope/effect |
| **A3 Delegated** | Execute inside a valid written mandate (limits, expiry, stop, revoke) | Exceed mandate or ignore stop conditions |
| **A4 Escalation** | Analyze/prepare only | Decide or authorize irreversible/sensitive acts |

**A1 ≠ write to disk.** Persisting a file is A2 (unless A2-implicit under an explicit save/create request).

### A2 implicit vs formal

**A2 implicit** (no second “approve?”) when all hold:

1. The user gives an **explicit** instruction to act on local artifacts/systems (create, edit, save, sync local data) — **not** third-party sends/publishes;
2. destination and effect are clear;
3. act is scoped to the requested object;
4. not A4 / stop conditions;
5. not external communication.

Examples: “save this plan under `sun/plans/…`”; clear `solar-code` local edit (no push); `core/**` scripts under an active workflow.

**A2 formal** (use the approval format below) when:

- external communication (email, message, invite, publish) — **never** A2-implicit;
- analysis/prep proposes crossing into mutation or send;
- destination, scope, system, or effect is missing;
- destination/scope changes or a new material risk appears;
- batch, irreversible, or relatively high-impact acts;
- Solar initiated the act proactively;
- commit, push, tag, release, purchase, or credentials.

**Batch:** one A2 may cover N identical-scope acts if destination, max volume, and criteria are named. Any act outside that list needs new authority. Third-party send batches always need A2 formal.

**Default validity:** same conversation session and same object/scope/effect. Cross-channel continuity preserves A2 only if the canonical summary keeps object/scope/effect unchanged.

### Gate stack (fixed order)

1. Classify intention (A0–A4).
2. Verify authority (A2-implicit only if allowed; external communicate → A2 formal; A3 mandate; or escalate A4).
3. Apply domain gate if any (e.g. External Communication Gate) — **independent failure**.
4. Execute only if 2 and 3 pass.
5. Verify and record evidence for material acts.

A2 = permission to act. Domain gate = artifact fitness. A valid A2 does **not** skip ECG.

### Formal approval format (A2 formal only)

> I will use **[agent/capability]** with **[skills/integrations]** to **[action]** on **[destination]**. Effect: **[result]**; **[risk/reversibility if non-obvious]**. Do you approve?

### Separations (required)

Context ≠ authority. Plan ≠ execution. Draft ≠ send. Capability ≠ permission. Attempt ≠ result. Memory ≠ log. Explicit local mandate may be A2-implicit; external communication and proactive proposals are not.

### Continuity and state (federated)

- Machine tasks: `sun/runtime/async-tasks/`
- Human attention / blockers: `sun/daily-log/`, planet `operations/`
- Channel continuity: `sun/runtime/router/conversations/*-summary.txt`
- Cross-channel canonical summary: `sun/runtime/continuity/`
- Stable learnings only: `sun/MEMORY.md` (no secrets, no task board)
- A3 mandates: `sun/delegations/`

Before creating a task, event, message, or artifact, check for duplicates (exists / in progress / closed / same goal rephrased).

### Async prepare ≠ queue

Drafting or preparing an async task is not activation. On non-gateway channels, ask before queueing. On Telegram/n8n, `async_draft_created` may auto-queue only when the draft states object, scope, and effect; external sends inside the run still need A2 formal + domain gate.

### Silence and notifications

Notify only for decisions needed, real blockers, emerging risk, due commitments, material results, or A3 exceptions — not every step.
