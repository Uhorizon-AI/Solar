# Built-in detectors (V1)

| Type | Intent | Notes |
|------|--------|--------|
| `IBAN_INTL` | International IBAN | Matches standard IBAN shape: country code + check digits + BBAN, with optional grouped spaces. |
| `EMAIL` | Email addresses | Standard local@domain pattern. |
| `URL` | http(s) URLs | Greedy to end of token; may truncate odd edge cases. |
| `PHONE_INTL` | International phone | Conservative E.164-like pattern: requires `+` prefix and common separators. |

## Not covered (examples)

Proper names, postal addresses without matching patterns, internal project codes,
national IDs without explicit regex, and obfuscated PII require human review or
future rules.

## Overlap rule

When two patterns match the same region, the earlier registered spec in
`sanitize_context.py` wins if spans overlap after sorting by start position and
length. Adjust `SPECS` order deliberately when extending.

## Mapping file (optional)

Use `--planet <name>` to persist original normalized values to placeholders
across runs. Mapping location per planet:
`planets/<planet>/.solar/security/placeholders.json` and add `.solar/`
to that planet's `.gitignore`.
