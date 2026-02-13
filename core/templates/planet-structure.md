# Planet Structure Reference

This document describes the expected structure for a Solar planet workspace.

## Minimal Planet Structure

Every planet must have at minimum:

```
planets/<planet-name>/
├── AGENTS.md          # Governance, scope, and protocols (required)
├── CLAUDE.md -> AGENTS.md   # Symlink for Claude AI clients
└── GEMINI.md -> AGENTS.md   # Symlink for Gemini AI clients
```

The symlinks ensure that different AI clients can discover the planet's governance instructions, regardless of which filename they look for.

## Full Planet Structure (Optional Components)

As your planet grows, you can add these optional components:

```
planets/<planet-name>/
├── AGENTS.md          # Governance and protocols (required)
├── CLAUDE.md -> AGENTS.md   # Symlink for Claude AI
├── GEMINI.md -> AGENTS.md   # Symlink for Gemini AI
├── README.md          # Optional: planet overview
├── MEMORY.md          # Optional: planet-specific memory (AI-agnostic, max 100 lines)
├── agents/            # Optional: custom agent definitions
│   ├── agent-1.md
│   └── agent-2.md
├── commands/          # Optional: custom commands
│   ├── command-1.md
│   └── command-2.md
└── skills/            # Optional: domain-specific skills
    ├── skill-1/
    │   ├── SKILL.md   # Required for each skill
    │   └── ...        # Skill implementation files
    └── skill-2/
        ├── SKILL.md
        └── ...
```

## Creating New Resources

### Creating a Skill

1. Create a folder in `planets/<planet-name>/skills/<skill-name>/`
2. Add a `SKILL.md` file (required)
3. Add implementation files as needed
4. Run sync: `bash ../../core/scripts/sync-clients.sh`

### Creating an Agent

1. Create a `.md` file in `planets/<planet-name>/agents/<agent-name>.md`
2. Define the agent's purpose, capabilities, and protocols
3. Run sync: `bash ../../core/scripts/sync-clients.sh`

### Creating a Command

1. Create a `.md` file in `planets/<planet-name>/commands/<command-name>.md`
2. Define the command's behavior and usage
3. Run sync: `bash ../../core/scripts/sync-clients.sh`

## Resource Sync

After creating or updating resources, always run:

```bash
bash ../../core/scripts/sync-clients.sh
```

This syncs your planet's resources to:
- `.claude/` - Claude Code client
- `.cursor/` - Cursor AI client
- `.codex/` - Codex client

### Resource Naming

- All planet resources are **always prefixed** with the planet name (npm-style)
- Example: `skill-name` → `planet-name:skill-name`
- This ensures deterministic naming and prevents conflicts
- Only `core/` resources remain unprefixed (framework privilege)

## Best Practices

1. **Create folders only when needed** - Don't create empty `agents/`, `commands/`, or `skills/` folders
2. **Use clear naming** - Choose descriptive names that won't conflict with core resources
3. **Sync after changes** - Always sync after creating or updating resources
4. **Document in AGENTS.md** - Keep your planet's governance and scope up to date
5. **Keep planet-specific** - Only put domain-specific resources in planets; framework resources go in `core/`

## Quick Start

The easiest way to create a new planet is using the helper script:

```bash
bash core/scripts/create-planet.sh my-project
```

This automatically:
- Creates the planet directory
- Copies the AGENTS.md template
- Creates CLAUDE.md and GEMINI.md symlinks
- Shows next steps

## See Also

- `/core/templates/planet-AGENTS.md` - AGENTS.md template
- `/core/scripts/sync-clients.sh` - Resource sync script
- `/core/scripts/create-planet.sh` - Planet creation helper script
- `/AGENTS.md` - Root Solar governance
