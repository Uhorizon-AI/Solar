# Reference: Cross-channel continuity

## Stores (federated — do not replace)

| Layer | Path | Role |
|---|---|---|
| Ephemeral turns | `sun/runtime/router/conversations/*.jsonl` | Raw chat per conversation_id |
| Rolling channel summary | `…/*-summary.txt` | Compact per-conversation continuity |
| Canonical intention | `sun/runtime/continuity/active.json` | Cross-channel shared intention |
| Machine tasks | `sun/runtime/async-tasks/` | Executable deferred work |
| Human attention | `sun/daily-log/`, planet `operations/` | Blockers / commitments |
| Stable memory | `sun/MEMORY.md` | Operational learnings only (not a task board) |
| Plans | `sun/plans/` | Design / RFCs (not runtime state) |

## `active.json` schema

```json
{
  "intention_id": "uuid-or-slug",
  "active_task": "one-line objective",
  "decisions": ["…"],
  "completed_actions": ["…"],
  "pending": ["…"],
  "constraints": ["…"],
  "next_owner": "<workspace owner>|Solar|<agent>",
  "updated_at": "ISO-8601 Z",
  "channels_seen": ["telegram", "other"]
}
```

No secrets. No full message dumps. Promote only durable decisions to `sun/MEMORY.md`.

## Rules

1. Channel changes; intention does not.
2. Last explicit instruction wins over incompatible prior context.
3. Classify new messages as replace / extend / query before acting.
4. Before creating task/event/message/artifact: check exists / in progress / closed / same goal.
5. Router injects `active.json` into prompts when present and lightly syncs `active_task` from `<solar_summary>`.

## IDE / agent updates

```bash
python3 core/skills/solar-router/scripts/continuity_cli.py status
python3 core/skills/solar-router/scripts/continuity_cli.py set --task "…" --owner Solar --pending "…"
python3 core/skills/solar-router/scripts/continuity_cli.py clear
```
