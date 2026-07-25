# Native packaging (backlog)

Stabilise the Git install + GitHub Release contract before packaging. This document is the Corte 4 backlog for Solar Client distribution without requiring Git familiarity.

## Targets

1. **Homebrew tap** — `brew install uhorizon-ai/tap/solar`  
   Formula installs the `solar` wrapper and a versioned framework prefix (or taps a release tarball).

2. **Signed release tarball** — attach to each GitHub Release:  
   `solar-vX.Y.Z-macos.tar.gz` + `.sha256`  
   Contents: framework tree at the release tag + wrapper install script.

3. **Release asset bootstrap** — optional evolution of the README pin from  
   `raw.githubusercontent.com/.../bootstrap_solar_client.sh`  
   to a checksummed asset URL on the same Release.

4. **Installer without Git** — extract tarball to `~/Solar/solar`, write wrapper, smoke `"$WRAPPER" --version`.

5. **Channels** — stable (GitHub Release latest) and optional beta (prerelease) once packaging exists.

6. **Linux package** — only after macOS package + ubuntu CI are green and the platform contract is declared.

## Non-goals until Git path is green

- Replacing `create-release.sh` with a separate packaging pipeline
- Silent profile edits
- Auto-update that bypasses the Release channel

## Prerequisite

Corte 1–2 install E2E + `create-release --publish` producing a real GitHub Release.
