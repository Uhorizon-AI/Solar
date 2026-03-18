---
name: solar-code
description: >
  Reusable Solar protocol for code modifications. Use when an intention (RFC,
  task, direct instruction) must be converted into a local, human-reviewable
  code change in any repo — including core/ skills. Covers triage, task spec,
  local change, checks, and IDE review. Does not handle PRs, push, or CI/CD.
---

# Solar Code

## Purpose

Convert an intention into a local executable code change without reinventing
the rules each time. Provides a canonical flow and repo adoption contract that
works for planet repos and Solar core skills alike.

## When to Use

Use this skill when:
- A task requires modifying code in any repo target (planet or core/).
- A change needs a defined triage level before touching files.
- A planet or skill needs to declare its repo policy (allowlist, restrictions, checks).

Do not use for:
- PR creation, git push, or GitHub review workflows.
- CI/CD pipeline changes.
- Async workers or queues.
- Multi-repo architectural decisions (use an RFC first).

## Required MCP

None

## Triage

Classify the change before acting:

| Level | Description | Required artifact |
|-------|-------------|-------------------|
| Micro change | 1-2 files, low risk | Clear instruction + repo checks |
| Standard change | Feature or fix with relevant context | Lightweight task spec (Markdown) |
| Multi-repo / high risk | Touches multiple repos or has strategic impact | RFC + task spec + prior review |

**Canonical example of a standard change:** refactor of `core/skills/solar-router/` to Orchestrator/Executor pattern — scoped to one skill, well-defined criteria, task spec already written.

## Workflow

1. **Triage** — classify the change level (micro / standard / multi-repo).
2. **Load repo policy** — read the target repo's policy file before writing anything.
3. **Write task spec** (if standard or above) — use `references/task-spec.md`.
4. **Apply change locally** — edit files in the working tree; do not push.
5. **Run checks** — only commands declared in the repo policy allowlist.
6. **Human review in IDE** — surface the diff; human decides to keep or discard.

**Default mode:** `local-review`. Branch, push, and PR are optional layers added
only when there is evidence they are needed.

## Failure protocol

- If a required check fails: stop, report the failure, do not proceed.
- If the repo policy is missing: ask the user to declare one before writing files.
- If the change scope grows beyond the original triage level: re-triage and get
  explicit approval before continuing.

## Repo adoption contract

Each repo target must declare a policy file. Format: `references/repo-policy.md`.
The policy lives in the planet that operates the repo target.

For core/ skills, the policy is inlined in the skill's own `SKILL.md` or a
dedicated `references/repo-policy.md` inside the skill folder.

## References

- `references/task-spec.md` — minimal task spec template.
- `references/repo-policy.md` — repo policy format for adopting repos.
- `references/local-review-guide.md` — how to use local-review mode.
