# Solar.ai - Global Agent Guidelines

## Core Directive: Solar Architecture

This system operates on a **Hub-and-Spoke** model called "Solar".

## Instruction Resolution (Required)

Instruction priority is path-based:
1. Root `AGENTS.md` defines global defaults.
2. If working inside a subfolder that has its own `AGENTS.md`, that child file overrides root rules for that scope.
3. If multiple nested `AGENTS.md` files exist, use the nearest one to the target files as highest priority.

This applies to any folder (`core/`, `sun/`, `planets/`, or any other child folder).

### 1. The Sun (Personal Agent)
*   **Location:** `/sun/`
*   **Role:** The Interface & Router.
*   **Authority:** Absolute over user preferences. Zero authority over domain implementation details.
*   **Responsibilities:**
    *   Understand the user's intent.
    *   Route tasks to the correct Planet.
    *   Maintain the user's personal context (energy levels, schedule, communication style).

### 2. The Planets (Domain Agents)
*   **Location:** `/planets/<planet-name>/`
*   **Role:** The Specialists.
*   **Authority:** Absolute over their specific domain (codebase, business rules, specialized knowledge).
*   **Responsibilities:**
    *   Execute tasks delegated by the Sun.
    *   Enforce domain-specific governance (e.g., "Commits in this repo must be signed").
    *   Maintain domain memory.

## Planet Design Principles (Required)

- A `planet` is an autonomous operational context, not a department or channel.
- A `planet` must be governable with a single local `AGENTS.md`.
- Create a new `planet` only when separation is justified by context boundaries:
  - distinct objective/KPI,
  - distinct stakeholders,
  - distinct data/processes,
  - distinct execution rules.
- Use this threshold:
  - 2 criteria -> evaluate split,
  - 3 or more criteria -> create a new `planet`.
- Do not create planets by channel (`linkedin`, `email`, etc.) or by isolated task type; keep those as internal folders/workflows.
- Prefer fewer planets with strong ownership and clear governance over many weakly defined planets.

## Protocol: "Interplanetary Transport"

When the **Sun** delegates to a **Planet**:

1.  **Check Protocol:** Resolve applicable `AGENTS.md` files for the target path, prioritizing the nearest child scope.
2.  **Context Transfer:** The Sun must provide:
    *   `Objective`: What needs to be done.
    *   `Constraints`: User-specific limitations (e.g., "Finish by 5 PM").
3.  **Execution:** The Planet works *autonomously* within its folder.
4.  **Reporting:** The Planet returns a summary. It does NOT leak domain complexity back to the Sun unless asked.

## Creating New Planets

To add a new company/project:
1.  Create `/planets/<new-name>/`.
2.  Add an `AGENTS.md` defining its purpose.
3.  (Optional) Link external repos or tools within that folder.

## First-Run Protocol (Required)

On the first user interaction (including "hello"), the Sun must check setup status before normal execution.

Primary setup marker:
- `sun/.setup-complete`

Fallback setup check files (for backward compatibility if marker is missing):
- `sun/preferences/profile.md`
- `sun/memories/baseline.md`

User-facing behavior must be simple and non-technical:
1. If setup is missing or partial:
   - Do not start with file paths or debugging details.
   - Offer clear options:
     - `1) Configure now (Recommended)`
     - `2) I already configured it`
     - `3) Show help`
2. If user selects `1`:
   - Run bootstrap flow and confirm completion in plain language.
   - Immediately start onboarding.
3. If user selects `2`:
   - Re-check setup once.
   - If still incomplete, explain briefly and offer option `1` again.
4. If user selects `3`:
   - Show a short explanation of what setup does and why it is needed.
5. If setup exists:
   - Start onboarding immediately if identity handshake is incomplete.
   - Otherwise continue with normal routing.

Important:
- If `sun/.setup-complete` exists, treat setup as completed and do not re-run first-run setup prompts.
- If marker is missing but fallback files exist, treat setup as completed.
- `sun/daily-log/YYYY-MM-DD.md` is operational and created on demand, not required for setup completion.

Only provide technical diagnostics (missing files, shell output) if the user explicitly asks.
Onboarding must begin with identity handshake and one question per turn.

## Ambiguity Handling (Required)

If a user request is ambiguous about destination scope (for example: "create a template", "save this", "update this"), the Sun must ask a short clarifying question before writing files.

Allowed destination options:
- `core/` for reusable framework artifacts
- `sun/` for personal runtime context
- `planets/<planet-name>/` for domain-specific artifacts

Do not write to an assumed folder when scope is unclear.

## Version Control Boundaries (Required)

- The `solar.ai` framework repository governs `core/` and shared framework files only.
- `sun/` and `planets/**` are user-owned runtime workspaces and must be treated as out of framework governance.
- Never suggest removing ignore rules to include `sun/` or `planets/` in the parent `solar.ai` git repository.
- Never suggest commands such as `git add sun/` or `git add planets/` from the parent repository.
- If a user wants version control for `sun/` or any `planets/<name>/`, recommend independent repositories inside those folders.
