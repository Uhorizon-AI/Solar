# Reference: Async Task Execution Consent

This contract applies when `solar-async-tasks` executes a task through
`solar-router` with `channel=async-task` and `mode=direct_only`.

It aligns with supervised autonomy (A0–A4): queued execution is scoped
A2 for the **declared** body and artifacts; sensitive acts remain A2 formal.

## Consent Levels

| Level | Allowed without extra approval | Requires explicit approval (A2 formal) |
|---|---|---|
| Approved execution | Execute the approved task body within declared object/scope/effect. | Changing the task objective or scope. |
| Declared artifacts | Write files or `## Result` output explicitly declared by the task body. | Writing outside declared output paths. |
| Runtime state | Write task logs and normal lifecycle state under `sun/runtime/async-tasks/`. | Deleting or rewriting unrelated runtime state. |
| Sensitive action | None by default. | External sends, destructive deletes, credentials, irreversible actions, and out-of-scope mutations. |

## Prepare ≠ queue

- Creating or planning a draft is **A1/preparation**, not execution authority.
- Moving to `queued/` via `approve.sh` (or gateway auto-queue of a scoped draft) is the A2 boundary for the declared body.
- On IDE / non-gateway channels: do not activate/queue without explicit confirmation when the user only asked to prepare.
- On Telegram/n8n: `async_draft_created` may auto-queue only when the draft states object, scope, and effect. That ACK is **not** authority for external sends inside the run.

## Practical Rule

Queued/active status means the task has already been approved to execute its
body. The executing AI should not stop only because the body writes the artifact
it explicitly requested. It must still stop for sensitive or out-of-scope actions
and apply domain gates (e.g. External Communication Gate) before any third-party send.

## Evidence

Material actions should leave proportional evidence in task logs: timestamp,
intention, authority used (queued A2 / A2 formal / A3), agent, systems, result,
validation, and error/rollback if any.

## Examples

- A weekly Solar proposal task that writes `sun/plans/YYYY/MM/<file>.md` may write
  that plan if the task body declares the path.
- A Telegram task may draft a message, but sending it still requires A2 formal
  (and domain gate when applicable) even if the task is queued.
- A cleanup task may remove files only inside its declared cleanup scope. Removing
  unrelated files or broad directories requires explicit approval.
