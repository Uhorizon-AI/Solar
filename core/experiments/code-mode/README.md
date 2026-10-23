# Solar Code Mode: evaluation MVP

This opt-in experiment makes the proposed mechanism executable. It is a separate
stdio MCP server with **search** and **execute**, not a new production Solar tool.
Only generated fixture data is reachable. It does not launch AI clients, import
Solar state, read credentials, register skills or change the installed MCP.

## Run and inspect

Prerequisites: Python 3.10+ and Deno (tested with Deno 2.9.6). Deno is an additional
runtime dependency of this experiment, not a new requirement for normal Solar.
No Python packages, npm packages or remote imports are needed for the demo.

From the repository root:

```bash
python3 core/experiments/code-mode/demo.py
uv run --project core/tests pytest core/tests/experiments/test_code_mode.py -q
```

The demo prints the discovered schemas, the exact JavaScript, its result, the
host-recorded calls and a reproducible comparison. It makes no model calls.
The code is supplied explicitly; a real LLM generating it has not been evaluated.

For an optional client-local stdio MCP connection, launch:

```bash
python3 /absolute/path/to/checkout/core/experiments/code-mode/server.py
```

Do not replace the normal Solar MCP entry. No client configuration is changed by
this PR. The wire test exercises initialize, tools/list, search and execute through
the actual subprocess transport.

## What happens

```mermaid
sequenceDiagram
    participant M as Model or test client
    participant H as Experimental MCP host (Python)
    participant W as Restricted JavaScript worker (Deno)
    M->>H: search({query: "customer invoice"})
    H-->>M: Method descriptions, schemas and TypeScript signatures
    M->>H: execute({code: "..."})
    H->>W: Code and allowlisted method names
    W->>H: getCustomer({customerId: 123})
    H->>H: Validate method and exact argument types; record decision
    H-->>W: Synthetic customer
    W->>H: getInvoices({customerId: 123})
    H->>H: Validate and record again
    H-->>W: 40 synthetic invoices
    W->>W: Filter pending invoices and sum cents
    W-->>H: Summary
    H-->>M: Summary and host-recorded trace
```

Example execution tool arguments:

```json
{"code":"const c = await solar.getCustomer({customerId:123}); const rows = await solar.getInvoices({customerId:c.id}); const pending = rows.filter(x => x.status === 'pending'); return {customer:c.name, pendingCount:pending.length, totalCents:pending.reduce((s,x) => s+x.amountCents,0)};"}
```

The result is `Example Customer`, 20 pending invoices and `240000` EUR cents
(EUR 2,400). Intermediate invoice fields do not return to the client unless the
supplied code explicitly returns them. Code Mode reduces context by convention,
not by enforcing a data-loss-prevention policy.

## Measured comparison and its limits

Observed locally on the fixture: **4,740 bytes** of direct data responses versus
**307 bytes** for the Code Mode response, including its trace. Both make the same
two backend calls. Execution tool invocations go from two to one. Search is
excluded equally; the measurement counts compact JSON payloads, not MCP envelopes,
request code, schemas, reasoning, model tokens, cost or end-to-end latency.

This deliberately exercises a favorable case: fetching rows and aggregating them.
A dedicated `getPendingInvoiceSummary` tool or existing skill script could return
the same summary without arbitrary JavaScript. The experiment therefore proves
composability and output reduction for this fixture, not that Code Mode is cheaper
than a well-designed existing tool or worth adopting in Solar.

## Boundaries exercised

- Host owns the fixture data and allowlist. Worker receives method names and only
  the responses it requests. RPC requests are validated in Python on every call.
- Fresh Deno process, empty environment apart from runtime controls, temporary
  working directory, no project config, no remote/npm imports, no prompts.
- File read/write, environment, network, subprocess, system and FFI permissions
  are explicitly denied in the process; the Worker has `permissions: "none"`.
- 8 KiB code, 8 host calls, 64 KiB cumulative worker protocol output, 3-second
  wall deadline. The host terminates the process in cleanup, including on error.
- V8 old-space target is 64 MiB. This is **not a hard total-process memory limit**.
  There is no cgroup/microVM, concurrency admission or production sandbox claim.
- The host generates trace IDs and records actual method decisions. Traces are
  returned in the response, not persisted in Solar's gate audit. Worker-reported
  results remain untrusted and can be fabricated by submitted code.
- Ordinary console logs are routed to discarded stderr, outside the RPC protocol.
  Log capture and presentation are not implemented.
- Unknown methods, invalid arguments, syntax errors, blocked access and time/call/
  output limits return errors. A caller may correct code and retry reads safely;
  no mutation retry semantics are implemented.

Deno's worker permission option is unstable and explicitly enabled. See the
[permission model](https://docs.deno.com/runtime/fundamentals/security/) and
[worker option flag](https://docs.deno.com/runtime/reference/cli/unstable_flags/#--unstable-worker-options).
Negative tests validate the listed probes on this host; they are not a proof
against every sandbox escape or denial of service. Keep this experiment on fixture
data until the runtime boundary has a dedicated security review.

## Production changes this would require

| Area | MVP | Required before adopting |
|---|---|---|
| Discovery | Two fixture signatures and closed schemas | Derive callable methods from the real registered contracts; version the catalog and validate outputs |
| Executor | Separate `execute(code)` tool | Choose a supported sandbox/dependency policy; expose an opt-in operation such as `code.run` without breaking the existing three tools |
| Bridge | Python fixture allowlist | Adapter to existing handlers and their gates; discovery never grants authority |
| Authority | Fixed synthetic read-only scope | Check caller identity, object, destination and permission for every dynamic call; never let code mint approval |
| Audit | Returned host trace | Persist code reference, outcomes and linked child operation traces in the canonical audit, with redaction |
| Limits | Per-execution timeout, calls and bytes | Total memory/process admission, cancellation, aggregate budgets, output schemas and deployment policy |
| Effects | None | Concrete approvals, pause/resume and idempotency before allowing mutations or sends |

Integration points to review are `core/skills/solar-mcp/scripts/mcp_server.py`
(tool schema/dispatch), `operations.py` (registry/contracts), and `mcp_gate.py`
(authority/audit). Those files are deliberately untouched. A real adapter must
reuse the gate, not call protected handlers directly. This MVP does **not** prove
compatibility with native confirmation or production task execution.

## Relationship to ask

Code Mode could compose several client consultations behind one execution call.
It cannot itself provide model sessions, launch profiles, provider limits, queue
admission, cancellation or durable task recovery. Those remain Solar task/router
responsibilities. A JavaScript sandbox does not confine an AI CLI launched outside
it. `Promise.all` does not override the scheduler's current serialization of ask.

Removing the extra ask flag by deriving the launch profile from declared read
access remains an independent simplification. This experiment does not change it.

## Decision after this PR

Recommendation: keep experimental until a real, repeated Solar workflow needs
dynamic composition. For that workflow compare current tools, a dedicated script
and Code Mode on identical inputs and outputs. Measure complete request/response
tokens, latency including sandbox startup, correctness, recovery and maintenance
cost. Advance only if the benefit survives those comparisons and each bridged
operation keeps its existing authority boundary. Otherwise retain the current
tools and close the experiment without installing a new runtime.
