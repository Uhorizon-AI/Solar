---
name: solar-sales-pipeline
description: "Generic sales pipeline standard for any planet. Use to create or update lead/contact/account records, apply stage transitions, keep short actionable history, and sync a per-planet pipeline board without company-specific logic."
---

# Solar Sales Pipeline

## Goal
Apply one concise structure for commercial tracking in any planet.

## Scope Rule
- This skill defines the shared framework.
- Pricing, ICP, messaging, and closing policies live in `planets/<planet-name>/`.

## Minimum Recommended Structure per Planet
- `planets/<planet-name>/sales/leads/YYYY/MM/`
- `planets/<planet-name>/sales/pipeline.md`

## Base Templates
- Single record: `core/templates/sales-record.md`
- Pipeline board: `core/templates/sales-pipeline-board.md`

## Minimum Record Fields
- `name`
- `organization`
- `lifecycle` (`Lead`, `Contact`, `Account`)
- `stage`
- `owner`
- `score`
- `last_contact`
- `next_followup`

## History Rules
- Descending order (most recent first).
- Keep only the last 5 interactions.
- Format: `YYYY-MM-DD - Channel - Short outcome`.

## Base Transitions
- `Lead -> Contacted`
- `Contacted -> Responded`
- `Responded -> Meeting Scheduled`
- `Meeting Scheduled -> Meeting Completed`
- `Meeting Completed -> Proposal Sent`
- `Proposal Sent -> Won` or `Lost`

## Sync Rule
When `stage` or `next_followup` changes, or when a relevant interaction happens:
1. Update the individual record.
2. Update the planet `sales/pipeline.md`.

## Expected Output per Update
- Current status.
- Next step with date.
- Main risk (if any).
