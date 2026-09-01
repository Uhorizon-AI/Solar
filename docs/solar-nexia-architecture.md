# Solar and NexIA: Architecture Boundary

Solar and NexIA serve different operating environments. They can exchange
explicitly selected, portable assets in the future, but they are not one
runtime and do not synchronize automatically.

## System boundaries

| System | Responsibility |
|--------|----------------|
| **Solar** | Local AI operating system for composing, validating, and operating work across personal or domain-specific contexts. |
| **NexIA** | Governed organizational platform for reviewing, configuring, publishing, and operating AI capabilities. |
| **NexIA Website** | User-facing NexIA layer where people manage agents, skills, documents, projects, processes, and approvals. |
| **MCP+** | NexIA backend and operational core for organization boundaries, permissions, capabilities, connectors, execution, audit, and runtime services. |

Solar runs from a local workspace and its installed framework. NexIA runs with
organization-specific identity, permissions, data, and operational controls.
Neither runtime is a substitute for the other.

## Promotion, not synchronization

A mature Solar asset may eventually be promoted to NexIA as a draft. Promotion
is an explicit, reviewable handoff:

1. Select a portable Solar asset.
2. Inspect it for local-only dependencies and sensitive context.
3. Prepare a NexIA-compatible representation.
4. Create or update a draft after explicit approval.
5. Review, configure, and publish separately inside NexIA.

Promotion never publishes or executes the asset automatically. There is no
background or two-way synchronization contract.

## Data and authority boundary

A Solar-to-NexIA handoff must not transfer:

- personal memory, preferences, logs, or task history;
- secrets, credentials, or local subscription access;
- arbitrary local files or machine-specific paths;
- permissions or authority inferred from the local workspace.

NexIA applies its own organization membership, access control, validation,
approval, audit, and publication rules. A valid Solar asset is input to that
governed lifecycle, not permission to bypass it.

## Current implementation status

The architecture boundary is defined, but the promotion bridge is not part of
the current Solar runtime. Until that bridge is implemented and approved,
moving an asset from Solar to NexIA remains a deliberate manual process.
