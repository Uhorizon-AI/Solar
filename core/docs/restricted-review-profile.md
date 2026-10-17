# Restricted text review: validation blocked

`text_only_review_v1` is not implemented or verified. The reader-profile registry
remains empty. This document records a preflight limitation, not a confinement
claim or permission to enable concurrent readers.

## CLI flag verification

On 2026-10-17, the local Claude Code CLI reported version `2.1.285`. Its
`claude --help` advertises all the proposed flags: `-p`,
`--no-session-persistence`, `--safe-mode`, `--restricted`, `--setting-sources`,
`--tools`, `--strict-mcp-config`, `--mcp-config`, `--settings`, and
`--system-prompt`. This check does not launch inference.

The same help explicitly says that managed settings still apply under both
`--safe-mode` and `--restricted`. The presence of the flags therefore does not
validate the effective configuration.

## Unresolved effective-policy validation

The [CLI reference](https://code.claude.com/docs/en/cli-reference) documents that
safe mode preserves managed policy, including policy-configured hooks.
[Managed settings](https://code.claude.com/docs/en/managed-settings) can come
from remote settings, operating-system policy, managed files and a policy
helper. Consequently, checking project files or a single managed JSON file
cannot establish that the effective policy adds no context or capabilities.

The documented diagnostic `/status` identifies selected settings sources;
`claude doctor` reports invalid entries and fetch outcomes. Neither the inspected
top-level help nor `claude doctor --help` establishes an interface that attests
the complete effective configuration of the subsequent restricted subprocess.
This is a limit of the verification performed, not proof that such an interface
cannot exist. No diagnostic session, inference, credential access or policy
change was performed to resolve it.

Without that verification, registering the adapter as verified would claim more
than the available evidence supports. The approved design calls for
`execution_profile_unsupported` when effective configuration cannot be validated.
Implementation stopped at this precondition; no substitute sandbox, credential
mode, attestation format or policy override is introduced.

## Remaining implementation

The shared launch constructor, canonical envelope and source checks, early
restricted router branch, worker integration, transactional derived children,
profile registration and console changes remain pending. Their contract tests,
two full implementation-suite runs and twenty timing/concurrency repetitions
have not been completed by this documentation change.

The production defaults remain capacity `1` and no enabled reader profiles.
Codex, Cursor Agent and Agy confinement, macOS launchd validation, quality pilot
and capacity rollout belong to later work.
