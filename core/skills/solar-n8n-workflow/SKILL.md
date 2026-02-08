---
name: solar-n8n-workflow
description: >
  Build or update n8n workflows in Solar for MCP-based integrations. Use when a
  user needs to connect channels (starting with Telegram), route messages,
  trigger skills, or orchestrate automation steps with a clear fallback path.
---

# Solar n8n Workflow

## Purpose

Create and maintain n8n workflows that connect user channels to Solar operations
with clear structure, safe defaults, and testable execution.

## Scope

- Create new n8n workflows for message routing and automation.
- Update existing workflows without breaking active triggers.
- Keep workflow logic documented and reproducible.

## Required MCP

- n8n
- telegram

## Fallback if MCP missing

- If `n8n` MCP is missing: provide a manual workflow design (step-by-step) and stop before execution.
- If `telegram` MCP is missing: keep workflow generic and output integration placeholders for bot token/chat IDs.
- If both are missing: output a runnable implementation checklist and validation plan only.

## Validation commands

```bash
# Validate required MCP declarations for this skill
bash core/scripts/check-mcp.sh --skill core/skills/solar-n8n-workflow/SKILL.md

# Sync core skills to local clients after updates
bash core/scripts/sync-clients.sh
```

## Workflow

1. Confirm objective and channel (default: Telegram-first).
2. Map trigger, transform, route, and action nodes.
3. Define failure path and retry behavior.
4. Add minimal observability (run log + error branch).
5. Validate MCP availability.
6. Produce implementation output and test checklist.

## Output Format

- Workflow summary (what it does, trigger, key actions).
- Node-by-node plan.
- Required credentials/secrets (names only, no values).
- Test checklist (happy path + failure path).
- Next step to deploy.

## References

- `references/telegram-first-workflow.md`
