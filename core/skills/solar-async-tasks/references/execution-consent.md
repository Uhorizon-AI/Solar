# Reference: Async Task Execution Consent

This contract applies when `solar-async-tasks` executes a task through
`solar-router` with `channel=async-task` and `mode=direct_only`.

## Consent Levels

| Level | Allowed without extra approval | Requires explicit approval |
|---|---|---|
| Approved execution | Execute the approved task body. | Changing the task objective or scope. |
| Declared artifacts | Write files or `## Result` output explicitly declared by the task body. | Writing outside declared output paths. |
| Runtime state | Write task logs and normal lifecycle state under `sun/runtime/async-tasks/`. | Deleting or rewriting unrelated runtime state. |
| Sensitive action | None by default. | External sends, destructive deletes, credentials, irreversible actions, and out-of-scope mutations. |

## Practical Rule

Queued/active status means the task has already been approved to execute its
body. The executing AI should not stop only because the body writes the artifact
it explicitly requested. It must still stop for sensitive or out-of-scope actions.

## Examples

- A weekly Solar proposal task that writes `sun/plans/YYYY/MM/<file>.md` may write
  that plan if the task body declares the path.
- A Telegram task may draft a message, but sending it still requires the task body
  to include an explicit send gate or prior approval.
- A cleanup task may remove files only inside its declared cleanup scope. Removing
  unrelated files or broad directories requires explicit approval.
