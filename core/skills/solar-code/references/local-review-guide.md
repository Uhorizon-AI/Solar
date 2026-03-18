# Local review guide

## What is local-review mode

The agent writes changes directly to the working tree. The human reviews the
diff in the IDE and decides to keep or discard. No branch, no push, no PR
unless explicitly requested.

## Flow

1. Agent applies changes to local files.
2. Agent runs only checks from the repo policy allowlist.
3. Agent surfaces a summary of modified files and check results.
4. Human reviews in IDE.
5. Human decides:
   - **Keep:** commit locally if desired; agent does not push unless asked.
   - **Discard:** run `git restore <modified-files>` to reset only the files
     touched by the agent. Do not use `git checkout .` or `git restore .` —
     those discard unrelated human changes.

## When to add a branch

Only when the human explicitly asks for one, or when the repo policy requires it.
Default is to work directly on the current branch.

## When to push or create a PR

Never by default. Only when the human explicitly requests it after reviewing
the local diff.

## Signals that local-review is done

- All required checks from the repo policy pass.
- Human has seen the diff in the IDE.
- Human has made an explicit keep/discard decision.
