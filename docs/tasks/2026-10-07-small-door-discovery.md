# Task spec: small-door discovery

**Triage level:** standard
**Date:** 2026-10-07
**Status:** in review

## Objective

Implement a reviewable first slice: shared capability inventory, bounded MCP
Search/Describe and reduced native exposure.
Keep native defaults, existing approvals and workspace ownership intact.

## Scope

- Solar Client owns the shared inventory and supported profile configuration.
  Discovery mode targets Codex registration and the shared `.agents` surface.
- MCP adds only Search/Describe; existing seven verbs keep original validation.
- Checkpoints, schema changes, rollback changes and responsibility recovery are
  moved to an independent draft; they cannot merge or activate with this MVP.
- Correct reviewer findings: handler arrows, session-level link, JIT claims,
  illustrative numbers, protocol version and maintainer-owned rollout criteria.
- Installed framework, live settings/state, user plans, releases, shared HTTP
  and Code Mode remain outside this implementation.

## Acceptance criteria

- Search and Describe use the same exclusions and namespaces as publication.
- Exact IDs, transversal lookup, references, stale revisions, bounds, traversal
  and symlink containment have isolated tests and explicit refusal behavior.
- Reduced publication verifies actual registered discovery before pruning;
  personal resources survive and native publication can be restored.
- Profile set uses the canonical Client writer, preserving user keys, refreshing
  identity, dropping stale portable keys and retaining atomic failure behavior.
- Unsafe individual skill directories warn and skip without breaking the rest.
- Discovery requires the explicit Codex-only choice and refuses Antigravity sync
  before pruning; native still publishes to all supported clients.
- Existing task/action/send gates and native client publication regressions pass.
- Essential membership and economic/latency rollout targets receive maintainer
  approval before rollout; a fresh real harness comparison remains required.

## Checks and review evidence

- Run per-skill pytest for the modified Client, MCP and Router skills with the
  repository's temporary runtime ownership fixtures.
- Run Client's Codex, Antigravity, skill-exclusion, planet-exclusion and pruning
  shell regressions; preserve the shell runtime guard and test launchctl.
- Package/validate the modified Client, MCP and Router skills; check shell syntax, local Markdown
  targets and `git diff --check`.
- Client profile tests run the supported Client sync against an isolated runtime
  and probe a real registered stdio MCP. They verify dry-run, reduction, rollback,
  unavailable registration, workspace mismatch and legacy settings migration.
- No production activation or measured token-saving percentage is claimed.
- Root link wording preserves the three session levels. The pre-existing root
  and core governance sizes exceed the legacy checklist targets; this focused
  change does not claim a full governance rewrite or full checklist compliance.

Catalog measurement, 2026-10-07: **160 eligible skills, 68,386 bytes** of ID plus
full description; three-essential preview **823 bytes**, without activation.
Fresh full/reduced Codex sessions on identical tasks remain pending. Actual
initial catalog/tokens, input/cache/output, calls, latency, billed cost and
completion quality are **unknown**. Record them using the procedure and matrix
in [the profile reference](../../core/skills/solar-client/references/discovery-profile.md).
The rough 17,000-token conversion at four bytes/token is not provider accounting.

Corrected-scope validation: **297 passed, 1 skipped, 10 subtests passed** across
Client, MCP and Router. All three modified skill packages passed validation;
all five shell publication regressions, shell syntax, local links/fences and
whitespace checks passed. State/async implementations and their
checkpoint tests are absent from the discovery diff.

## Review status

Implementation is available in the draft PR, separated by capability into
commits. The task remains in review until maintainer acceptance. Fresh-session
harness behavior, baseline costs and rollout approval are pending, independently
of passing isolated code checks.

## References

- [Design and implementation contract](../../core/docs/capability-discovery-design.md)
- [Contribution policy](../../CONTRIBUTING.md)
- [Enforcement scope](../solar-scope-and-enforcement.md)
