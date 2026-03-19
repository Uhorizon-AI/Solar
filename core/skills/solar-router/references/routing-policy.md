# AI Routing Policy (v3)

## Objective

`solar-router` is the **single source of truth** for all AI execution in Solar:
- Provider selection and fallback live only in the router.
- Async routing policy (`direct_reply` vs `async_draft_created`) lives only in the router.
- Consumers (transport-gateway, async-tasks) delegate 100% to the router and consume the structured v3 response.

All providers (Codex, Claude, Gemini, Agent) run with the same repo context: working directory = Solar repo root, so they see `sun/`, `planets/`, `core/`, and `AGENTS.md`.

## Internal architecture

`solar-router` is split into three layers. The public contract (stdin/stdout v3) does not change.

| Layer | File | Responsibility |
|---|---|---|
| Entrypoint | `scripts/run_router.py` | stdin → `route()` → stdout + exit. No logic. |
| Router core | `scripts/router.py` | Parse, validate, JIT, prompt, decision engine, provider selection. Provider-agnostic. |
| Provider adapters | `scripts/providers/*.py` | Build command, prepare env, run subprocess, normalize output. No routing logic. |

**Adapter location:** `scripts/providers/{claude,codex,gemini,agent}.py`. Each adapter inherits from `scripts/providers/base.py` (`BaseProvider`). Command override env vars (`SOLAR_ROUTER_{PROVIDER}_CMD`) are resolved in `BaseProvider.get_cmd()`.

## Environment keys

- `SOLAR_ROUTER_PROVIDER_PRIORITY` — Comma-separated provider list (e.g., `agent,codex,claude,gemini`)
- `SOLAR_SYSTEM_FEATURES` — CSV of enabled features (e.g., `async-tasks,transport-gateway`). Router reads this to check if `async-tasks` is enabled.

## Recommended defaults

```env
SOLAR_ROUTER_PROVIDER_PRIORITY=agent,codex,claude,gemini
SOLAR_SYSTEM_FEATURES=async-tasks,transport-gateway
```

## Provider selection behavior

- The first provider in `SOLAR_ROUTER_PROVIDER_PRIORITY` is primary.
- Remaining providers are fallback order if the previous provider fails.
- Supported providers are enforced by the router implementation.
- **Strict mode**: if `provider` field is set in the request, only that provider is used — no fallback. On failure → `error_code: provider_locked_failed`.
- **Priority mode**: if `provider` is not set, router tries providers in order until one succeeds.

## Repo context (all providers)

- The router runs each provider with `cwd` = repo root.
- Relative paths (`SOLAR_ROUTER_SYSTEM_PROMPT_FILE`, `SOLAR_ROUTER_RUNTIME_DIR`) are resolved against the repo root.
- Codex additionally receives `-C <repo-root>` and `--add-dir ~/.codex` in its command.

## Command overrides

- `SOLAR_ROUTER_AGENT_CMD`
- `SOLAR_ROUTER_CODEX_CMD`
- `SOLAR_ROUTER_CLAUDE_CMD`
- `SOLAR_ROUTER_GEMINI_CMD`

Default Agent command: `agent -p -f --approve-mcps --workspace <repo-root>`
Default Codex command is repo-anchored: `codex exec --skip-git-repo-check --full-auto -C <repo-root> --add-dir ~/.codex --`

## Timeout keys

- `SOLAR_ROUTER_TIMEOUT_SEC` (end-to-end router timeout, including provider execution, default: `300`)

## Conversation continuity keys

- `SOLAR_ROUTER_RUNTIME_DIR` (default: `sun/runtime/router`), resolved against repo root if relative
- `SOLAR_ROUTER_SYSTEM_PROMPT_FILE` (default: `core/skills/solar-router/assets/system_prompt.md`), resolved against repo root if relative
- `SOLAR_ROUTER_CONTEXT_TURNS` (default: `12`)

## DecisionEngine — mode and channel rules

| mode          | channel      | decision.kind          | notes                                          |
|---------------|--------------|------------------------|------------------------------------------------|
| `direct_only` | any          | `direct_reply`         | Always direct, no AI decision needed           |
| `async_only`  | any          | `async_draft_created`  | Requires `async-tasks` in SOLAR_SYSTEM_FEATURES |
| `async_only`  | any          | `failed`               | If `async-tasks` not enabled                   |
| `auto`        | `async-task` | `direct_reply`         | Already in queue, never re-propose async       |
| `auto`        | other        | AI decides semantically | AI returns JSON with `decision.kind`           |

## Async draft creation rule

- Router calls `core/skills/solar-async-tasks/scripts/create.sh` directly via subprocess.
- No direct file writes from router.
- Draft creation only if `async-tasks` is in `SOLAR_SYSTEM_FEATURES`.
- Activation (`plan.sh` + `approve.sh`) requires explicit second confirmation from user — never auto-queued.

## Caller mapping (approved)

| Caller              | channel       | mode          |
|---------------------|---------------|---------------|
| Telegram inbound    | `telegram`    | `auto`        |
| n8n inbound         | `n8n`         | `auto`        |
| async-task execution| `async-task`  | `direct_only` |
| `async_only` flows  | any           | `async_only`  |
| AI client subprocess| `other`       | `direct_only` |

## Router contract v3 — input

```json
{
  "request_id": "string",
  "session_id": "string",
  "user_id": "string",
  "text": "string",
  "channel": "telegram|n8n|async-task|other",
  "mode": "auto|direct_only|async_only",
  "provider": "codex|claude|gemini|agent|null",
  "metadata": {
    "agent": "agent-name|null",
    "skills": ["planet:skill-name", "core-skill-name"],
    "planet": "planet-name|null"
  }
}
```

**metadata field rules:**
- `agent`: existing agent from `planets/<planet>/agents/` or `core/agents/`. Set to `null` to generate JIT role inline.
- `skills`: `planet:skill` resolves to `planets/<planet>/skills/<skill>/SKILL.md`; unprefixed `skill` resolves to `planets/<metadata.planet>/skills/<skill>/SKILL.md` first (if `metadata.planet` is set), then falls back to `core/skills/<skill>/SKILL.md`. Only the frontmatter `description` is injected — never the full file.
- `planet`: planet that owns this task's domain. Used for agent and skill lookup.
- `provider` (top-level): `claude` for reasoning/writing, `codex` for code, `gemini` for research. Omit to use priority order.

## Secure Invocation Protocol (Required)

To prevent JSON parsing errors (invalid control characters, unescaped newlines), always use one of these two methods when calling the router from an AI agent or shell:

### Method A: Temporary JSON File (Recommended for Agents)

1. Use `write_file` to create a temporary JSON file (e.g., `sun/runtime/router/request_<id>.json`).
2. Ensure the `text` field contains explicit `\n` for newlines.
3. Execute the router piping the file: `python3 core/skills/solar-router/scripts/run_router.py < sun/runtime/router/request_<id>.json`.

### Method B: Heredoc with Single Quotes (Shell)

Use a heredoc with `'EOF'` (single quotes) to prevent the shell from interpreting backslashes or special characters:

```bash
cat << 'EOF' | python3 core/skills/solar-router/scripts/run_router.py
{
  "request_id": "my-id",
  "text": "Line 1\nLine 2",
  "channel": "other",
  "mode": "direct_only"
}
EOF
```

### Critical Rules:
- **Prefer escaped newlines** (`\n`) inside JSON strings for portability.
- **Escape double quotes** inside the `text` string as `\"`.
- **Validate JSON** before sending if using a custom script.

## Router contract v3 — output

```json
{
  "status": "success|failed",
  "request_id": "string",
  "provider_used": "codex|claude|gemini|agent",
  "reply_text": "string",
  "decision": {
    "kind": "direct_reply|async_draft_proposal|async_draft_created|async_activation_needed",
    "task_id": "string|null",
    "priority_suggested": "high|normal|low|null"
  },
  "error_code": "string|null",
  "error": "string|null"
}
```

## n8n bridge output rule

- HTTP webhook bridge for n8n exposes the router v3 JSON directly.
- No legacy double-wrapper (`solar_status` / `solar_response`).
- Only minimal bridge metadata (`bridge`, `route`) is added.

## Migration from v1/v2 to v3

Legacy variable names are supported with automatic fallback:
- `SOLAR_AI_PROVIDER_PRIORITY` → `SOLAR_ROUTER_PROVIDER_PRIORITY`
- `SOLAR_RUNTIME_DIR` → `SOLAR_ROUTER_RUNTIME_DIR`
- `SOLAR_SYSTEM_PROMPT_FILE` → `SOLAR_ROUTER_SYSTEM_PROMPT_FILE`
- `SOLAR_CONTEXT_TURNS` → `SOLAR_ROUTER_CONTEXT_TURNS`
- `SOLAR_AI_ROUTER_TIMEOUT_SEC` → `SOLAR_ROUTER_TIMEOUT_SEC`
- `SOLAR_AI_{PROVIDER}_CMD` → `SOLAR_ROUTER_{PROVIDER}_CMD`

Run `bash core/skills/solar-router/scripts/onboard_router_env.sh` to migrate automatically.

## JIT Context Protocol

When `metadata` is present, the router executes `resolve_jit_context(metadata)` before building the prompt:

1. **Agent resolution**: look up `planets/<planet>/agents/<agent>.md` → fallback to `core/agents/<agent>.md` → if not found, generate role inline (no extra LLM call).
2. **Skill resolution**: for each skill in `metadata.skills`, resolve path and extract frontmatter `description` only. Unknown skills emit a warning and are skipped.
3. **Prompt injection**: resolved agent role and skill catalog (name + description) are injected as `## Agent Role` and `## Available Skills` sections in the prompt.

**Anti-recursion rule:** subprocess calls from AI clients MUST always use `mode: direct_only` to prevent infinite delegation loops.

## router_id

The router auto-generates a `router_id` (UUID v4) for every execution. This is the internal process identifier.

- `router_id` is independent of `request_id` (caller-provided reference).
- `request_id` is preserved in the v3 contract and returned in the output.
- Both fields appear in the audit log for full traceability.

## Audit log

File: `sun/runtime/router/audit.jsonl`

Two records are written per execution:

```json
{"ts": "...", "event": "start", "router_id": "<uuid>", "request_id": "<caller-ref>", "user_id": "...", "channel": "...", "mode": "...", "metadata": {...}}
{"ts": "...", "event": "end",   "router_id": "<uuid>", "status": "success|failed", "provider": "...", "jit_generated": true|false, "duration_ms": 4200}
```

- `start` written on request receipt; `end` written before emitting the response.
- `jit_generated`: `true` if the agent role was generated inline (no pre-existing agent file).
- Used by `status_router.sh` to show in-flight processes and last N executions.
- **Known bug:** `end` is not written on early-exit paths (e.g. `async_tasks_disabled`, `provider_locked_failed`, `all_providers_failed`). Test 14 in `check_router.sh` documents this as expected current behavior.

## Key invariants (enforced)

1. No provider selection or fallback outside `solar-router`.
2. No async routing policy outside `solar-router`.
3. `decision.kind` is the official flow control field for all consumers.
4. `provider` in request → strict mode, no fallback.
5. Async activation always requires second explicit user confirmation.
6. AI client subprocesses always use `mode: direct_only` — no exceptions.
7. `router_id` is always a UUID auto-generated by the router; never reused across executions.
8. Skills are resolved on-demand from frontmatter only — full SKILL.md content is never injected into prompts.
