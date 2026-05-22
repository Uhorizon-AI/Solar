# JIT Delegation Protocol

When receiving a task, the AI must self-evaluate before responding:

## 1. Self-Assessment

Check if available agents, skills, and commands are sufficient for the task:
- **Sufficient** → execute directly.
- **Insufficient or uncertain** → delegate to `solar-router` as a subprocess.
- **Requires external resources** (internet, system binaries, MCPs, long-running operations) → create an async task via `solar-async-tasks` (create → plan → approve → queue). The system executes it automatically via the Solar LaunchAgent. Do NOT run `run_worker.sh` manually or attempt direct execution.

## 2. Validation Gate

Before delegating to `solar-router`:
- Task is **read / analysis only** → delegate automatically.
- Task **modifies data or sends messages** → show the user which agent + skills will be used and wait for explicit approval before proceeding.

Exception: tasks already executing from `solar-async-tasks` with `channel=async-task`
are approved to run their task body and write declared artifacts. They still require
explicit approval for external sends, destructive deletes, credentials, irreversible
actions, or changes outside the declared task scope. See
`core/skills/solar-async-tasks/references/execution-consent.md`.

## 3. Subprocess Invocation

Call `solar-router` using the v3 contract via stdin. Always use `mode: direct_only` and `channel: other` in subprocesses to prevent recursion:

```bash
echo '{
  "request_id": "<uuid>",
  "session_id": "<session_id>",
  "user_id": "<user_id>",
  "text": "<task description>",
  "channel": "other",
  "mode": "direct_only",
  "provider": "<claude|gemini|codex>",
  "metadata": {
    "agent": "<agent-name or null>",
    "skills": ["<skill-1>", "<skill-2>"],
    "planet": "<planet-name>"
  }
}' | python3 core/skills/solar-router/scripts/run_router.py
```

For full field rules, metadata format, and invariants see `core/skills/solar-router/references/routing-policy.md`.

## 4. When No Agent or Skill Exists

Set `metadata.agent` to `null` — the router generates a role JIT. Frequently used JIT resources are persisted to the correct planet and synced via `sync-clients.sh`.
