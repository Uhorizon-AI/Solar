#!/usr/bin/env python3
"""
Universal Skill Packager
Validates and packages skills into .skill files (zip with .skill extension)
Compatible with Claude, Codex, Gemini, and all SKILL.md-compatible AI agents.
"""

import os
import sys
import zipfile
import argparse
from pathlib import Path
import re


def extract_section(body: str, heading: str) -> str:
    pattern = rf"{re.escape(heading)}\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, body, re.DOTALL)
    return match.group(1).strip() if match else ""

def validate_skill(skill_path: Path) -> list:
    """Validate skill structure and return list of errors."""
    errors = []

    # Check SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        errors.append("Missing required SKILL.md file")
        return errors

    # Read and parse SKILL.md
    content = skill_md.read_text(encoding='utf-8')

    # Check frontmatter
    if not content.startswith('---'):
        errors.append("SKILL.md must start with YAML frontmatter (---)")
        return errors

    # Extract frontmatter
    parts = content.split('---', 2)
    if len(parts) < 3:
        errors.append("Invalid YAML frontmatter format")
        return errors

    frontmatter = parts[1]
    body = parts[2]

    # Check required fields
    if 'name:' not in frontmatter:
        errors.append("Missing 'name' field in frontmatter")

    if 'description:' not in frontmatter:
        errors.append("Missing 'description' field in frontmatter")

    # Check description quality
    desc_match = re.search(r'description:\s*>?\s*(.+?)(?=\n[a-z]+:|$)', 
                          frontmatter, re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip()
        if len(desc) < 50:
            errors.append("Description too short (minimum 50 characters)")
        if '[TODO]' in desc:
            errors.append("Description contains [TODO] - complete before packaging")

    # Check body not empty
    if len(body.strip()) < 100:
        errors.append("SKILL.md body too short (minimum 100 characters)")

    # Check for TODOs in body
    if '[TODO]' in body:
        errors.append("SKILL.md contains [TODO] markers - complete before packaging")

    # Required sections (always)
    always_required_sections = [
        "## Required MCP",
        "## Validation commands",
    ]
    for section in always_required_sections:
        if section not in body:
            errors.append(f"Missing required section: {section}")

    # Conditional fallback section
    required_mcp_content = extract_section(body, "## Required MCP")
    has_fallback_section = "## Fallback if MCP missing" in body
    requires_mcp = bool(required_mcp_content) and not re.search(
        r"\b(none|n/a|not required)\b", required_mcp_content, re.IGNORECASE
    )

    if requires_mcp and not has_fallback_section:
        errors.append("Missing required section: ## Fallback if MCP missing")

    # Check file size
    if len(content) > 100000:  # ~100KB
        errors.append("SKILL.md too large (>100KB). Consider splitting into references/")

    # Check line count
    line_count = len(body.split('\n'))
    if line_count > 500:
        errors.append(f"SKILL.md body has {line_count} lines (recommended max: 500)")

    # Warn about extraneous files
    extraneous = ['README.md', 'CHANGELOG.md', 'LICENSE.md', 'INSTALL.md']
    for filename in extraneous:
        if (skill_path / filename).exists():
            errors.append(f"Remove extraneous file: {filename}")

    return errors

def package_skill(skill_path: Path, output_dir: Path) -> Path:
    """Package skill into .skill file (zip)."""

    skill_name = skill_path.name
    output_file = output_dir / f"{skill_name}.skill"

    # Create zip file with .skill extension
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(skill_path):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(skill_path.parent)
                zf.write(file_path, arcname)

    return output_file

def main():
    parser = argparse.ArgumentParser(
        description="Validate and package a universal AI skill"
    )
    parser.add_argument("skill_path", type=Path, help="Path to skill directory")
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs='?',
        default=Path.cwd(),
        help="Output directory for .skill file (default: current directory)"
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip validation (not recommended)"
    )

    args = parser.parse_args()

    # Validate paths
    if not args.skill_path.exists():
        print(f"❌ Error: Skill directory not found: {args.skill_path}")
        sys.exit(1)

    if not args.skill_path.is_dir():
        print(f"❌ Error: Path is not a directory: {args.skill_path}")
        sys.exit(1)

    # Create output directory if needed
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Validate skill
    if not args.no_validate:
        print("🔍 Validating skill...")
        errors = validate_skill(args.skill_path)

        if errors:
            print("\n❌ Validation failed:\n")
            for error in errors:
                print(f"  • {error}")
            print("\nFix errors and run again, or use --no-validate to skip.")
            sys.exit(1)

        print("✅ Validation passed")

    # Package skill
    print("📦 Packaging skill...")
    output_file = package_skill(args.skill_path, args.output_dir)

    file_size = output_file.stat().st_size
    size_kb = file_size / 1024

    print(f"\n✅ Skill packaged successfully!")
    print(f"   File: {output_file}")
    print(f"   Size: {size_kb:.1f} KB")
    print(f"\n📋 To install:")
    print(f"   - Claude Code: Import .skill file in settings")
    print(f"   - Codex: Place in ~/.config/codex/skills/")
    print(f"   - Gemini: Upload via Code Assist settings")

if __name__ == "__main__":
    main()
