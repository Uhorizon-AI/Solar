# Solar: Scope and Enforcement Ceiling

Solar sits between the person and the agentic harness they use. This document
states what Solar is, what it can and cannot enforce, and the rule that keeps
its public claims honest.

It is the source for any statement about Solar's category, control, or
governance. Material that contradicts it is wrong, not an alternative view.

## What Solar is

**Solar is the layer that makes an organization's way of working outlive the
session, the channel, and the AI vendor.**

It is a system of record for *how work is done* — context, procedure, memory and
rules — plus a small runtime that schedules and dispatches that work.

## What Solar is not

Solar is not the reasoning loop. Harnesses — Claude Code, Codex, Cursor,
Antigravity — own the loop, the tools, the effective permissions, and the chat
and voice interfaces. Solar does not replace them and does not compete for their
surface.

Solar is not a model provider. The intelligence comes from the subscriptions the
user already has.

## The two halves

Solar is often described as inert without a harness. That is half true, and the
inaccurate half matters.

| Half | Without a harness | Examples |
|---|---|---|
| **Context and governance** | Inert. Files that do nothing until an agent reads them. | Planets, skills, commands, memory, gates, plans |
| **Runtime** | Keeps running. | LaunchAgent, async task queue, router dispatch, gateway and Telegram transport |

The accurate statement: **without a harness Solar cannot reason, but it keeps
scheduling, dispatching, transporting and recording.** It loses judgment, not
its pulse.

## Enforcement ceiling

Enforcement depends on who owns the point the action passes through.

| Where the action passes | Can Solar refuse it? | Why |
|---|---|---|
| **Solar's own runtime** — router, async queue, gateway, transports | **Yes, fully** | It is Solar's process. Solar performs the call. |
| **Solar's MCP server** — capabilities exposed as tools | **Yes, fully** | Any harness that calls the tool passes Solar's handler. |
| **Inside a harness session** | **Unevenly** | Claude Code exposes hooks and deny rules. Codex and Cursor, partially. Chat apps, not at all. |
| **Anything the user does directly in another app** | **Never** | There is no point of passage. |

Two consequences follow.

**Per-harness hooks can never be the basis of the claim.** The weakest harness
sets the ceiling, and Solar does not control its roadmap.

**The MCP server is the only vendor-independent chokepoint.** A capability
exposed as a tool is gated for every client that calls it, regardless of which
harness the person happens to be using.

### The small door and progressive discovery

The [small-door delivery](../core/docs/capability-discovery-design.md) adds
read-only `solar_search`/`solar_docs` and an opt-in Client profile that reduces the shared
`.agents` catalog. Full native publication remains the default. Antigravity destinations are
refused in discovery mode because its MCP registration is unsupported.

Discovery retrieves instructions; it does not execute them, grant authority or
extend the gate to shell, browser or other native harness routes. Task
mutation handlers write through solar-state; Telegram send and
registered-action handlers have their own effects outside that database.
No per-planet settings tree or physical database per agent is introduced.
Initial catalog bytes can shrink, but total token savings and latency remain
unmeasured until fresh-session comparison. Shared HTTP and Code Mode remain
separate work.

## How Solar launches each client for a task

Solar starts the client as a terminal would and leaves the restrictions to the client's own sandbox. It does not add a sandbox, a private `HOME` or copied credentials: the client uses its real login. A task starts in the workspace, and a folder outside it waits for the user's `task.authorize_run`.

| Client | Default launch | What the client then enforces |
|---|---|---|
| Codex | `--sandbox workspace-write -c approval_policy="never" -C <workspace>` | Shell and patch tool write in the workspace (and in `/tmp` under the measured configuration); `.git/hooks`, `.git/config` and `.codex/` are protected; network is off. |
| Claude | `--permission-mode acceptEdits` with `sandbox.enabled`, `allowUnsandboxedCommands: false` and `failIfUnavailable: true` | Write and Edit stay in the workspace; the shell writes only in the workspace and `$TMPDIR`; `.git/hooks`, `.git/config`, `.claude/settings.json` and `.claude/skills` are protected; the shell has no network except the domains the user allows. The client tools `WebSearch` and `WebFetch` are allowed by Solar's settings and are not limited by the shell sandbox. |
| Cursor | `--sandbox enabled` (no `-f`) | Shell and edit tools write in the workspace (and in `/tmp` under the measured configuration); `.git/hooks`, `.git/config` and `.cursor/mcp.json` are protected; network is off unless `.cursor/sandbox.json` allows it. |
| Antigravity | `--sandbox --mode accept-edits` with `toolPermission: proceed-in-sandbox` | Shell writes only in the workspace (and in `/tmp` under the measured configuration); network is off; a command that needs to leave the sandbox is refused because headless mode cannot approve. The edit tool is stopped outside the workspace by a missing `write_file` permission, not by the OS sandbox. Measured on macOS with Antigravity 1.5.1 only; not verified on Linux, where its documentation says `--sandbox` has no effect when the system cannot provide it. |

The Antigravity row replaces `--dangerously-skip-permissions`, which approved everything: a task wrote in `$HOME`, in `/tmp`, and used the network (measured on 2026-11-05).

Conditions of these measurements: macOS only, a clean workspace, the real `HOME`, Codex with `approval_policy = "never"` (the one Solar passes), and no extra allow rules in the user's own settings. They change what the table promises:

- **Codex** is launched with `approval_policy="never"`, which wins over `~/.codex/config.toml`. It only stops the automatic reviewer from approving an escalation: the user's `workspace-write` settings can still add writable folders, open the network or exclude `/tmp`. Without it, a user with `on-request` and an automatic approvals reviewer let the patch tool write in `$HOME` (measured on 2026-11-05). A task that relied on that reviewer to leave the sandbox now fails.
- **`/tmp`** was writable in Codex 0.165 and Cursor 2026.10.22 on macOS (Claude's shell only gets `$TMPDIR`). It is each client's own rule; Solar does not change it, and the Codex row is the result of the configuration tested, not a guarantee.
- **Claude** keeps the user's own `Edit(...)` rules and `additionalDirectories`; they can allow edits outside the workspace. On Linux the sandbox needs `bubblewrap` and `socat`; without them Claude should refuse to start (`failIfUnavailable`) instead of running the shell unconfined. That refusal is not verified on Linux.
- **Cursor** was measured without `-f` on 2026.10.22, where edits inside the workspace were applied on disk. Cursor's documentation says a non-interactive run without `--force` only proposes edits; the behavior on Linux and in other versions is not measured.

What this does not give, measured on macOS with Codex 0.165, Claude 2.1.318 and Cursor 2026.10.22:

- **The workspace is a work zone.** The clients may edit `AGENTS.md`, `skills/` and `.solar/` inside it; each sandbox protects only its own client's configuration folder, so the other clients' folders, `AGENTS.md`, `skills/` and `.solar/` stay writable. Controlling that is a governance matter, not a sandbox one.
- **Reads and network.** Reads are open. Network is closed by default, so a task that needs a shell command with network must have it allowed in the client's own settings (Claude `sandbox.network.allowedDomains`, Cursor `.cursor/sandbox.json`; Codex is all or nothing).
- **Hard links.** A hard link already inside the workspace that points outside lets a task write the outside file; all three sandboxes allow it.
- **MCP servers and browsers.** The MCP server runs outside the client's shell sandbox, so the Solar MCP works and writes its own audit log, and it is only as limited as its own gate. A shell inside the sandbox cannot start Chrome; start it before the task and use it through its MCP.
- **Overrides.** `SOLAR_ROUTER_<CLIENT>_CMD` replaces the whole command; a replacement that drops the flags above also drops the protection.

## Verbs are gated, nouns are not

A harness keeps its own file tools. If context lives in a directory the harness
can read, it can read it without asking Solar. That is not a defect to fix; it
is the intended shape.

- **Reading** context — planets, skills, memory, rules — stays open.
- **Acting** — writing, sending, executing, spending, committing — goes through
  Solar.

Enforcement becomes real when credentials live in Solar's process rather than in
the workspace. At that point a harness cannot send, publish or spend **through
the routes Solar mediates** without passing the gate, because it has nothing to
do it with. For those routes the rule stops being obeyed and starts being
unavoidable.

### Where the guarantee ends

**Inside it:** anything that passes through Solar's runtime or its MCP server,
using credentials the server holds.

**Outside it:** anything that acts through an already-authenticated browser
session, or with credentials Solar does not hold. Several skills in a typical
workspace drive email, messaging and social platforms this way; what stops them
from sending is a sentence in their own definition, not a mechanism.

**The boundary is drawn by mechanism, not by authorship.** A skill shipped with
Solar and a skill written by the user are equally outside the gate if they act
through a session Solar does not mediate. This is stated so the guarantee can be
verified rather than argued about.

Isolating the user's browser is not the answer: the session is theirs, and the
harness can open its own. The answer is to give Solar a real tool for the same
verb — a gated send, with credentials in the server — so the browser route
becomes unnecessary and the skill can be retired.

## Two modalities and their limits

Solar serves two modalities over the same context layer. Their goals and their
limits differ, and neither may borrow the other's claims.

**Status.** Solar Assistant is what exists today. Solar Orchestrator is a
**design target**: the table and the requirements below describe what it must
guarantee, not what the code enforces now. Identity per person, verified
senders, scoped permissions and revocation are design work tracked in #130 and
#129; they are not implemented. Today the gateway filters Telegram by allowed
chat, not by person, and takes the requester's `user_id` from the message.

| | **Solar Assistant** (today) | **Solar Orchestrator** (design target) |
|---|---|---|
| Where | The user's own computer | A VPS, under a service account separate from its operators |
| Who | One person: builder and approver | Several people, over channels |
| Goal | The same context, rules and memory across harnesses, with several harnesses able to work in parallel on different planets once capacity and reader profiles are enabled | To provide verified requesters, scoped permissions, revocation and an audit trail |
| Approval | In the harness: its own permission prompt or the MCP confirmation | To happen in the channel where the request arrived; not built yet |
| Console | A read-only window; never an approval surface | A read-only window; approval is not a console feature |
| Isolation | None promised: agent and user share one system account | Possible only where the service account is separate from the operators; never a multi-tenant boundary |

**Assistant limits.** It runs under the user's own system account, so it cannot
promise isolation from the agent or from the user. It is not a model, holds no
provider credentials and does not reason. Consent for bounded local work is the
builder's instruction plus the client's own permission.

The harness can use Solar's MCP as a background executor: it keeps a to-do list
in which each item is a task (with subtasks if needed), marks it with
`task.wait` and reacts when it finishes.

- `task.wait` waits at most 90 seconds per call, and Solar does not notify a
  harness whose session has closed (it can notify the configured chat through `notify_when`).
- Parallelism is bounded by the applied capacity policy (`global_capacity`, 1 to
  5, with an optional limit per provider) and by each task's declared access.
  Parallelism is not available by default: the shipped policy has capacity 1 and
  reader profiles disabled, so it has to be raised and the profiles enabled.
- A task that declares no access, or does not run under an enabled and verified
  reader profile for its provider, runs alone, because providers execute with
  their own permissions.
- Each independent task needs its own authorization unless it runs confined or
  belongs to a parent with an approved subtask policy. The exception is a
  question under `ask_readonly_v1`: when the folder and every declared path are inside the workspace it counts as low risk
  and runs without `task.authorize_run`, although it only requests the client's
  read-only mode and does not guarantee it.
- Solar keeps only what must outlive the session; the harness's own list stays
  the harness's.

**Orchestrator requirements (not yet enforced).** Orchestrator must not be
described as controlling these until code does:

- A request is trusted only if the channel proves the sender; a self-asserted
  identity never binds or elevates.
- Content from an unverified sender never reaches a provider.
- The registry of people is not editable by the agent. A separate service
  account makes that possible; it does not establish identity by itself.
- It is not isolation between people: MCP filtering does not isolate files that
  clients read with the same system account, so the first pilot uses shareable
  information only.

**Common to both.**

- Solar cannot refuse what happens outside its own runtime and its MCP server.
- Unattended or deferred execution should run confined, or wait for a Solar
  authorization, with the `ask_readonly_v1` exception above. A builder's "do it"
  approves an idea in a turn, not a run hours later with broad provider
  permissions.
- Solar-side authorization is needed for unattended unconfined runs, third-party
  sends and capability changes; not for reading, and not when a valid
  authorization already covers exactly what will happen.
- No control is claimed that code does not execute (see the honesty rule below).

## The honesty rule

**Solar does not claim a control it does not execute.**

Rules that an agent follows because it read them are *declarative*. They are
useful, auditable and worth having, and they are not enforcement. Public
material must not present them as technical prevention.

Every control claimed in documentation, README or commercial material is
verified against code before publishing. A control that exists only as text is
described as guidance, never as a guarantee.

## Category

**Category: agentic platform. Mechanism: vendor-agnostic harness that runs on
whichever CLI the organization chooses.** Category first, mechanism second.

"Operating system" is an approved one-line analogy — *if an AI agent is an
employee, Solar is the operating system that unifies the team* — and it is not
the category. An operating system is defined by protection, and protection is
precisely what Solar cannot yet provide across every surface. The analogy
explains; it does not classify.

The term becomes accurate for a given capability the day that capability is
gated in Solar's own runtime or MCP server. It is earned per capability, not
claimed for the whole.

## What can be licensed

This follows directly from the ceiling and is the commercial consequence of it.

| Asset | Licensable | Why |
|---|---|---|
| Instruction skills — how to write, review, decide | **No** | Text. It is read and copied. |
| Context, planets, memory format | **No** | Same reason. |
| **Tools that act** — send, publish, execute, spend, commit | **Yes** | They run, they hold the gate, they hold the credentials. |
| **Governance capabilities** — identity, authorized registry, audit trail | **Yes** | Same reason, and they are what organizations buy. |

The catalogue of gated tools is therefore both the enforcement surface and the
inventory of what can sit behind a commercial boundary. Open capability, paid
governance.

## Related

- `docs/solar-nexia-architecture.md` — boundary with NexIA
- `core/docs/authority-model.md` — authority levels and gates
