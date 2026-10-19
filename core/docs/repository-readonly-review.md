# Repository readers alongside a builder

`repository_readonly_v1` lets a reviewer explore all regular tracked files of an
approved Git commit. It complements `text_only_review_v1`, which only receives
selected text. Neither replaces the other. A review always identifies its commit;
it does not attest the builder's current working tree or a subsequent commit.

The production baseline stays capacity **1**, reader profiles **disabled**. This
contract does not authorize inference, account use, spend or deployment. Native
approval is required for creation and queuing; concurrency additionally requires
the [rollout prerequisites](async-rollout.md).

```mermaid
flowchart LR
    B[Builder prepares a commit] --> A[Approve version, model and review scope]
    A --> S[Supervisor reserves places]
    S --> R[Router verifies ID, token and approved inputs]
    R --> C[Private copy of committed files per reviewer]
    C --> P[Read-only CLI review]
    P --> F[Version-labelled findings]
    F --> Y[One parent synthesis after terminal children]
    B --> N[Builder continues separately on the next version]
```

## Ownership of the contract

- **Tasks/MCP** store the approved model, provider, profile, access declaration
  and canonical versioned inputs. A draft never queues itself. Material edits
  withdraw approval; revisions need fresh review inputs.
- **State/supervisor** retain the common claim, capacity, provenance, recovery,
  cancellation and synthesis rules. No schema migration is added.
- **Router** composes and validates inputs, creates private snapshots, inspects
  the CLI and builds provider-specific commands. Both run and stream use this
  boundary before interactive history, continuity or JIT context loading.
- **The CLI** performs the actual review with its installed authentication.
  Solar does not call a model API directly or add a billing account. CLI account
  limits and billing mode still need explicit operator validation.

The builder can be an interactive author outside the async pool. Async tasks
with write access remain exclusive under the existing scheduler. This change
allows multiple approved readers; it does not add concurrent async writers or
promise quota reserved for the interactive builder.

## Version and snapshot boundary

Prepare an existing full 40/64-character commit object ID, not HEAD, a branch or
a tag. The repository must be its physical root. Router reads Git objects without
checkout, hooks, replace objects, global/system Git configuration, or lazy fetch.
The full manifest covers repository, commit/tree, exact model/provider/prompts,
file paths, modes represented by the accepted tree entries, object IDs, SHA-256
content hashes and sizes. File execution bits are deliberately not reproduced.

The initial bound is 10,000 regular files and 32 MiB total. Symlinks, submodules,
unsafe paths, root CLI configuration directories and tracked credential-like
files are rejected, not silently omitted. There are no filters or repository
setup scripts. Choose another reviewed commit if it contains unsupported files.

At execution Router revalidates approved inputs, materializes all files into a
private temporary directory without `.git`, rechecks the ID/token and snapshot,
and invokes the selected CLI there. Each invocation receives an independent
copy of the same version. Uncommitted builder edits and newer commits do not
change it. The source repository is never given as the review cwd. A result is
labelled `Reviewed commit: <full ID>` by Solar, not inferred from model prose.

Right after it Solar records `Repository HEAD when the review finished: <ID>`
with `same as` or `differs from the reviewed commit`, or `unknown` when HEAD
cannot be read (unborn HEAD, Git error or timeout). A detached HEAD is reported
like any other. This is a record, never a gate: a differing HEAD is the expected
case while the builder continues, the line is not part of the manifest or
digest, and a failure to read it never fails or alters the review. The approved
prompt still carries the repository path, and the sandbox does not stop the CLI
from reading outside the snapshot, so the model may run Git on the live
repository and comment on HEAD. Such statements are model commentary, not a
freshness check; only the Solar-written lines above are authoritative.

The copy is checked for unexpected files, symlinks and changed content after
execution, and removed in `finally`. A mismatch invalidates the result. This is
defense in depth, not the mechanism that prevents writes. The CLI restrictions
below prevent writes; a writable temporary copy alone is not a sandbox.

This is a repository review, not a general machine read-isolation guarantee.
The CLI's OS/runtime/authentication reads still exist. Do not use this profile
as an attestation that no file outside the snapshot can be read, or that a
review result proves absence of hidden provider-side context. Hostile repository
instructions remain untrusted evidence, even when the CLI discovers them.

## Provider implementations and stop conditions

| Provider | Implemented boundary | Status |
|---|---|---|
| Claude | Existing help/managed-policy preflight; safe/restricted modes, empty setting sources, only `Read,Glob,Grep`, plan permissions, empty strict MCP and disabled hooks; exact model and fixed system prompt | Implemented; real quality pilot still required |
| Codex | Private config home with only a mode-0600 copy of the CLI auth file, `exec --sandbox read-only`, approval policy `never`, ignored user config/rules, ephemeral JSONL output used only for failure signals, the completed-turn marker and usage (it has no phase/channel field), the review taken solely from `--output-last-message` under a requested `--output-schema` and validated by Solar (exactly one non-empty `review` string; anything else fails), explicit empty integration registries and disabled hooks/plugins/apps/agent/browser/computer/image-generation and skill-install/discovery features | Implemented; effective-config preflight and real sandbox evidence required |
| Cursor `agent` | Private HOME/config/data and subscription-token file store, `--mode ask --sandbox enabled`, deny writes/shell/MCP/web, no inherited hooks/plugins, external OS write guard | Implemented; real model pilot still required |
| Antigravity `agy` | Private HOME with standalone subscription token only, `--mode plan --sandbox --disable-slash-commands`, strict permissions denying writes/commands/MCP/web, external OS write guard | Implemented; real model pilot still required |

### Optional Codex review evidence

The Codex JSONL and final-message file live in a launch directory that is
removed when the launch ends. To keep evidence for attributing a failed pilot,
set `SOLAR_ROUTER_REVIEW_EVIDENCE_DIR` to an absolute directory (unset by
default: nothing is kept). Each Codex review then writes one run directory
`<UTC time>-<pid>-<random>/` with `events.jsonl`, `last-message.json` (when the
CLI wrote one) and `meta.json` (provider, model id, reviewed commit, exit code,
timeout, truncation flags; never the prompt). The model and commit tie a folder
to the task that produced it. It is taken for completed, failed and timed-out
launches alike.

The variable must be set in the environment of the process that executes the
review (the supervisor/worker), not in the session that launches the task.

- The root and run directories are mode `0700`, files `0600`. Solar creates the
  root with `0700` but never changes the mode of a pre-existing directory: a
  symlinked or foreign-owned root, or an existing one accessible to group or
  others, is refused and nothing is captured (one line on stderr). Create it
  with `mkdir -m 700 <path>` (a plain `mkdir` gives `0755` on macOS), or let
  Solar create it.
- Retention: the newest `SOLAR_ROUTER_REVIEW_EVIDENCE_KEEP` runs (default `10`,
  maximum `100`; `0` or lower is raised to `1`); older Solar-named run directories are deleted, other entries
  are left alone. Each file is cut at 8 MiB on a character boundary.
- Never written: argv (it carries the prompt), env, stderr, `auth.json` or its
  contents. Values of environment variables whose names end in `_KEY`, `_TOKEN`,
  `_SECRET`, `_PASSWORD` or `_CREDENTIAL` (in the review environment or the
  supervisor's), the copied auth file's values and JWT/`sk-` shaped strings are
  replaced with `[REDACTED]`; an equal value that is also harmless text is
  masked too. This is pattern-based. `events.jsonl` contains model output and
  the reads of the reviewed repository, so it is sensitive data beyond
  credentials: restrict access and delete it after use.
- Capture is diagnostic only and never changes the outcome: any capture error
  is logged as a one-line warning and ignored, and the result is still decided
  solely by the validated final message.

### Cursor and Antigravity host guards

These adapters supplement the CLI read-only/planning modes with an external OS
write boundary. On macOS, `sandbox-exec` denies file writes except in disposable
CLI state, and explicitly denies writes to the repository snapshot. On Linux,
`bubblewrap` (`bwrap`) mounts the host and snapshot read-only and binds only the
private CLI state writable. Missing helpers, unavailable kernel/user-namespace
support, or a failed write probe refuse launch; there is no unguarded fallback.
Linux deployments must install bubblewrap before enabling these readers.
The real account's CLI/config trees are also denied or hidden, preventing a CLI
from bypassing HOME redirection by resolving the home through the OS user database.

Every invocation probes the actual boundary before starting the CLI: reading an
existing snapshot file must succeed, overwriting it, creating a snapshot file,
and overwriting a separate disposable host sentinel must fail. Private state
writes must succeed. Help is then checked under the same guard:

- every required option must be declared (an example or another option's
  description does not count);
- every value Solar passes (`--mode`, `--sandbox` and `--output-format` where
  they take values) must be listed in that option's own block, in a form seen in
  the real Cursor and Antigravity help: `Values:`/`Modes:`/`Formats:` lists,
  `(choices: "a", "b")`, `a | b`, `[a|b]` or a closing `(a, b)` note;
- ignored: `Examples:`/`Usage:` sections, options nested in another option's
  description, prose, `e.g.` and lists introduced by a negation (`none of`,
  `not one of`, `removed`); unknown layouts are refused, never guessed. Colour
  is disabled and ANSI codes are stripped; details in
  `cli_capabilities.advertised_values`;
- the CLI version is recorded (`review_preflight.version` in the result and audit
  log) and never blocks launch.

A refusal carries `error_detail` with `provider`, `stage`, `reason` and, for help
checks, `option`. Reasons: `required_option_missing`, `required_value_unadvertised`,
`help_failed`, `help_timeout`, `help_unavailable`, `help_format_unknown`,
`managed_policy_present`, `credentials_unavailable`, `boundary_unavailable`,
`write_guard_probe_failed`, `write_guard_probe_timeout`, `provider_unsupported`.
A help text proves neither the effective configuration nor that a guard works. These adapters
do not claim a doctor-style effective/cloud-policy attestation; their stronger
write boundary is enforced externally. Network access remains available for the
provider, so this is not an OS network-egress boundary or proof of absent
provider-side integrations. A real model pilot must also verify tool refusals.

Cursor receives `CURSOR_CONFIG_DIR`, `CURSOR_DATA_DIR`, a private HOME/XDG tree,
and `AGENT_CLI_CREDENTIAL_STORE=file`. `--trust` satisfies the CLI headless
workspace gate for the disposable snapshot only; it does not approve MCPs or
trust repository instructions as authority. Its trust record stays in the
private HOME and is deleted on exit. Only subscription access/refresh tokens
are copied, not API keys, settings, hooks, plugins, approvals or history. On
macOS the two named Cursor keychain entries can be read into that private file;
no keychain writes are made. The file-store switch is not documented in CLI
help, so help discovery cannot confirm it and no version list gates it. It was
inspected in Cursor `2026.10.14-0f9edde`; a later release that ignored it could
read or refresh the user's real keychain entries. That residual risk is accepted
for now and stays unverified without a real run; do not read it as a guarantee.
Known machine-managed Cursor directories cause a
refusal rather than overriding administrator policy. Enterprise/team accounts
and hidden provider-side context are not accredited by these help checks.

Agy receives a private HOME/XDG tree with only
`.gemini/jetski-standalone-oauth-token`; no Gemini API/ADC credentials, CLI state,
plugins, MCP configuration or hooks are copied. Its private settings use strict
permissions with explicit global write, command, unsandboxed-command, MCP and
web denials. Slash-command/skill expansion is disabled. Both adapters remove
ambient API keys, endpoint overrides, IDE/remote-control and shell injection
variables. Token refresh stays in the disposable copy and is not copied back;
subscription account validity and token lifecycle still need operator validation.

Root `.agents` and `.gemini` trees are rejected as operational configuration,
alongside the existing CLI configuration exclusions. The approved system rules
and user input are combined into one fixed prompt for these CLIs. Their native
JSON terminal states are checked; failures, unknown states or missing responses
cannot become successful reviews. Run and stream use the same constructor.

The inference-free host proof can check all three CLI/OS guards:

```bash
SOLAR_TEST_REPOSITORY_CLI=1 python3 core/tests/support/repository_review_cli_probe.py --provider all
```

Cursor/Agy checks use synthetic credentials and execute only `--help`, plus
local OS guard probes. They do not demonstrate model quality, authentication,
MCP refusal during inference, account headroom or billing behavior.

Sources: [Cursor configuration](https://cursor.com/docs/cli/reference/configuration),
[Cursor permissions](https://cursor.com/docs/cli/reference/permissions),
[Antigravity permissions](https://antigravity.google/docs/permissions?tab=cli),
[Antigravity headless output](https://antigravity.google/docs/cli/headless/).

CLI configuration overrides and extra execution flags are refused. Account
credentials are never put in manifests, prompts or captured results. Codex
currently requires file-backed CLI auth; the private copy is deleted with its
config home. Its auth mechanism may refresh the private credential copy; it is
not copied back to the original. Keyring-only authentication is unsupported in
this initial adapter. Review account/token lifecycle before production use.

Codex preflight uses `exec --help` and the same config overrides in `doctor
--json`. Its effective config must include cloud-policy inspection, zero MCP
servers, none of the prohibited features, approval policy `Never`, and no
managed filesystem source. Missing/changed diagnostic fields or unreadable
policy refuse launch. Overall network diagnostics may fail without changing
these specific config checks; model access is not inferred from doctor output.
Never weaken this parser to turn an unsupported host into success.

The inspected local CLI versions were Codex 0.162.1 and Claude Code 2.1.285.
The [Codex configuration reference](https://developers.openai.com/codex/config-reference)
and [managed configuration](https://developers.openai.com/codex/enterprise/managed-configuration)
explain why sandbox selection alone is insufficient for hooks/MCP. Help and
synthetic tests establish command compatibility, not real model review quality.
Claude exposes file readers only; Codex can use its sandboxed shell. The prompt
forbids executing project code, but this is not a separate OS execution ban.

## Native task preparation

`task.create` and `task.update` accept a closed `review` object. Router composes
the canonical manifest; arbitrary commands, environment or flags cannot be
supplied. Explicit provider and instructions are required with every new review.
For an update, also pass the stored `task_id` and `expected_row_version`.

```json
{
  "operation": "task.create",
  "arguments": {
    "title": "Review committed implementation",
    "instructions": "Identify correctness regressions and cite affected files.",
    "provider": "codex",
    "review": {
      "profile": "repository_readonly_v1",
      "model": "EXACT_APPROVED_MODEL_ID",
      "repository": "/absolute/approved/repository",
      "commit": "FULL_APPROVED_COMMIT_OBJECT_ID",
      "rules": ["Separate findings from uncertainty."]
    }
  }
}
```

Default access is read-only for that repository. An explicit access declaration
must be read-only and contain that root. Review creation returns a draft and row
version. Inspect and use ordinary `task.approve` for that exact stored version.
The native confirmation shows profile, model, repository and commit both when
preparing and when approving. Changing provider/model/version/inputs is a
material edit; a queued task returns to draft. No profile is globally enabled by
creating or approving a task: it runs exclusively while profiles are disabled.

Existing packet reviews can use the same entry point with `profile:
text_only_review_v1`, exact model and `evidence` entries containing `source_path`,
`content` and raw-byte `sha256`. Repository fields and packet evidence cannot be
mixed. Packet composition and its no-tools provider restrictions are unchanged.

## One builder and bounded derived reviews

A parent task may instead supply `review_batch` with one repository/commit and
one to five explicit reviews. Every item names a unique key/title, exact
instructions, provider, model and optional rules. The parent must name
`object`, `scope` and `effect`. MCP creates the approved catalog and bounded
subtask policy; the child access is read-only on that repository. The parent
keeps its own access policy and ordinary execution mode.

```json
"review_batch": {
  "repository": "/absolute/approved/repository",
  "commit": "FULL_APPROVED_COMMIT_OBJECT_ID",
  "reviews": [
    {"key":"correctness", "title":"Correctness review", "instructions":"Find correctness bugs.", "provider":"codex", "model":"EXACT_MODEL_ID"},
    {"key":"regressions", "title":"Regression review", "instructions":"Find regressions.", "provider":"claude", "model":"EXACT_MODEL_ID"},
    {"key":"tests", "title":"Test review", "instructions":"Find test coverage gaps.", "provider":"codex", "model":"EXACT_MODEL_ID"}
  ]
}
```

The worker supplies the exact approved declarations to the parent's prompt.
The parent requests them through its existing `<subtasks>` response. State
materializes the complete batch atomically/idempotently with derived child
approvals. No model can select a different commit, add a reviewer or broaden its
scope. Children use the common pool; the parent waits and synthesizes once.
Revocation, cancellation, missing dependencies and uncertain synthesis keep their
existing stop conditions.

## Verification and rollout

Tests use disposable Git repos, runtimes and provider doubles. Integrated tests
apply policy through native operations in the test runtime, release three/five
same-provider workers through a durable-event barrier, assert overlap, one
synthesis and no duplicate dispatch. They do not establish account headroom.

The separate inference-free Codex sandbox probe is opt-in:

```sh
SOLAR_TEST_REPOSITORY_CLI=1 python3 core/tests/support/repository_review_cli_probe.py
```

It uses a temporary config home without credentials, invokes no model, checks
reads succeed and writes fail both inside and outside the cwd, checks original
bytes, and removes its temporary directory. Run on macOS/Linux with a compatible
CLI. A skipped probe is not evidence. This complements constructor diagnostics;
it does not simulate a whole model invocation or attest Claude's behavior.

Before enabling this profile, obtain the real useful-review pilot, versioned CLI
policy evidence, account limits and bounded observation, then propose capacity
3 and later 5 through the existing runbook. Include `repository_readonly_v1`
explicitly in `enabled_reader_profiles` only after that separate authorization.
Keep `text_only_review_v1` available for fixed evidence evaluations. Capacity 1
with profiles disabled remains the default and the safe operational rollback.
