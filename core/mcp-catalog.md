# MCP Catalog

Use this catalog to understand which MCP servers are commonly needed and how to adopt them.

## How to Read This Catalog

For each MCP entry:
- Purpose: what workflows it unlocks.
- Typical skills: where it is usually required.
- Validation: how to verify availability.

## Common MCP Servers

### `filesystem`
- Purpose: extended file operations when default client file access is not enough.
- Typical skills: migration, repository automation, structured exports across broader paths.
- Validation: run skill validation commands and ensure no filesystem permission errors.
- Notes: often optional because many AI clients already provide built-in file access in the current workspace. Use `filesystem` MCP only when extra path scope or explicit MCP-based file operations are needed.

### `github`
- Purpose: pull requests, issues, comments, review automation.
- Typical skills: engineering workflows, release ops.
- Validation: check authenticated API access and list repositories.

### `notion`
- Purpose: knowledge base reads/writes and process docs automation.
- Typical skills: documentation operations, PM workflows.
- Validation: list pages/databases required by the skill.

### `slack`
- Purpose: channel messages, updates, workflow notifications.
- Typical skills: communication automation, operational alerts.
- Validation: post/read in target channels defined by the skill.

### `calendar`
- Purpose: scheduling and availability checks.
- Typical skills: meeting orchestration, lead follow-up workflows.
- Validation: read/write test event in allowed calendar scope.

### `crm`
- Purpose: lead/account/opportunity operations.
- Typical skills: sales pipeline and follow-up automation.
- Validation: read and update a test lead/account record.

### `n8n`
- Purpose: workflow orchestration and integrations across apps/services.
- Typical skills: automation pipelines, lead enrichment, notifications, sync jobs.
- Validation: run a test workflow with one trigger and one action, then confirm execution log.

### `telegram`
- Purpose: direct chat interface and notifications via Telegram bot.
- Typical skills: conversational commands, approval flows, alert delivery.
- Validation: send and receive a test message from the target bot/chat.

### `whatsapp`
- Purpose: mobile-first conversation channel via WhatsApp integration.
- Typical skills: inbound commands, status updates, human approvals from phone.
- Validation: receive an inbound message and send a reply through the configured provider.
- Notes: usually implemented through WhatsApp Cloud API or provider bridges (for example Twilio/Meta stack), then exposed to your MCP flow.

### `chrome-devtools`
- Purpose: browser automation, page inspection, and UI validation.
- Typical skills: web QA, scraping with browser context, troubleshooting frontend flows.
- Validation: open a page, read title, and run one deterministic interaction.

## Skill Requirements Contract

Each skill should declare:

1. `Required MCP`
2. `Fallback if MCP missing`
3. `Validation commands`

Notes:
- If a skill does not require MCP, set `Required MCP` to `None`.
- If MCP is required, fallback behavior must be explicit.

## User Journey (MCP On-Demand)

1. User states goal.
2. Match goal to skill(s).
3. Read skill `Required MCP`.
4. Run MCP check script.
5. If missing MCP:
   - Offer setup now,
   - or continue with fallback mode.

## Mobile-First Conversation Goal

If the user wants to interact from phone directly:

1. Preferred channel: `telegram` or `whatsapp`.
2. Orchestration layer: `n8n` as message router.
3. Skill execution path: channel -> MCP -> Solar skills.
4. Optional browser execution: `chrome-devtools` for tasks requiring web interaction.
