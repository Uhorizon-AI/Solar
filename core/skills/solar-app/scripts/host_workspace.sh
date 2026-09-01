#!/usr/bin/env bash
# solar app workspace — manage machine-local registry
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_PY="$SCRIPT_DIR/host_registry.py"

usage() {
  cat <<'EOF'
Usage:
  solar app workspace list
  solar app workspace add <path> [label]
  solar app workspace remove <path>
  solar app workspace use <path>
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
