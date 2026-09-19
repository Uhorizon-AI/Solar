# User-level MCP clients

The client launches `solar mcp` as a stdio child, independently of LaunchAgent.
Supported destinations:

| Client | File |
|---|---|
| Cursor | `~/.cursor/mcp.json` |
| Claude | `~/.claude.json` (`mcpServers`; skipped when absent) |
| Codex | `$CODEX_HOME/config.toml`, default `~/.codex/config.toml` |

Gemini and Antigravity registration are intentionally unsupported until their
separate destinations and schemas have integration tests. Unknown client names
fail before any write.

`install --clients cursor,codex --dry-run` validates and shows a diff of only the
Solar entry. Other environment values are redacted. It creates no files.
`print` emits complete JSON snippets (including `mcpServers`) and a TOML section.
The canonical workspace resolver discovers the parent workspace or accepts
`--workspace`; `.solar/settings.json` and `sun/` must exist. It never registers
an arbitrary current directory. Entries pin the absolute Python interpreter
using `SOLAR_MCP_PYTHON`; registration requires Python 3.11+. Selection prefers
an explicit `SOLAR_MCP_PYTHON`, then `python3` on PATH, preserving symlinks.
The selected executable is probed for its version and venv status. A temporary
venv is rejected as a registration target; running the installer from a venv
is allowed when a stable external interpreter is explicitly selected.
Stdio startup does not import `tomllib` or impose registration's 3.11 requirement.
If no installed Solar wrapper exists, the CLI warns before using the checkout
path. Keep that checkout and interpreter in place, or reinstall the registration.

Updates preserve unrelated settings, validate TOML semantically and fail closed
on layouts that cannot safely be edited, including unsupported inline tables.
Unchanged entries produce no writes or backups. Changed files use a temporary
file in the same directory, fsync and atomic replacement. One 0600 backup per
client is retained as `<filename>.bak.solar-mcp`; legacy timestamped backups
are not deleted automatically. Configuration permissions are preserved.

Solar writers share persistent locks in `<runtime>/mcp/config-locks/`, keyed by
the canonical configuration path. Locks are not unlinked on release, avoiding
inode races between waiting processes. No new lock files are placed beside
client configurations. Solar writers compare the original bytes immediately before
replacement. Noncooperating apps can still race in the final check/replace window;
close the client's settings editor while installing. This is not a transaction
across all clients: an error is reported per client, with a nonzero final exit.

`uninstall` removes only the Solar entry. It does not restore a whole backup or
remove other servers. Review the backup manually if deeper recovery is needed.
Project-level entries may shadow the user registration; review those separately.

## Development validation

```bash
uv run --project core/tests python -m pytest core/tests/skills/solar-mcp -q
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-mcp /tmp
```

`mcp_probe.py list` and `mcp_probe.py call solar_task_status '{}'` exercise the
legacy direct-server read path; the tests additionally cover dispatcher startup.

## Runtime dependencies

Starting the stdio child does not start Solar services. Tools still depend on
Solar's configured workspace, runtime storage and (for sends) installation secrets.
`solar_task_create` invokes `create.sh` to write a task; the supervised
orchestrator processes queued tasks separately. Console and background services
have their own startup/LaunchAgent lifecycle. A connected MCP child is not evidence
that the queue worker, console or transport is running.

## Legacy backup cleanup

Older versions produced timestamped files such as `mcp.json.bak.solar-mcp.*`
beside the client configuration. List them without reading their potentially
sensitive contents:

```bash
find "$HOME/.cursor" "$HOME/.codex" -maxdepth 1 -type f -name '*.bak.solar-mcp.*' -print
find "$HOME" -maxdepth 1 -type f -name '.claude.json.bak.solar-mcp.*' -print
```

For a custom CODEX_HOME, inspect that directory instead. After confirming that
the current configuration loads, other servers remain registered, and the current
`.bak.solar-mcp` provides the intended recovery copy, review the listed files and
remove only the obsolete copies you explicitly select. No automated cleanup is
performed; never restore a whole legacy backup over newer client settings blindly.
