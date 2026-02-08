#!/usr/bin/env python3
"""
Universal Skill Initializer
Creates a new skill directory with proper SKILL.md template and resource folders.
Works for Claude, Codex, Gemini, and all SKILL.md-compatible AI agents.
"""

import os
import sys
import argparse
from pathlib import Path

SKILL_TEMPLATE = '''---
name: {skill_name}
description: >
  [TODO: Describe what this skill does AND when to use it. Include specific
  triggers, contexts, and use cases. This description is what the AI reads
  to decide if this skill applies to a user request.]
---

# {skill_title}

## Purpose

[TODO: 2-4 sentences explaining what problem this skill solves]

## When to Use

✅ Use this skill when:
- [TODO: List situations]

❌ Don't use for:
- [TODO: Exclusions]

## Workflow

1. Validate request
2. Execute procedure
3. Format output

## Required MCP

- [TODO: List required MCP servers or write "None"]

## Fallback if MCP missing

- [TODO: Define behavior if MCP is unavailable]
- [TODO: If Required MCP is "None", write "N/A"]

## Validation commands

```bash
[TODO: Add one or more commands to verify this skill works]
```

## Examples

### Example 1

**User input:**
> [TODO: Example]

**Expected behavior:**
> [TODO: Response]
'''

def create_skill(skill_name: str, output_path: Path):
    skill_path = output_path / skill_name

    if skill_path.exists():
        print(f"❌ Error: Skill directory already exists: {skill_path}")
        sys.exit(1)

    skill_path.mkdir(parents=True)
    (skill_path / "scripts").mkdir()
    (skill_path / "references").mkdir()
    (skill_path / "assets").mkdir()

    skill_title = skill_name.replace('-', ' ').replace('_', ' ').title()
    skill_content = SKILL_TEMPLATE.format(
        skill_name=skill_name,
        skill_title=skill_title
    )
    (skill_path / "SKILL.md").write_text(skill_content, encoding='utf-8')

    print(f"✅ Skill created: {skill_path}")
    print(f"")
    print(f"Next steps:")
    print(f"1. Edit {skill_name}/SKILL.md")
    print(f"2. Add your scripts, references, assets")
    print(f"3. Run: python scripts/package_skill.py {skill_name}")

def main():
    parser = argparse.ArgumentParser(
        description="Initialize a new universal AI skill"
    )
    parser.add_argument("skill_name", help="Name of the skill")
    parser.add_argument("--path", type=Path, default=Path.cwd())

    args = parser.parse_args()
    create_skill(args.skill_name, args.path)

if __name__ == "__main__":
    main()
