# MCP Requirements

Solar does not maintain a fixed MCP catalog. MCP usage is declared per skill, because different users, planets, and AI clients may expose different tools.

## Source of Truth

The source of truth for MCP requirements is each skill's `SKILL.md`:

1. `## Required MCP`
2. `## Fallback if MCP missing`
3. Validation notes or commands when the skill needs them.

If a skill does not require an MCP server, set `Required MCP` to `None`.

## Runtime Check

Before using a skill that declares MCP requirements:

1. Read the skill's `Required MCP` section.
2. Run `bash core/scripts/check-mcp.sh --skill <skill-path>` when local client config validation is useful.
3. If an MCP is missing, use the skill's fallback mode or ask the user to configure the specific missing server.

## Canonical Browser Exception

Chrome DevTools has an extra lifecycle rule because it can leave local browser and helper processes running:

- Before Chrome DevTools MCP work: run `core/skills/solar-browser/scripts/ensure_browser.sh --start`.
- After the browser workflow completes: run `core/skills/solar-browser/scripts/ensure_browser.sh --stop`.
- Full protocol: `core/docs/browser-protocol.md`.

Do not instruct users to keep Chrome remote debugging always on.

## Design Rule

Do not add broad, global MCP assumptions to onboarding or governance docs. Add requirements to the specific skill that needs the server.
