# Installation contract (Solar Client)

**Platform (supported):** macOS  
**Experimental:** Linux CLI (CI informative only)  
**Out of scope:** Windows native

## Layout (Claude Code / Codex style)

| Path | Role |
|---|---|
| `~/.local/share/solar` (default `SOLAR_ROOT`) | Global framework install (git checkout; hidden data dir) |
| Any directory (e.g. `~/Solar`) | Workspace (`sun/`, `planets/`, `.solar/`) |
| `~/.local/bin/solar` | Wrapper on PATH (`SOLAR_BIN_DIR` override) |

Install and workspace stay separate so core updates never overwrite `sun/` / `planets/`.

**Legacy:** older installs may live at `~/Solar/solar`. That path is still discovered as a fallback. Prefer migrating with:

```bash
bash ~/.local/share/solar/core/skills/solar-client/scripts/install_solar_client.sh --yes
# or keep SOLAR_ROOT=~/Solar/solar if you prefer not to move
```

## Dependencies

Required: `git`, `bash`, `python3`, `curl`.

## Stable channel

Default ref = latest **GitHub Release** for `Uhorizon-AI/Solar` via:

`GET https://api.github.com/repos/Uhorizon-AI/Solar/releases/latest` → `tag_name`

Resolved with `curl` (not `gh`). No fallback to `main`. Pass `--ref` for an explicit tag/branch/commit.

## Installer smoke and PATH

- Success requires `"$WRAPPER" --version` (absolute path) to succeed.
- Missing `PATH` entry for the wrapper directory prints an instruction; it does **not** fail the install.
- The installer never edits shell profiles silently.
- `curl | bash` is supported (no `BASH_SOURCE` dependency).

## Commands

```bash
# Install (bootstrap pin in README is release-managed)
curl -fsSL https://raw.githubusercontent.com/Uhorizon-AI/Solar/vX.Y.Z/core/skills/solar-client/scripts/bootstrap_solar_client.sh | bash

# Use from any folder
mkdir -p ~/Solar && cd ~/Solar
solar setup                 # preflight + init + sync + doctors
solar client update --ref <tag>   # or default = stable release
solar uninstall             # remove wrapper; optional --remove-install
```

## Releases

See `core/commands/solar-create-release.md`:

- test ordinary code independently with `solar client update --ref <full-remote-SHA>`; no new version or release request is needed, and the selected installation/runtime really changes
- installed commit and nominal version are reported separately; local SHA acceptance does not replace CI of the final release tree
- default `create-release.sh --version vX.Y.Z`: freeze the authorized main base, prepare/push metadata PR and request protected native auto-merge; GitHub tests and publishes the exact integrated SHA
- no second post-green command or running Mac is required; auto-merge, mandatory reviews/checks and main up-to-date protection (`strict: true`) are explicit prerequisites; merge queue is not supported
- `--local` prepares without remote effects; `--resume` previews/confirms the prepared request (non-interactive: `--resume --yes`)
- `--publish` / `--retry` request the exact remote CI run; only the dependent GitHub job writes tags/Releases
- exceptional recovery freezes admission and reconciles old writers/outcomes before an append-only omission can permit a higher corrected version; ambiguous outcomes remain blocked
- stale requests are blocked before normal merge by strict protection; already-integrated drift requires controlled omission and a higher corrected request, not a blind rerun
- bootstrap raw URL verification retries five times with short waits before reporting propagation failure
- no automatic installed-client update/deployment occurs during publication

## Telemetry

None by default. Solar does not phone home during install.
