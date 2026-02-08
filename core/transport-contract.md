# Interplanetary Transport Contract

This contract defines the standard message exchanged between the Sun and any Planet.

## Sun -> Planet Request

Required fields:
- `objective`: concrete result expected.
- `constraints`: limits for time, quality, budget, security, or process.
- `context`: relevant state that helps execution.

Optional fields:
- `deadline`
- `priority`
- `references`

## Planet -> Sun Response

Required fields:
- `status`: `completed`, `partial`, `blocked`.
- `deliverables`: concrete outputs produced.
- `risks`: known risks or tradeoffs.
- `next_steps`: clear follow-up actions.

Optional fields:
- `assumptions`
- `needs_decision`

## Rules
1. Planets operate autonomously within their scope.
2. Sun controls user-level preferences and final prioritization.
3. No domain leakage in responses unless explicitly requested.
