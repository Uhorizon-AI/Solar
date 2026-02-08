# solar.ai

Solar.ai es un sistema operativo agéntico con arquitectura Sun-Planets: un agente personal central (Sun) enruta tareas a agentes de dominio (Planets) con reglas propias. Incluye contratos estándar de delegación, plantillas de onboarding y gobernanza para operar múltiples proyectos con contexto y límites claros.

## The Philosophy

Real-world users are not mono-faceted. A single person often manages multiple distinct domains (companies, side-projects, personal life). A monolithic "Personal Assistant" fails to respect the boundaries between these domains.

**Solar.ai** solves this with a gravity-based model:

- **The Sun (You):** The center of the system. Your personal agent holds your identity, preferences, and private memories. It is the single interface you talk to.
- **The Planets (Your Domains):** Independent workspaces for each of your companies or projects (e.g., `openclaw`, `brain.ai`, `real-estate`). Each planet has its own laws (governance), atmosphere (context), and specialized agents.

## Architecture

```text
/solar.ai/
├── core/                # Versioned source of truth
│   ├── templates/       # Templates used to create local workspaces
│   └── ...
├── sun/                 # Local runtime workspace (gitignored)
└── planets/             # Local runtime workspace (gitignored)
```

## Installation

This repository is intentionally lightweight. It is a Git-based operating framework, not an app server.

1. Clone and enter repo:
```bash
git clone <repo-url> solar.ai
cd solar.ai
```
2. Run bootstrap:
```bash
bash core/bootstrap.sh
```
3. Complete onboarding checklist:
- `core/checklist-onboarding.md`
- Start with the identity handshake in `core/templates/onboarding-profile.md`.

Note: `sun/` and `planets/` are ignored by Git on purpose, so each person can adapt their own instance without polluting the shared framework repository.

## How it Works

1. **You speak to the Sun.** ("Update the website", "Schedule a meeting for Company X").
2. **The Sun calculates the orbit.** It determines which Planet governs that task.
3. **Delegation.** The Sun sends a structured request to the specific Planet's agent.
4. **Execution.** The Planet executes the task using its specific tools and governance rules.
5. **Return.** The Planet reports back to the Sun, which presents the result to you.

## Operating Contract

Use standard contracts for all task exchanges:

- Request contract: `core/transport-contract.md`
- Report template: `core/report-template.md`
- Onboarding conversation contract: `core/onboarding-conversation-contract.md`
- Orchestration blueprint: `core/orchestration-blueprint.md`
- Reusable sales skill: `core/skills/solar-sales-pipeline/SKILL.md`
- Core governance: `core/AGENTS.md`
- Onboarding template: `core/templates/onboarding-profile.md`

Minimum request fields from Sun to Planet:
- `objective`
- `constraints`
- `context`

Minimum response fields from Planet to Sun:
- `status`
- `deliverables`
- `risks`
- `next_steps`

## Add a New Planet

Before creating a planet, run a user confirmation checkpoint:
- Show a short onboarding summary.
- Show proposed planet name and objective.
- Ask explicit confirmation.

1. Create a planet folder:
```bash
mkdir -p planets/<planet-name>
```
2. Copy templates:
```bash
cp core/templates/planet-AGENTS.md planets/<planet-name>/AGENTS.md
cp core/templates/planet-memory.md planets/<planet-name>/memory.md
```
3. Customize governance in `planets/<planet-name>/AGENTS.md`.
