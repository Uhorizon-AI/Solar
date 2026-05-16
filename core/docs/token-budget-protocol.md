# Token Budget Protocol

**Version:** 1.0  
**Scope:** Solar framework — all AI clients (Claude, Cursor, Codex, Gemini)  
**Purpose:** Reduce per-session context overhead by 50–60% without losing operational capability.

---

## The Problem

Solar's first-run protocol currently loads the same set of files in every session regardless of task type. In a typical planet work session this produces ~25,000–35,000 tokens of governance overhead before the AI does anything useful. At scale this is the largest controllable cost in the system.

Files loaded unconditionally today:

| File | Tokens (est.) |
|------|---------------|
| root AGENTS.md (via CLAUDE.md) | ~2,700 |
| sun/preferences/profile.md | ~560 |
| sun/MEMORY.md | ~1,550 |
| core/AGENTS.md | ~2,800 |
| Planet AGENTS.md (active planet) | ~2,000–3,000 |
| **Subtotal** | **~9,600–10,600** |

Skills add another 1,500–6,000 tokens each when invoked.

---

## Three Session Levels

### Level 1 — Light

**When:** The first user message is a question, quick task, or does not reference a specific planet domain or Solar framework files.

**Examples:** "Résumeme este artículo", "¿Cuál es el estado de mis tasks de Ascendion?", "Redacta un email corto", "¿Qué día es hoy?"

**Load:**
- `sun/preferences/profile.md` (already present via CLAUDE.md context in most clients)
- Do NOT read `sun/MEMORY.md`, `core/AGENTS.md`, or any planet AGENTS.md

**Token budget target:** < 3,500 tokens of governance overhead.

---

### Level 2 — Planet

**When:** The task clearly belongs to a specific planet (uhorizon, ascendion, louis, website, etc.) or requires planet-specific rules, skills, or data.

**Trigger signals:**
- User mentions a planet name, company, or project
- Task involves writing files inside `planets/<name>/`
- Skill invocation that is planet-prefixed (e.g., `uhorizon:linkedin-post`)
- User says "en Uhorizon", "para Ascendion", "actualiza el CRM", etc.

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

Files that rarely change should be treated as cacheable to activate Claude's 90% discount on cached input tokens:

| File | Cache status | Reason |
|------|-------------|---------|
| root AGENTS.md / CLAUDE.md | Cacheable | Changes rarely |
| `sun/preferences/profile.md` | Cacheable | Changes at most weekly |
| `core/AGENTS.md` | Cacheable | Changes rarely |
| `sun/MEMORY.md` | Semi-static | Changes every few sessions |
| Planet AGENTS.md | Semi-static | Changes per sprint/project |
| Skills (SKILL.md) | Cacheable | Changes rarely |

**Implementation note:** Claude's prompt caching activates automatically for content that appears consistently at the start of conversations. Keeping CLAUDE.md (root AGENTS.md) stable and below 3,000 tokens maximizes cache hit rate.

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

The AI loads only the HEADER section during routing/detection. The DETAIL section is read only when the skill is actually invoked. This reduces skill overhead from 1,500–6,000 tokens to 200–400 tokens per skill during routing.

---

## Token Estimation in sync-clients.sh

When `--report-size` flag is passed, `sync-clients.sh` should output:

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

**Review trigger:** Run `sync-clients.sh --report-size` after any significant addition to core/ or a planet AGENTS.md. If the L2 baseline exceeds 8,000 tokens, compress before merging.
