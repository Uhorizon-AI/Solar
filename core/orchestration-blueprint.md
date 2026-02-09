# Solar Orchestration Blueprint

This blueprint defines how Sun orchestrates work across planets and memory layers.

## Goal
Keep execution simple, traceable, and reusable for any user.

## Runtime Sources
- User preferences: `sun/preferences/profile.md`
- Baseline context: `sun/memories/baseline.md`
- Daily execution (on demand): `sun/daily-log/YYYY-MM-DD.md`
- Planet scope and governance: `planets/<planet-name>/AGENTS.md`
- Planet memory: `planets/<planet-name>/memory.md`

## Orchestration Cycle
1. Understand user intent in one sentence.
2. Route to the correct planet using scope in `planets/<planet-name>/AGENTS.md`.
3. Build a Sun -> Planet request with `core/transport-contract.md`.
4. Execute task in the selected planet.
5. Capture Planet -> Sun response with `core/report-template.md`.
6. Persist learnings:
   - Stable user-level decisions -> `sun/memories/baseline.md`
   - Domain decisions and facts -> `planets/<planet-name>/memory.md`
   - Daily actions and follow-ups -> `sun/daily-log/YYYY-MM-DD.md` (only when daily planning or follow-up is needed)
7. Return concise result to user and ask next decision only if needed.

## Discovery Standard (for sales/commercial planets)
- Use `core/templates/lead-discovery-5q.md` for first-call qualification.
- Persist score, package recommendation, and next action in planet memory.
- Use `core/skills/solar-sales-pipeline/SKILL.md` to keep sales records and stage transitions consistent across planets.

## Routing Rules
- If task is identity, communication style, or personal constraints -> Sun.
- If task is domain execution -> matching planet.
- If task spans multiple domains -> split into independent planet tasks and aggregate in Sun.
- If no planet exists yet -> run pre-planet checkpoint before creation.

## Pre-Planet Gate (Required)
Before creating a new planet, Sun must:
1. Show a short summary of captured onboarding state.
2. Show proposed planet name and objective.
3. Ask explicit confirmation.
4. Create folder only after a clear yes.

## Planet Boundary Rule (Required)
- Treat each `planet` as an autonomous operational context (not as a department/channel).
- A new `planet` should be created only when context boundaries justify separation:
  - objective/KPI,
  - stakeholders,
  - data/processes,
  - execution rules.
- Decision threshold:
  - 2 criteria -> evaluate split,
  - 3+ criteria -> create a new `planet`.
- Do not split planets by channel or isolated task type; keep those concerns inside the existing planet structure.

## Persistence Rules
- Write only the minimum durable context.
- Do not duplicate the same fact in multiple files unless needed for operation.
- Keep memory entries atomic and specific.
- Prefer appending new facts over rewriting history, except when correcting wrong data.

## Correction Handling
- User corrections override previous values.
- Update the source file immediately.
- Continue from latest valid state without restarting onboarding.

## Minimum Quality Bar per Task
- Request has `objective`, `constraints`, `context`.
- Response has `status`, `deliverables`, `risks`, `next_steps`.
- At least one memory update occurs when a new durable decision appears.
- Output to user is brief and actionable.
