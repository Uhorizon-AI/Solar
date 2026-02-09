---
name: solar-migration-playbook
description: >
  Plan and execute migrations of existing folders/repos into Solar architecture
  with minimal risk. Use when a user wants to adapt current structures into
  core/sun/planets, define phased migration batches, and produce actionable
  file-level mapping without breaking ongoing operations.
---

# Solar Migration Playbook

## Purpose

Define a practical, low-risk process to migrate existing structures into Solar.
Focus on file-level mapping, phased execution, and validation per batch.
Avoid big-bang moves and preserve continuity of current operations.

## When to Use

Use this skill when:
- User has existing folders/repos and wants to adapt them to Solar.
- User needs a clear mapping into `core/`, `sun/`, and `planets/<planet-name>/`.
- User wants migration by controlled batches with validation checkpoints.

Do not use for:
- New greenfield setup with no pre-existing structure.
- One-off edits inside a single already-migrated skill or planet.

## Required MCP

None

## Validation commands

```bash
# Validate this skill
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-migration-playbook /tmp

# Sync core changes after modifying this skill
bash core/scripts/sync-clients.sh
```

## Workflow

1. Collect migration input
- Ask for source path(s) and intended destination scope.
- Confirm migration objective and constraints (timeline, risk tolerance, critical systems).

2. Build inventory
- Create a concise list of top-level folders/files per source.
- Tag each item as: reusable framework, personal runtime, or domain-specific.

3. Map to Solar targets
- `core/` for reusable contracts/templates/skills/scripts.
- `sun/` for personal runtime context and memory.
- `planets/<planet-name>/` for domain-specific assets.

4. Define migration batches
- Batch 1: critical day-to-day paths.
- Batch 2: automations and integrations.
- Batch 3: cleanup and standardization.

5. Execute one batch at a time
- Apply only scoped changes for the current batch.
- Report moved/rewritten files and deferred items.

6. Validate and close batch
- Validate expected runtime behavior.
- Record open risks and next batch entry criteria.

## Output format

- Migration objective
- Source inventory summary
- File-level target mapping (`core/sun/planet`)
- Batch plan (1/2/3)
- Batch execution report
- Risks and next action

## References

- `references/migration-map-template.md`
