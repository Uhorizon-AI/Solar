# Reference: Authority Gate (A0–A4)

Canonical router-facing summary of supervised autonomy (fail-closed).

**Framework design:** `core/docs/authority-model.md`  
**Executable rules:** workspace root `AGENTS.md` (Supervised autonomy)

Instance operating contracts under `sun/plans/` may extend the model for a specific installation; they are **not** a dependency of this reference or of `core/` code.

## Levels

- **A0** — observe/read/analyze; no mutations.
- **A1** — prepare in-turn (draft/plan/simulate); no disk persistence, no send.
- **A2** — execute with authority (implicit local scoped, or formal).
- **A3** — execute under a written mandate (`sun/delegations/`); enforced by `scripts/delegation_ctl.py`, see `references/a3-mandates.md`.
- **A4** — escalate; never open-delegate.

## A2 implicit checklist

Explicit local act + clear destination/effect + scoped + not A4 + not external communication.

## A2 formal

Always for third-party communication. Also when scope is unclear, proactive, high-impact, or push/commit/credentials/purchase.

Format:

> I will use **[agent/capability]** with **[skills/integrations]** to **[action]** on **[destination]**. Effect: **[result]**; **[risk/reversibility if needed]**. Do you approve?

## Stacking

Authority first, then domain gate (e.g. ECG). Both must pass.

## Async

`prepare` ≠ `queue`. Gateway auto-queue ACK covers only the declared draft object/scope/effect.

## Worked examples

`references/authority-scenarios.md` (S1–S10).

## Behaviour above the gate

How to turn a signal into closed work (classify, prioritize, verify) lives in `references/signal-orchestration.md` and adds no authority. Planets personalize tone and domain rules; they do not reimplement this gate or enforce A3 mandates.
