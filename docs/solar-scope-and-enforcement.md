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
