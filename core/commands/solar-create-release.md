---
name: solar-create-release
description: Create a new Solar framework release with semantic versioning
---

# Solar Release Creation

Interactive command to create framework releases with automatic version calculation and changelog generation.

## Usage

```bash
# Prepare locally (no remote side effects)
bash core/scripts/create-release.sh [--yes] [--version vX.Y.Z]

# Publish (A2 formal — push + GitHub Release)
bash core/scripts/create-release.sh [--yes] [--version vX.Y.Z] --publish

# Idempotent recovery if tag is remote but GitHub Release is missing
bash core/scripts/create-release.sh --publish --retry [--version vX.Y.Z]
```

**Options:**
- `--yes`: Skip confirmation prompt (required in non-interactive shells)
- `--version vX.Y.Z`: Force version instead of auto bump
- `--publish`: Local E2E → `git push origin main --tags` → verify remote tag → `gh release create` → API/raw verify
- `--publish --retry`: Do **not** recreate commit/tag; only complete/verify the GitHub Release
- `--push`: Deprecated alias for `--publish` (push without Release is not allowed)

**When to use:**
- After completing 2-3 significant framework features
- Before starting new major development (to establish baseline)
- When framework changes are ready for distribution

Publishing (`--publish`) requires formal A2 approval (external push + GitHub Release).

---

## Modes

| Mode | Effect | Remoto |
|---|---|---|
| Prepare (default) | CHANGELOG + `SOLAR_VERSION` + README Quickstart pin + commit + local tag | no |
| `--publish` | Prep if needed → **E2E local** → push → `gh release create` → verify | yes |
| `--publish --retry` | Confirm remote tag; create Release if missing | yes |

### Prepare order (before commit/tag)

1. Calculate `NEW_VERSION`
2. Update `CHANGELOG.md` and `SOLAR_VERSION` in `scripts/solar`
3. Rewrite README block between `<!-- solar-bootstrap-pin -->` markers to
   `https://raw.githubusercontent.com/Uhorizon-AI/Solar/vX.Y.Z/core/skills/solar-client/scripts/bootstrap_solar_client.sh`
4. Show preview (changelog + pin URL) and confirm
5. Commit `chore(release): vX.Y.Z` and create local tag

### Publish order

1. Complete prepare if HEAD is not already the release tag
2. Run `core/tests/skills/solar-client/test_install_solar_client.sh` — abort on failure (**no push**)
3. `git push origin main --tags`
4. Verify tag on remote (`git ls-remote`)
5. `gh release create` (only after remote tag exists)
6. Verify Release via API + bootstrap raw URL HTTP 200

If `gh release create` fails after a successful push, re-run:

```bash
bash core/scripts/create-release.sh --publish --retry --version vX.Y.Z
```

---

## Pre-flight Checks

- Working tree clean
- On `main`
- At least one commit since last release (or curated `[Unreleased]`)
- `--publish` also requires `gh` authenticated

---

## What Gets Modified (prepare)

- `CHANGELOG.md`
- `core/skills/solar-client/scripts/solar` (`SOLAR_VERSION`)
- `README.md` (bootstrap pin only)
- Git tag `vX.Y.Z`

**NOT modified:** `sun/`, `planets/` (workspace), no VERSION file

---

## Identity contract

| Artefact | Value |
|---|---|
| Tag / GitHub Release | `vMAJOR.MINOR.PATCH` |
| `SOLAR_VERSION` | `MAJOR.MINOR.PATCH` |
| README pin | same `vMAJOR.MINOR.PATCH` (written by this script) |
| Install/update runtime | `releases/latest` via API + curl (no hard-coded default tag) |

---

## Exit Codes

- `0`: Success
- `1`: User rejected or publish/E2E failure
- `2`: Pre-flight / usage error
