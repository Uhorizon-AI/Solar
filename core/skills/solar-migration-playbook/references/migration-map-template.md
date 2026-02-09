# Migration Map Template

Template-only file for `core/`.
Do not store user-specific migration instances in `core/`.
Save instances under `sun/migrations/` or `planets/<planet-name>/migrations/`.

## 1) Objective

- Goal:
- Constraints:
- Non-goals:

## 2) Sources

| Source path | Type (repo/folder) | Notes |
|---|---|---|
|  |  |  |

## 3) Migration Mode

- `.git` detected: yes/no
- Selected mode: `in-place` or `copy-import`
- Why this mode:
- User confirmation:

## 4) File-level Mapping

| Source | Target scope | Target path | Action (keep/move/rewrite/archive) | Rationale |
|---|---|---|---|---|
|  | core |  |  |  |
|  | sun |  |  |  |
|  | planet | planets/<name>/... |  |  |

## 5) Planet Boundary Gate (Required)

- Existing target planet:
- Boundary criteria check:
  - Objective/KPI distinct: yes/no
  - Stakeholders distinct: yes/no
  - Data/processes distinct: yes/no
  - Execution rules distinct: yes/no
- Threshold result:
  - 2 criteria -> evaluate split
  - 3+ criteria -> create/suggest separate planet
- Decision:
- Rationale:

## 6) Mixed-context Items (if any)

| Source | Mixed contexts detected | Decision (`split-required`/`single-scope`) | Planned slices |
|---|---|---|---|
|  |  |  |  |

## 7) Batches

### Batch 1 (Critical)
- Scope:
- Success criteria:
- Rollback note:

### Batch 2 (Automations)
- Scope:
- Success criteria:
- Rollback note:

### Batch 3 (Cleanup)
- Scope:
- Success criteria:
- Rollback note:

## 8) Validation

- Functional checks:
- Data integrity checks:
- Routing/governance checks:

## 9) Risks and Decisions

- Risks:
- Mitigations:
- Deferred decisions:

## 10) Decision Log (Per Batch)

| Batch | Scope decision (`core/sun/planet`) | Rationale | Risks | Next checkpoint |
|---|---|---|---|---|
|  |  |  |  |  |
