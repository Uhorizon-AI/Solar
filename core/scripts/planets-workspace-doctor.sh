#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANETS_DIR="$ROOT_DIR/planets"
CHECK_GIT=false

error_count=0
warn_count=0
planet_count=0

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
  bash core/scripts/planets-workspace-doctor.sh [--check-git]

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

if [ ! -d "$PLANETS_DIR" ]; then
  warn "Planets workspace does not exist: $PLANETS_DIR"
  echo "Summary: ${error_count} error(s), ${warn_count} warning(s), ${planet_count} planet(s) audited"
  exit 0
fi

for planet_dir in "$PLANETS_DIR"/*; do
  [ -d "$planet_dir" ] || continue
  planet_name="$(basename "$planet_dir")"
  planet_count=$((planet_count + 1))

  echo "== Planet: $planet_name =="

  if [ -f "$planet_dir/AGENTS.md" ]; then
    ok "$planet_name has AGENTS.md"
  else
    err "$planet_name is missing AGENTS.md"
  fi

  if [ -f "$planet_dir/MEMORY.md" ] || [ -f "$planet_dir/README.md" ]; then
    ok "$planet_name has runtime context file (MEMORY.md or README.md)"
  else
    warn "$planet_name has no MEMORY.md or README.md (optional)"
  fi

  if $CHECK_GIT; then
    if [ ! -d "$planet_dir/.git" ]; then
      info "$planet_name has no independent git repository (.git missing)"
      echo
      continue
    fi

    ok "$planet_name has independent git repository"

    if git -C "$planet_dir" rev-parse --verify HEAD >/dev/null 2>&1; then
      ok "$planet_name has at least one commit"
    else
      warn "$planet_name has no commits yet"
    fi

    if git -C "$planet_dir" remote get-url origin >/dev/null 2>&1; then
      ok "$planet_name has origin remote"
    else
      warn "$planet_name has no origin remote configured"
    fi

    branch="$(git -C "$planet_dir" branch --show-current 2>/dev/null || true)"
    if [ -z "$branch" ]; then
      warn "$planet_name has no active branch"
    else
      ok "$planet_name active branch: $branch"
      if git -C "$planet_dir" rev-parse --abbrev-ref "${branch}@{upstream}" >/dev/null 2>&1; then
        ok "$planet_name branch '$branch' has upstream tracking"
      else
        warn "$planet_name branch '$branch' has no upstream tracking"
      fi
    fi
  else
    info "$planet_name git checks skipped (use --check-git to enable)"
  fi

  echo
done

if [ "$planet_count" -eq 0 ]; then
  warn "No planets found under $PLANETS_DIR"
fi

echo "Summary: ${error_count} error(s), ${warn_count} warning(s), ${planet_count} planet(s) audited"

if [ "$error_count" -gt 0 ]; then
  exit 1
fi

exit 0
