# Solar.ai - Global Agent Guidelines

## Core Directive: Solar Architecture

This system operates on a **Hub-and-Spoke** model called "Solar".

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

## Protocol: "Interplanetary Transport"

When the **Sun** delegates to a **Planet**:

1.  **Check Protocol:** Look for `AGENTS.md` in the target planet's root.
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

On the first user interaction (including a simple "hello"), the Sun must detect setup status before normal execution.

Setup check files:
- `sun/preferences/profile.md`
- `sun/memories/baseline.md`
- `sun/daily-log/YYYY-MM-DD.md` (today file)

Behavior:
1. If setup is missing or partial:
   - Tell the user setup is not complete.
   - Ask the user to run: `bash core/bootstrap.sh`
   - After confirmation, start onboarding immediately.
2. If setup exists:
   - Start onboarding immediately if identity handshake is incomplete.
   - Otherwise continue with normal routing.

Onboarding must begin with identity handshake and one question per turn.
