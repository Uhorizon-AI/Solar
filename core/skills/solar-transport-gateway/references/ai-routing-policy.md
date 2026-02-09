# AI Routing Policy (v1)

## Objective

Select which AI provider processes each inbound request in a deterministic way.

## Environment key

- `SOLAR_AI_PROVIDER_PRIORITY`

## Recommended defaults

```env
SOLAR_AI_PROVIDER_PRIORITY=codex,claude,gemini
```

## Behavior

- The first provider is the primary one.
- Remaining providers are fallback order if the previous provider fails.
- Supported providers are enforced by the skill implementation, not by `.env`.

## Notes

- Current implementation includes provider stubs (`codex`, `claude`, `gemini`) behind one interface.
- Replace stubs with real provider calls while keeping response contract unchanged.
