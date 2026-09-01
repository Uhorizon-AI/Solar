# Solar Orchestration Blueprint

How Sun turns intent into supervised work across planets, channels, and memory.

**Goal:** keep execution simple, traceable, and reusable for any workspace. Prefer composing existing primitives over inventing a new “process” skill.

There is **no** `solar-processes` skill. A process is a *shape*, not an artifact: naming a skill for that shape has no boundary and absorbs routing, state, stages, and authority. Fit new work into the four layers below instead.

---

## Four layers (fit test)

Before creating a skill, script, or mandate, ask which layer owns the need. Exactly one primary answer:

| Layer | Owns | Does not own | Home |
|---|---|---|---|
| **1. Definition** | Stages of a domain routine (what to do, in what order, with which tools) | Queue, cadence, permission, turn execution | Planet/domain skill (`SKILL.md`, scripts). Examples: `calendar-sync`, `lou-job-triage`, `linkedin-prospecting` |
| **2. State & cadence** | Deferred work, lifecycle, subtasks, recurrence, scheduled windows | Domain steps, authority, interactive turns | `solar-async-tasks` → `sun/runtime/async-tasks/` (`drafts → planned → queued → active → done/error`) |
| **3. Execution** | One turn of work: classify, route, invoke agents/skills, return a reply | Long-lived progress, domain pipeline design, written mandates | `solar-router` (interactive channels **and** `channel=async-task` for approved tasks) |
| **4. Authority** | May this act / may this routine run without the human present | How the work is done or scheduled | Workspace `AGENTS.md` A0–A4; A3 mandates in `sun/delegations/` via `solar-router/scripts/delegation_ctl.py` |

**Cross-cutting (not a fifth layer):**

- **Continuity** — canonical intention across channels: `sun/runtime/continuity/active.json` (`solar-router/scripts/continuity_cli.py`). Answers *where we are / whose turn*; never duplicates the machine queue.
- **Human attention** — blockers and commitments: `sun/daily-log/`, planet `operations/`.
- **On-demand status** — `solar-router/scripts/work_status.sh` (read-only). Periodic briefings, if wanted, are recurring async tasks — not a skill with a timer.

### Composition examples

| Need | Layers |
|---|---|
| Interactive question in IDE/Telegram | 3 (+ 4 if mutation/send) |
| Multi-step deferred job with synthesis | 1 (skill body) + 2 (task/subtasks) + 3 (router runs the task) + 4 as needed |
| Nightly calendar write | 1 (`calendar-sync`) + 2 (recurring task) + 4 (A3 mandate) — bash path may skip the LLM router |
| “Where are we?” | Continuity + `work_status.sh` (A0) |

**n8n** remains an external process engine on the same router path as Telegram. Prefer it for heavy visual pipelines; do not rebuild Airflow inside Solar.

---

## Runtime sources

- User preferences: `sun/preferences/profile.md`
- Stable learnings: `sun/MEMORY.md` (not a task board)
- Daily attention: `sun/daily-log/YYYY-MM-DD.md` — on demand or execution trace. Format: Top Priorities, Blockers, Log. See `core/templates/daily-log.md`
- Canonical intention: `sun/runtime/continuity/active.json`
- Machine queue: `sun/runtime/async-tasks/`
- A3 mandates: `sun/delegations/*.yaml` (evidence under `sun/runtime/delegations/`)
- Planet scope: `planets/<planet-name>/AGENTS.md`
- Planet memory (optional): `planets/<planet-name>/MEMORY.md`

---

## Orchestration cycle

1. **Understand** intent in one sentence; classify signal (see `solar-router/references/signal-orchestration.md`).
2. **Authority** — gate stack A0–A4 (`core/docs/authority-model.md`). Fail closed.
3. **Route** — Sun vs planet(s) using `planets/<name>/AGENTS.md` scope.
4. **Choose vehicle** — in-turn answer; async task (defer / recur / subtasks); or deterministic skill script.
5. **Execute** — interactive: router turn; deferred: queue → worker → router (`channel=async-task`); scripted: skill script with A3 `check` when mandated.
6. **Verify** — attempted ≠ done; evidence proportional to the claim.
7. **Persist** — continuity / daily-log / MEMORY / planet MEMORY as appropriate; update async task result.
8. **Reply** — brief; ask a decision only when needed (silence threshold).

---

## Routing rules

- Identity, communication style, or personal constraints → Sun.
- Domain execution → matching planet.
- Spans multiple domains → split into independent planet tasks; aggregate in Sun.
- No planet yet → pre-planet checkpoint before creation.
- Recurring delegated mutation → require a valid A3 mandate; shadow until activated with real evidence.

## Pre-planet gate (required)

Before creating a new planet, Sun must:

1. Show a short summary of captured onboarding state.
2. Show proposed planet name and objective.
3. Ask explicit confirmation.
4. Create the folder only after a clear yes.

## Planet boundary rule (required)

- Treat each `planet` as an autonomous operational context (not a department or channel).
- Create a new planet only when context boundaries justify separation: objective/KPI, stakeholders, data/processes, execution rules.
- Decision threshold: 2 criteria → evaluate split; 3+ → create.
- Do not split by channel or isolated task type; keep those inside the existing planet.

## Persistence rules

- Write only the minimum durable context.
- Do not duplicate the same fact across stores unless needed for operation.
- Continuity never lists machine work in `pending`; reference the async task id instead.
- MEMORY = stable learnings only (no secrets, no task board).
- Prefer appending new facts over rewriting history, except when correcting wrong data.

## Correction handling

- User corrections override previous values.
- Update the source file immediately.
- Continue from the latest valid state without restarting onboarding.

## Minimum quality bar

- Sun → Planet request has `objective`, `constraints`, and `context`.
- Planet → Sun response has `status`, `deliverables`, `risks`, and `next_steps`.
- Mutating / sending acts passed the authority (+ domain) gate with evidence when material.
- At least one durable write when a new durable decision appears (continuity, MEMORY, or daily-log — pick one primary).
- Output to the user is brief and actionable.

## Related

- Authority: `core/docs/authority-model.md`, `solar-router/references/authority-gate.md`
- Continuity: `solar-router/references/continuity.md`
- Signal → closed work: `solar-router/references/signal-orchestration.md`
- A3 mandates: `solar-router/references/a3-mandates.md`
- Async consent: `solar-async-tasks/references/execution-consent.md`
- Recurring + artefact gate vs A3: `solar-async-tasks/references/recurring-with-gate.md`
- JIT agent/skill routing: `core/docs/jit-delegation-protocol.md`
