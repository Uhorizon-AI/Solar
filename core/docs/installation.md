# Installation contract (Solar Client)

**Platform (supported):** macOS  
**Experimental:** Linux CLI (CI informative only)  
**Out of scope:** Windows native

## Layout (Claude Code / Codex style)

| Path | Role |
|---|---|
| `~/.local/share/solar` (default `SOLAR_ROOT`) | Global framework install (git checkout; hidden data dir) |
| Any directory (e.g. `~/Solar`, `~/Projects/acme`) | Workspace (`sun/`, `planets/`, `.solar/`) |
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

- prepare (local): CHANGELOG, `SOLAR_VERSION`, README pin, commit, tag
- `--publish` (A2 formal): local E2E → push → `gh release create` → API verify
- `--publish --retry`: complete a missing GitHub Release without recreating the tag

## Telemetry

None by default. Solar does not phone home during install.
