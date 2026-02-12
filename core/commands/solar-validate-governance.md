---
name: solar-validate-governance
description: Validate Solar governance structure coherence across all AGENTS.md layers
---

# Solar Governance Validation

Interactive validation command to verify governance coherence across root, core, and planet layers.

## Usage

Execute this command after creating or modifying any AGENTS.md file to ensure governance structure remains coherent.

---

## 1. Structure Coherence

Verify that Solar's three-layer governance structure is properly implemented:

### Required Files
- [ ] `AGENTS.md` (root) exists
- [ ] `core/AGENTS.md` exists
- [ ] `planets/<planet-name>/AGENTS.md` exists for each planet

### Root AGENTS.md Structure
- [ ] Has "Instruction Resolution (Required)" section
  - [ ] Defines 3 layers explicitly: root, core, planets
  - [ ] Clarifies `sun/` is runtime storage, NOT governance
- [ ] Has "Governance Delegation (Required)" section
  - [ ] Documents only immediate delegation (root → core)
  - [ ] Does NOT document entire chain
- [ ] Has "Planet Resource Sync (Required)" section
  - [ ] Delegates to `core/AGENTS.md` for operational rules

### Core AGENTS.md Structure
- [ ] Has "Governance delegation rule (required)" section
  - [ ] Documents authority: framework operations
  - [ ] Documents it's called by root
  - [ ] Does NOT document entire chain
- [ ] Has "Planet management rule (required)" section
  - [ ] Documents create-planet.sh usage
  - [ ] Documents sync-clients.sh usage
  - [ ] Documents conflict resolution (npm-style prefixing)

### Planet AGENTS.md Structure
- [ ] Has "Governance Delegation" section
  - [ ] Documents authority: domain-specific governance
  - [ ] Documents delegation to `../../AGENTS.md` (root)
  - [ ] Does NOT document entire chain
- [ ] Has "Planet Sync Rule" section (if planet has resources)
  - [ ] References root for operational rules
  - [ ] Provides quick reference commands

---

## 2. Delegation Chain Coherence

Verify each layer knows only its immediate delegate (minimal knowledge principle):

### Planet → Root Delegation
For each `planets/<planet-name>/AGENTS.md`:
- [ ] Documents authority: "Domain-specific governance"
- [ ] Delegates to: `../../AGENTS.md` (root)
- [ ] Does NOT mention `core/AGENTS.md`
- [ ] Does NOT explain what root does with the delegation

### Root → Core Delegation
For `AGENTS.md` (root):
- [ ] Documents authority: "Global orchestration"
- [ ] Delegates to: `core/AGENTS.md`
- [ ] Does NOT mention planets in delegation section
- [ ] Does NOT document complete chain (planet → root → core)

### Core Execution Context
For `core/AGENTS.md`:
- [ ] Documents authority: "Framework operational rules"
- [ ] Documents it's called by: root
- [ ] Does NOT mention planets
- [ ] Does NOT document complete chain

### Chain Integrity
- [ ] No AGENTS.md documents complete chain (planet → root → core)
- [ ] Each file knows only its immediate neighbor
- [ ] No file explains what happens after delegation
- [ ] `sun/` is NOT treated as a governance layer anywhere

---

## 3. Resource Sync Protocol Consistency

Verify planet resource sync protocol is documented consistently:

### Root Layer
`AGENTS.md` (root):
- [ ] Has "Planet Resource Sync (Required)" section
- [ ] States planets can include custom resources
- [ ] Delegates to `core/AGENTS.md` "Planet management rule"
- [ ] Does NOT duplicate operational instructions

### Core Layer
`core/AGENTS.md`:
- [ ] Has "Planet management rule (required)" section
- [ ] Documents `create-planet.sh` usage
- [ ] Documents `sync-clients.sh` usage
- [ ] Documents npm-style prefixing: `<planet-name>:<resource-name>`
- [ ] References `planet-structure.md` for structure details

### Planet Template
`core/templates/planet-AGENTS.md`:
- [ ] Has "Planet Sync Rule" section
- [ ] States planet supports custom resources
- [ ] References `../../AGENTS.md` for protocols
- [ ] Provides quick reference commands
- [ ] Does NOT duplicate detailed instructions

### Consistency Check
- [ ] All layers use consistent terminology
- [ ] npm-style prefixing documented consistently across layers
- [ ] Sync command (`sync-clients.sh`) referenced correctly
- [ ] Delegation flow: Planet → Root → Core (no layer skipping)

---

## 4. Token Efficiency (CRITICAL)

**AGENTS.md files MUST be CONCISE and TOKEN-EFFICIENT.**

### Strict Character Limits
- [ ] Root AGENTS.md: **≤ 4,000 characters** (~1,000 tokens) - Router only
- [ ] core/AGENTS.md: **≤ 8,000 characters** (~2,000 tokens) - Framework operations
- [ ] Planet AGENTS.md: **≤ 2,500 characters** (~625 tokens) - Domain-specific

### Verify Current Sizes
Run: `wc -m AGENTS.md core/AGENTS.md planets/*/AGENTS.md`

### Token Efficiency Principles
- [ ] **High signal-to-noise ratio** - Every sentence adds value
- [ ] **No duplication** - Delegate instead of repeating
- [ ] **No examples in rules** - Reference external files for examples
- [ ] **Specific, not verbose** - "≤ 4,000 characters" not "keep it short"

### If Over Limit
1. Extract examples to separate reference files
2. Use "See X for details" instead of duplicating
3. Remove persuasive language, keep only directives
4. Consolidate similar rules

---

## Validation Result

**All checks passed:** ✅ Governance structure is coherent, properly delegated, and token-efficient.

**Some checks failed:** ⚠️ Review failed items and fix before proceeding with governance changes.

---

## Common Issues and Fixes

### Issue: Planet AGENTS.md references core directly
- **Fix:** Change to reference `../../AGENTS.md` (root only)

### Issue: AGENTS.md documents entire governance chain
- **Fix:** Document only immediate delegation

### Issue: `sun/` treated as governance layer
- **Fix:** Clarify it's runtime storage, not governance

### Issue: Inconsistent npm-style prefixing documentation
- **Fix:** Use `<planet-name>:<resource-name>` consistently

### Issue: Planet duplicates operational instructions
- **Fix:** Simplify to reference root + quick reference only
