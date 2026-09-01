#!/usr/bin/env bash
# client_init.sh — idempotent Solar Client workspace bootstrap (v1.1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

FORCE_LEGACY=false
FORCE_GOVERNANCE=false
WORKSPACE="$(pwd -P)"

usage() {
  cat <<'EOF'
Usage:
  solar client init [--force] [--force-governance]

Creates in the current directory (SOLAR_WORKSPACE):
  .solar/settings.json, sun/, planets/, .env.example, AGENTS.md, IDE symlinks, .cursorignore

Framework skills/agents come from the global Solar Client install (solar client sync).
Does NOT copy core/ into .solar/core/ (obsolete in v1.1).

Options:
  --force               Allow init when legacy core/ already exists at workspace root
  --force-governance    Replace existing CLAUDE.md, GEMINI.md, .cursorrules (backs up first)

For framework development, use a monorepo with core/ or solar/core/ at the repo root — not client init --from-dev.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-dev)
      echo "ERROR: --from-dev is removed in v1.1 (no .solar/core/). Use a dev monorepo or solar client upgrade." >&2
      exit 2
      ;;
    --force) FORCE_LEGACY=true; shift ;;
    --force-governance) FORCE_GOVERNANCE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -d "$WORKSPACE/.solar/core" ]]; then
  echo "ERROR: obsolete .solar/core/ present. Run: solar client upgrade" >&2
  exit 1
fi

if [[ -d "$WORKSPACE/core" && -f "$WORKSPACE/core/AGENTS.md" ]] && ! solar_client_settings_exists "$WORKSPACE"; then
  if [[ "$FORCE_LEGACY" != true ]]; then
    echo "ERROR: legacy layout (core/ at root). Use a new directory or --force (not recommended on dev monorepo)." >&2
    exit 1
  fi
fi

if solar_resolve_paths --workspace "$WORKSPACE" --relaxed --quiet 2>/dev/null; then
  INSTALL_ROOT="$SOLAR_ROOT"
else
  INSTALL_ROOT="$(solar_client_install_root)"
  export SOLAR_WORKSPACE="$WORKSPACE"
  export SOLAR_ROOT="$INSTALL_ROOT"
fi
CORE_DIR="$INSTALL_ROOT/core"

stable_hash() {
  printf '%s' "$1" | cksum | awk '{print $1}'
}

port_offsets() {
  local h
  h="$(stable_hash "$WORKSPACE")"
  echo "$((9000 + h % 500)) $((8787 + h % 500))"
}

read -r HOST_PORT HTTP_PORT < <(port_offsets)

mkdir -p "$WORKSPACE/sun/preferences" "$WORKSPACE/sun/daily-log" "$WORKSPACE/planets" "$WORKSPACE/.solar"

if ! solar_client_settings_exists "$WORKSPACE"; then
  solar_client_write_settings_v12 "$WORKSPACE" "$INSTALL_ROOT"
fi

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

if [[ ! -f "$WORKSPACE/AGENTS.md" ]]; then
  if [[ -f "$CORE_DIR/templates/workspace-AGENTS.md" ]]; then
    cp "$CORE_DIR/templates/workspace-AGENTS.md" "$WORKSPACE/AGENTS.md"
  else
    echo "# Solar Workspace" > "$WORKSPACE/AGENTS.md"
  fi
fi

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
  if [[ -f "$CORE_DIR/templates/workspace.env.example" ]]; then
    cp "$CORE_DIR/templates/workspace.env.example" "$WORKSPACE/.env.example"
  fi
  {
    echo ""
    echo "# Assigned by solar client init (override as needed)"
    echo "SOLAR_APP_PORT=$HOST_PORT"
    echo "SOLAR_HTTP_PORT=$HTTP_PORT"
  } >> "$WORKSPACE/.env.example"
fi

if [[ ! -f "$WORKSPACE/.env" ]]; then
  cp "$WORKSPACE/.env.example" "$WORKSPACE/.env"
fi

echo "OK: Solar Client init at $WORKSPACE"
echo "  .solar/      manifest only (framework via global client)"
echo "  sun/         personal context"
echo "  planets/     domain workspaces"
echo "  Next: solar client sync"
if [[ "$SYMLINK_WARN" == true ]]; then
  echo "WARN: IDE symlinks unavailable; stub files created (see solar client doctor)"
fi
if [[ "$GOVERNANCE_SKIPPED" == true ]]; then
  echo "INFO: existing governance files preserved (use --force-governance to replace)"
fi
