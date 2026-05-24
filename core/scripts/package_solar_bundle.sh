#!/usr/bin/env bash
# package_solar_bundle.sh — build an allowlisted core/ bundle for Solar Client.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash core/scripts/package_solar_bundle.sh --output <dir> [--from-dev] [--from-tag <tag>]

Options:
  --output <dir>   Staging directory (created; must be empty or --force)
  --from-dev       Copy from current repo (default)
  --from-tag <tag> Checkout tag into a temp tree first (read-only on main worktree)
  --force          Replace existing output directory
EOF
}

FROM_DEV=true
FROM_TAG=""
OUTPUT=""
FORCE=false
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT="$2"; shift 2 ;;
    --from-dev) FROM_DEV=true; FROM_TAG=""; shift ;;
    --from-tag) FROM_TAG="$2"; FROM_DEV=false; shift 2 ;;
    --force) FORCE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$OUTPUT" ]] || { echo "ERROR: --output required" >&2; exit 1; }

SRC_ROOT="$ROOT_DIR"
TEMP_CHECKOUT=""
if [[ -n "$FROM_TAG" ]]; then
  TEMP_CHECKOUT="$(mktemp -d)"
  trap 'rm -rf "$TEMP_CHECKOUT"' EXIT
  git -C "$ROOT_DIR" archive "$FROM_TAG" | tar -x -C "$TEMP_CHECKOUT"
  SRC_ROOT="$TEMP_CHECKOUT"
fi

if [[ -d "$OUTPUT" ]]; then
  if [[ "$FORCE" == true ]]; then
    rm -rf "$OUTPUT"
  else
    echo "ERROR: output exists: $OUTPUT (use --force)" >&2
    exit 1
  fi
fi
mkdir -p "$OUTPUT/core"

copy_tree() {
  local rel="$1"
  local src="$SRC_ROOT/core/$rel"
  local dest="$OUTPUT/core/$rel"
  if [[ -d "$src" ]]; then
    mkdir -p "$(dirname "$dest")"
    rsync -a --delete \
      --exclude '.venv' --exclude '__pycache__' --exclude 'node_modules' \
      --exclude '.env' --exclude '*.pyc' \
      "$src/" "$dest/"
  fi
}

for part in skills agents commands scripts templates docs; do
  copy_tree "$part"
done

if [[ -f "$SRC_ROOT/AGENTS.md" ]]; then
  cp "$SRC_ROOT/AGENTS.md" "$OUTPUT/workspace-AGENTS.md.template"
fi

if [[ -f "$SRC_ROOT/core/AGENTS.md" ]]; then
  cp "$SRC_ROOT/core/AGENTS.md" "$OUTPUT/core/AGENTS.md"
fi

VERSION="$(git -C "$ROOT_DIR" describe --tags --always 2>/dev/null || echo "dev")"
COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")"
DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

cat > "$OUTPUT/manifest.json" <<EOF
{
  "version": "$VERSION",
  "commit": "$COMMIT",
  "channel": "stable",
  "packaged_at": "$DATE",
  "layout": "solar-client-bundle-v1"
}
EOF

echo "Bundle written to $OUTPUT (version=$VERSION)"
