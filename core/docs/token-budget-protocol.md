# Token Budget Protocol

**Version:** 1.1
**Scope:** Solar framework — all AI clients (Claude, Cursor, Codex, Gemini)  
**Purpose:** Keep per-session context overhead small without losing operational capability. Targets below require per-harness validation.

---

## The Problem

Unconditional loading of governance, native capability catalogs and reference
material can produce substantial overhead. The session levels below guide
selective loading; they do not prove what every harness actually injects.
Measure the client before attributing its usage to Solar. There is no measured
cross-harness saving percentage established by this protocol.

Illustrative historical file estimates, not a current unconditional load list:

| File | Tokens (est.) |
|------|---------------|
| root AGENTS.md (via CLAUDE.md) | ~2,700 |
| sun/preferences/profile.md | ~560 |
| sun/MEMORY.md | ~1,550 |
| core/AGENTS.md | ~2,800 |
| Planet AGENTS.md (active planet) | ~2,000–3,000 |
| **Subtotal** | **~9,600–10,600** |

Selected skills and references add task-dependent context. Their complete
bodies are not automatically loaded merely because Client sync published the
packages. Names, descriptions and paths in the native catalog have a separate
initial cost that grows with the number of advertised entries.

## Progressive discovery

The [small-door design](capability-discovery-design.md) documents the shared
inventory, MCP Search/Describe and opt-in reduced native profile. Full native
publication remains the default; rollout requires review and harness measurements.
Adding discovery while retaining the full advertised catalog does not remove
its initial context cost. Sharing an MCP server process can reduce local memory
overhead; it does not itself reduce model input tokens.

Compare identical tasks in fresh full/reduced sessions. Record catalog bytes,
selected instructions, input/cached/output tokens when exposed, tool calls,
latency and completion quality. Router `prompt_chars` measures only the prompt
Solar builds, not everything the harness injects or subsequently reads. Caching
can reduce billed input without removing context occupancy. Treat missing
measurements as unavailable, not zero.

---

## Three Session Levels

### Level 1 — Light

**When:** The first user message is a question, quick task, or does not reference a specific planet domain or Solar framework files.

**Examples:** "Summarize this article", "What is the status of my tasks?", "Draft a short email", "What day is it today?"

**Load:**
- `sun/preferences/profile.md` (already present via CLAUDE.md context in most clients)
- Do NOT read `sun/MEMORY.md`, `core/AGENTS.md`, or any planet AGENTS.md

**Token budget target:** < 3,500 tokens of governance overhead.

---

### Level 2 — Planet

**When:** The task clearly belongs to a specific planet (uhorizon, website, etc.) or requires planet-specific rules, skills, or data.

**Trigger signals:**
- User mentions a planet name, company, or project
- Task involves writing files inside `planets/<name>/`
- Skill invocation that is planet-prefixed (e.g., `uhorizon:weekly-report`)
- User says "in Uhorizon", "update the CRM", etc.

**Load:**
- `sun/preferences/profile.md`
- `sun/MEMORY.md` (full)
- `planets/<active-planet>/AGENTS.md` (active planet ONLY)
- Do NOT load other planets' AGENTS.md
- Do NOT load `core/AGENTS.md` unless a framework operation is needed

**Token budget target:** < 6,000 tokens of governance overhead.

---

### Level 3 — Framework

**When:** The task modifies Solar's own infrastructure: `core/`, root AGENTS.md, sync-clients.sh, create-planet.sh, skill governance, or cross-planet architecture decisions.

**Trigger signals:**
- User references `core/`, `AGENTS.md`, governance, sync, scripts, templates
- Task involves creating or modifying a planet's structure
- Task involves Solar's own maintenance or improvement

**Load:**
- `sun/preferences/profile.md`
- `sun/MEMORY.md` (full)
- `core/AGENTS.md` (full)
- Active planet AGENTS.md if applicable
- Relevant skill SKILL.md if the task touches a specific skill

**Token budget target:** < 12,000 tokens of governance overhead.

---

## Detection Logic

The AI determines the session level by inspecting the first user message before reading any additional file. Detection is sequential: check L3 conditions first, then L2, default to L1.

```
IF message mentions: core/, AGENTS.md, scripts, sync, governance, Solar itself, framework
  → Level 3

ELSE IF message mentions: planet name, company project, planet-specific skill, planet path
  → Level 2

ELSE
  → Level 1
```

If the level changes mid-session (user pivots from light question to planet work), escalate the load at that point. Never de-escalate within the same session.

---

## Prompt Caching Strategy

Keep stable content reusable where a provider/harness supports prompt caching.
Pricing and cache behavior are provider-specific; measure cached input rather
than assuming a fixed discount or automatic activation:

| File | Cache status | Reason |
|------|-------------|---------|
| root AGENTS.md / CLAUDE.md | Cacheable | Changes rarely |
| `sun/preferences/profile.md` | Cacheable | Changes at most weekly |
| `core/AGENTS.md` | Cacheable | Changes rarely |
| `sun/MEMORY.md` | Semi-static | Changes every few sessions |
| Planet AGENTS.md | Semi-static | Changes per sprint/project |
| Skills (SKILL.md) | Cacheable | Changes rarely |

**Implementation note:** a stable prefix may help cache reuse. This protocol
does not configure provider caching or guarantee a cache hit.

---

## SKILL.md Two-Part Convention

To avoid loading full skill documents when only the trigger is needed, all SKILL.md files should follow this structure:

```markdown
<!-- HEADER — always load -->
# Skill Name
**Purpose:** One-line description.
**When to use:** 2–3 trigger conditions.
**Key commands:** List of main entry points.
<!-- END HEADER -->

---

<!-- DETAIL — load only when executing the skill -->
## Full workflow
...
## Contracts
...
## References
...
<!-- END DETAIL -->
```

This is an authoring convention, not an implemented selective parser.
Client sync publishes the package; the harness controls what it loads. Keep
frontmatter descriptions concise and move long detail to references. Do not
claim that HEADER/DETAIL comments enforce a token reduction.

---

## Context reporting

The historical report below is an illustrative format with invented figures, not an available
`sync-clients.sh --report-size` interface or a tokenizer measurement. Use the
existing `core/skills/solar-skill-creator/scripts/context-report.sh` for
directional file-size inspection. Actual token accounting requires the client
or provider usage metrics:

```
Token budget report (estimated @ 12.7 chars/token):
  core/AGENTS.md                   220 lines  ~2,800 tokens
  root AGENTS.md (CLAUDE.md)       213 lines  ~2,700 tokens
  sun/MEMORY.md                    122 lines  ~1,550 tokens
  sun/preferences/profile.md        44 lines    ~560 tokens
  ---
  Top 3 heaviest skills:
    solar-async-tasks/SKILL.md     479 lines  ~6,100 tokens
    uhorizon-ai/SKILL.md           340 lines  ~4,300 tokens
    solar-router/SKILL.md          290 lines  ~3,700 tokens
  ---
  Total governance baseline:              ~9,610 tokens
  Recommended target (L2 session):        < 6,000 tokens
```

---

## Governance

This protocol is owned by `core/`. Changes require updating both this document and the first-run block in root AGENTS.md (via CLAUDE.md). The token targets are guidelines, not hard limits.

**Review trigger:** inspect context size after a significant addition to core or
planet governance. If a measured L2 baseline exceeds its target, reduce unrelated
context while preserving required rules; document the harness and measurement.
