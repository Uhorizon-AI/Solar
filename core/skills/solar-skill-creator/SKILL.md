---
name: solar-skill-creator
description: >
  Solar-native guide for creating or updating skills in this repository. Use when a
  user needs a new reusable skill, a migration from external skills, or a cleanup of
  existing skills to match Solar governance (core vs planet scope, English in core,
  lean structure, and minimal dependencies).
---

# Solar Skill Creator

Create and maintain skills that fit Solar architecture without depending on external skill folders.

## Purpose

Define a consistent process to:
- create new skills in `core/skills/` or `planets/<planet-name>/skills/`,
- migrate external skills into Solar-owned skills,
- keep skills lean, testable, and easy to maintain.

## Scope Rules

- Put a skill in `core/skills/` only if reused by 2+ planets or 3+ times.
- Put planet-specific skills in `planets/<planet-name>/`.
- Keep `core` content in English.
- Planet skills may use the user preferred language.

## Required MCP

None

## Validation commands

```bash
# Validate one modified skill (standard per-skill flow)
python3 core/skills/solar-skill-creator/scripts/package_skill.py <skill-path> /tmp

# Sync core skill changes to local clients
bash core/scripts/sync-clients.sh
```

## Skill Structure

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter: name + description
│   └── Markdown instructions
└── Optional resources:
    ├── scripts/     - deterministic execution
    ├── references/  - large or variant details
    └── assets/      - output templates/files
```

Do not add auxiliary docs like README/INSTALL/CHANGELOG inside skill folders.

## Workflow

1. Capture 2-3 concrete usage examples.
2. Decide destination: `core` or `planet`.
3. Create or update folder and `SKILL.md`.
4. Add only required resources (`scripts`, `references`, `assets`).
5. Validate:
   - clear trigger description,
   - no duplicated content,
   - lean size (prefer references for long details),
   - no extraneous files.
6. If migrating from external source, rewrite into Solar-owned language and structure.

## Required Checks

- Frontmatter includes only `name` and `description`.
- Description states what it does and when to use it.
- Body stays procedural and concise.
- Core skills remain vendor-neutral and Solar-owned.
- Skill body includes these required sections:
  - `Required MCP`
  - `Validation commands`
- `Fallback if MCP missing` is required only when `Required MCP` is not `None`.
- If skill scripts manage `.env`, they must write a skill-scoped compact block:
  - header comment identifying the skill,
  - contiguous variables with no blank lines inside the block,
  - preserve existing values unless explicit overwrite is requested.
- If a skill is modified, validate that specific skill with:
  - `python3 core/skills/solar-skill-creator/scripts/package_skill.py <skill-path> /tmp`
  - do not use `--no-validate` in normal flow.

## Migration Rule

If source exists outside Solar:
- reuse concepts, not blind copy,
- remove platform-specific installation noise,
- avoid external runtime dependencies unless explicitly needed,
- keep attribution/license notes when required.

## Bundled References in This Skill

- `references/workflows.md`
- `references/output-patterns.md`

## Provenance

Based on cross-agent skill-creator concepts, adapted for Solar architecture.
