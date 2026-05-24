#!/usr/bin/env bash
# client_init.sh — idempotent Solar Client workspace bootstrap.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_home.sh
source "$SCRIPT_DIR/resolve_solar_home.sh"

FROM_DEV=false
FORCE_LEGACY=false
FORCE_GOVERNANCE=false
WORKSPACE="$(pwd -P)"
FRAMEWORK_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  bash client_init.sh [--from-dev] [--force]

Creates in the current directory (SOLAR_HOME):
  .solar/ + manifest, sun/, planets/, .env.example, AGENTS.md, IDE symlinks, .cursorignore

Options:
  --from-dev            Package core/ from the development framework checkout
  --force               Allow init when legacy core/ already exists at workspace root
  --force-governance    Replace existing CLAUDE.md, GEMINI.md, .cursorrules (backs up first)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-dev) FROM_DEV=true; shift ;;
    --force) FORCE_LEGACY=true; shift ;;
    --force-governance) FORCE_GOVERNANCE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -d "$WORKSPACE/core" && -f "$WORKSPACE/core/AGENTS.md" && ! -d "$WORKSPACE/.solar" ]]; then
  if [[ "$FORCE_LEGACY" != true ]]; then
    echo "ERROR: legacy layout (core/ at root). Use a new directory or --force (not recommended on dev monorepo)." >&2
    exit 1
  fi
fi

stable_hash() {
  printf '%s' "$1" | cksum | awk '{print $1}'
}

port_offsets() {
  local h
  h="$(stable_hash "$WORKSPACE")"
  echo "$((7741 + h % 500)) $((8787 + h % 500))"
}

read -r IFACE_PORT HTTP_PORT < <(port_offsets)

mkdir -p "$WORKSPACE/sun/preferences" "$WORKSPACE/sun/daily-log" "$WORKSPACE/planets" "$WORKSPACE/.solar"

# Bundle core into .solar/core
if [[ "$FROM_DEV" == true ]]; then
  STAGING="$(mktemp -d)"
  trap 'rm -rf "$STAGING"' EXIT
  bash "$FRAMEWORK_ROOT/core/scripts/package_solar_bundle.sh" --output "$STAGING" --from-dev --force
  rsync -a "$STAGING/core/" "$WORKSPACE/.solar/core/"
  if [[ -f "$STAGING/manifest.json" ]]; then
    cp "$STAGING/manifest.json" "$WORKSPACE/.solar/manifest.json"
  fi
elif [[ ! -d "$WORKSPACE/.solar/core/skills" ]]; then
  echo "ERROR: .solar/core missing. Run with --from-dev from a framework checkout." >&2
  exit 1
fi

if [[ ! -f "$WORKSPACE/.solar/manifest.json" ]]; then
  VERSION="$(git -C "$FRAMEWORK_ROOT" describe --tags --always 2>/dev/null || echo "dev")"
  COMMIT="$(git -C "$FRAMEWORK_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")"
  cat > "$WORKSPACE/.solar/manifest.json" <<EOF
{
  "version": "$VERSION",
  "commit": "$COMMIT",
  "channel": "stable",
  "packaged_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "layout": "solar-client-v1"
}
EOF
fi

# sun bootstrap (minimal)
if [[ ! -f "$WORKSPACE/sun/preferences/profile.md" ]]; then
  cat > "$WORKSPACE/sun/preferences/profile.md" <<'EOF'
# User Profile

## Identity Handshake
- Your name:
- How you want me to call you:
- Preferred language: Español

## Working Preferences
- Deep work windows:
- Timezone:

## Priorities
1.
EOF
fi

if [[ ! -f "$WORKSPACE/sun/MEMORY.md" ]]; then
  cat > "$WORKSPACE/sun/MEMORY.md" <<'EOF'
# Sun Memory

Operational learnings only (max 200 lines).
EOF
fi

# AGENTS.md workspace
if [[ ! -f "$WORKSPACE/AGENTS.md" ]]; then
  if [[ -f "$FRAMEWORK_ROOT/core/templates/workspace-AGENTS.md" ]]; then
    cp "$FRAMEWORK_ROOT/core/templates/workspace-AGENTS.md" "$WORKSPACE/AGENTS.md"
  else
    echo "# Solar Workspace" > "$WORKSPACE/AGENTS.md"
  fi
fi

# Symlinks with fallback stubs (never overwrite regular files without --force-governance)
SYMLINK_WARN=false
GOVERNANCE_SKIPPED=false
link_governance() {
  local name="$1"
  local target="AGENTS.md"
  local path="$WORKSPACE/$name"

  if [[ -L "$path" ]]; then
    local current
    current="$(readlink "$path" 2>/dev/null || true)"
    if [[ "$current" == "$target" || "$current" == "./$target" ]]; then
      return 0
    fi
    if [[ "$FORCE_GOVERNANCE" != true ]]; then
      echo "SKIP: $name symlink -> $current (preserved; use --force-governance to replace)"
      GOVERNANCE_SKIPPED=true
      return 0
    fi
    rm -f "$path"
  elif [[ -f "$path" ]]; then
    if [[ "$FORCE_GOVERNANCE" != true ]]; then
      echo "SKIP: $name exists as a regular file (preserved; use --force-governance to replace)"
      GOVERNANCE_SKIPPED=true
      return 0
    fi
    cp "$path" "${path}.bak.$(date +%Y%m%d%H%M%S)"
    rm -f "$path"
  fi

  if ln -snf "$target" "$path" 2>/dev/null; then
    return 0
  fi
  SYMLINK_WARN=true
  cat > "$path" <<EOF
# Read $target in this workspace (symlink unavailable).
See AGENTS.md for governance.
EOF
}

link_governance "CLAUDE.md"
link_governance "GEMINI.md"
link_governance ".cursorrules"

if [[ ! -f "$WORKSPACE/.cursorignore" ]]; then
  cat > "$WORKSPACE/.cursorignore" <<'EOF'
.solar/
sun/runtime/**/logs/
sun/runtime/**/audit.jsonl
EOF
fi

if [[ ! -f "$WORKSPACE/.env.example" ]]; then
  if [[ -f "$FRAMEWORK_ROOT/core/templates/workspace.env.example" ]]; then
    cp "$FRAMEWORK_ROOT/core/templates/workspace.env.example" "$WORKSPACE/.env.example"
  fi
  {
    echo ""
    echo "# Assigned by solar client init (override as needed)"
    echo "SOLAR_INTERFACE_PORT=$IFACE_PORT"
    echo "SOLAR_HTTP_PORT=$HTTP_PORT"
  } >> "$WORKSPACE/.env.example"
fi

if [[ ! -f "$WORKSPACE/.env" ]]; then
  cp "$WORKSPACE/.env.example" "$WORKSPACE/.env"
fi

export SOLAR_HOME="$WORKSPACE"
export SOLAR_CORE_ROOT="$WORKSPACE/.solar/core"
export REPO_ROOT="$WORKSPACE"

echo "OK: Solar Client init at $WORKSPACE"
echo "  .solar/core  framework bundle"
echo "  sun/         personal context"
echo "  planets/     domain workspaces"
if [[ "$SYMLINK_WARN" == true ]]; then
  echo "WARN: IDE symlinks unavailable; stub files created (see solar client doctor)"
fi
if [[ "$GOVERNANCE_SKIPPED" == true ]]; then
  echo "INFO: existing governance files preserved (use --force-governance to replace)"
fi
