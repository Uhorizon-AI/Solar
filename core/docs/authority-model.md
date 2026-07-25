# Supervised Autonomy — Authority Model (A0–A4)

Fail-closed primitives for Solar workspaces. Framework reference for multi-user reuse.

**Product boundary:** these primitives are **universal** (`core/`). Solar’s public identity remains an AI operating system for multi-agent workflows; supervised autonomy is governance, not a product rename.

Executable rules live in the workspace root `AGENTS.md` (Supervised autonomy). This document is the design source in `core/`. Instance-specific operating contracts may extend it under `sun/plans/` without becoming a dependency of framework code.

---

## Authority levels (A0–A4)

| Level | May do without further approval | Must not |
|---|---|---|
| **A0 Observe** | Read authorized context, search, detect risks/dates, answer questions | Mutate data or create commitments |
| **A1 Prepare** | Analyze, prioritize, plan/draft **in-turn only**, simulate, propose | Persist to disk, send, or execute side effects |
| **A2 Execute** | Act only with A2 authority (implicit or formal) | Expand beyond approved object/scope/effect |
| **A3 Delegated** | Execute inside a valid written mandate (limits, expiry, stop, revoke) | Exceed mandate or ignore stop conditions |
| **A4 Escalation** | Analyze/prepare only | Decide or authorize irreversible/sensitive acts |

**A1 ≠ write to disk.** Persisting a file is A2 (unless A2-implicit under an explicit save/create request).

---

## Gate stack (fixed order)

1. Classify intention (A0–A4).
2. Verify authority (A2-implicit only if allowed; external communicate → A2 formal; A3 mandate; or escalate A4).
3. Apply domain gate if any (e.g. External Communication Gate) — **independent failure**.
4. Execute only if 2 and 3 pass.
5. Verify and record evidence for material acts.

**A2 = permission to act. Domain gate = artifact fitness.** A valid A2 does **not** skip a domain gate.

---

## A2 implicit vs formal

### A2 implicit

No second “approve?” when **all** hold:

1. The user gives an **explicit** instruction to act on local artifacts/systems (create, edit, save, sync local data) — **not** third-party sends/publishes;
2. destination and effect are clear;
3. act is scoped to the requested object;
4. not A4 / stop conditions;
5. not external communication.

Examples: “save this plan under `sun/plans/…`”; clear `solar-code` local edit (no push); `core/**` scripts under an active workflow.

### A2 formal

Always for third-party communication. Also when:

- analysis/prep proposes crossing into mutation or send;
- destination, scope, system, or effect is missing;
- destination/scope changes or a new material risk appears;
- batch, irreversible, or relatively high-impact acts;
- Solar initiated the act proactively;
- commit, push, tag, release, purchase, or credentials.

**Batch:** one A2 may cover N identical-scope acts if destination, max volume, and criteria are named. Third-party send batches always need A2 formal.

**Default validity:** same conversation session and same object/scope/effect. Cross-channel continuity preserves A2 only if the canonical summary keeps object/scope/effect unchanged.

### Formal approval format

> I will use **[agent/capability]** with **[skills/integrations]** to **[action]** on **[destination]**. Effect: **[result]**; **[risk/reversibility if non-obvious]**. Do you approve?

---

## Separations (required)

Context ≠ authority. Plan ≠ execution. Draft ≠ send. Capability ≠ permission. Attempt ≠ result. Memory ≠ log. Explicit local mandate may be A2-implicit; external communication and proactive proposals are not.

---

## A3 mandate — minimum schema

Recurring delegated autonomy requires a readable, auditable mandate (typically under `sun/delegations/`). Minimum fields:

```yaml
delegation:
  name: ""
  owner: ""
  objective: ""
  allowed_actions: []
  systems: []
  recipients: []
  excluded_data: []
  limits:
    frequency: ""
    volume: ""
    cost: ""
  approval_exceptions: []
  notify_on: []
  stop_conditions: []
  valid_from: ""
  expires_at: ""
  revoke_with: ""
  evidence_log: ""
```

Required controls: **limits**, **expiry** (`expires_at`), **stop conditions**, **revoke** mechanism. Workspaces may keep mandates in shadow until explicit activation with evidence.

**Enforcement ships with the framework:** `core/skills/solar-router/scripts/delegation_ctl.py` validates mandates, refuses mutating actions while in shadow, reserves volume under lock, records evidence, and requires real shadow evidence plus explicit owner approval to activate. See `core/skills/solar-router/references/a3-mandates.md`. Callers fail closed on non-zero exit.

---

## Async: prepare ≠ queue

Drafting or preparing an async task is not activation. On non-gateway channels, ask before queueing. On gateway channels (e.g. Telegram/n8n), auto-queue may apply only when the draft states **object, scope, and effect**; external sends inside the run still need A2 formal + domain gate.

---

## Continuity (high level)

- Prefer one canonical intention across channels; do not fork duplicate tasks for the same goal.
- Machine tasks, human attention surfaces, and channel summaries are federated state — not substitutes for MEMORY.
- Cross-channel continuity may carry A2 only if object/scope/effect are unchanged in the canonical summary.
- Before creating a task, event, message, or artifact, check for duplicates (exists / in progress / closed / same goal rephrased).

---

## Related

- Router summary: `core/skills/solar-router/references/authority-gate.md`
- A3 mandate controller: `core/skills/solar-router/references/a3-mandates.md`
- Workspace template: `core/templates/workspace-AGENTS.md`
- Async consent: `core/skills/solar-async-tasks/references/execution-consent.md`
