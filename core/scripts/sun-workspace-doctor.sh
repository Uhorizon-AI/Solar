#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SUN_DIR="$ROOT_DIR/sun"
CHECK_GIT=false

error_count=0
warn_count=0

ok() {
  echo "OK: $1"
}

warn() {
  echo "WARN: $1"
  warn_count=$((warn_count + 1))
}

err() {
  echo "ERROR: $1"
  error_count=$((error_count + 1))
}

info() {
  echo "INFO: $1"
}

usage() {
  cat <<'EOF'
Usage:
  bash core/scripts/sun-workspace-doctor.sh [--check-git]

Options:
  --check-git  Include optional git checks (.git, commit, remote, upstream)
  -h, --help   Show this help
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check-git)
      CHECK_GIT=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_file() {
  local file="$1"
  if [ -f "$SUN_DIR/$file" ]; then
    ok "Found $file"
  else
    err "Missing required file: $file"
  fi
}

if [ ! -d "$SUN_DIR" ]; then
  err "Missing sun workspace: $SUN_DIR"
  echo "Summary: ${error_count} error(s), ${warn_count} warning(s)"
  exit 1
fi

ok "Sun workspace exists"
require_file "preferences/profile.md"
require_file "memories/baseline.md"

if $CHECK_GIT; then
  if [ -d "$SUN_DIR/.git" ]; then
    ok "Sun has independent git repository"
    if git -C "$SUN_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
      ok "Sun has at least one commit"
    else
      warn "Sun has no commits yet"
    fi

    if git -C "$SUN_DIR" remote get-url origin >/dev/null 2>&1; then
      ok "Sun has origin remote"
    else
      warn "Sun has no origin remote configured"
    fi

    branch="$(git -C "$SUN_DIR" branch --show-current 2>/dev/null || true)"
    if [ -z "$branch" ]; then
      warn "Sun has no active branch"
    else
      ok "Sun active branch: $branch"
      if git -C "$SUN_DIR" rev-parse --abbrev-ref "${branch}@{upstream}" >/dev/null 2>&1; then
        ok "Sun branch '$branch' has upstream tracking"
      else
        warn "Sun branch '$branch' has no upstream tracking"
      fi
    fi
  else
    info "Sun has no independent git repository (.git missing)"
  fi
else
  info "Git checks skipped (use --check-git to enable)"
fi

echo "Summary: ${error_count} error(s), ${warn_count} warning(s)"

if [ "$error_count" -gt 0 ]; then
  exit 1
fi

exit 0
