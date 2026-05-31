#!/usr/bin/env bash
# solar host workspace — manage machine-local registry
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_PY="$SCRIPT_DIR/host_registry.py"

usage() {
  cat <<'EOF'
Usage:
  solar host workspace list
  solar host workspace add <path> [label]
  solar host workspace remove <path>
  solar host workspace use <path>
EOF
}

cmd="${1:-}"
case "$cmd" in
  list)
    exec python3 "$REGISTRY_PY" list
    ;;
  add)
    shift
    [[ -n "${1:-}" ]] || { usage >&2; exit 2; }
    exec python3 "$REGISTRY_PY" add "$@"
    ;;
  remove)
    shift
    [[ -n "${1:-}" ]] || { usage >&2; exit 2; }
    exec python3 "$REGISTRY_PY" remove "$@"
    ;;
  use)
    shift
    [[ -n "${1:-}" ]] || { usage >&2; exit 2; }
    exec python3 "$REGISTRY_PY" use "$@"
    ;;
  "")
    usage >&2
    exit 2
    ;;
  *)
    echo "Unknown workspace subcommand: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
