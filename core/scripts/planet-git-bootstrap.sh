#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANETS_DIR="$ROOT_DIR/planets"

PLANET_NAME=""
REMOTE_URL=""
DEFAULT_BRANCH="main"
PUSH_UPSTREAM=false

usage() {
  cat <<'EOF'
Usage:
  bash core/scripts/planet-git-bootstrap.sh --planet <name> [--remote <git-url>] [--push]

Options:
  --planet <name>     Planet folder under planets/ (required)
  --remote <git-url>  Set origin remote if missing
  --push              Push and set upstream (requires origin + network access)
  --branch <name>     Branch name to use/create (default: main)
  -h, --help          Show this help

Examples:
  bash core/scripts/planet-git-bootstrap.sh --planet career
  bash core/scripts/planet-git-bootstrap.sh --planet uhorizon.ai --remote git@github.com:org/uhorizon-ai-ops.git
  bash core/scripts/planet-git-bootstrap.sh --planet career --push
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --planet)
      PLANET_NAME="${2:-}"
      shift 2
      ;;
    --remote)
      REMOTE_URL="${2:-}"
      shift 2
      ;;
    --branch)
      DEFAULT_BRANCH="${2:-}"
      shift 2
      ;;
    --push)
      PUSH_UPSTREAM=true
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

if [ -z "$PLANET_NAME" ]; then
  echo "ERROR: --planet is required" >&2
  usage
  exit 1
fi

if ! [[ "$PLANET_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: Invalid planet name: '$PLANET_NAME'" >&2
  echo "Use only letters, numbers, dot (.), dash (-), or underscore (_)." >&2
  exit 1
fi

PLANET_DIR="$PLANETS_DIR/$PLANET_NAME"
if [ ! -d "$PLANET_DIR" ]; then
  echo "ERROR: Planet does not exist: $PLANET_DIR" >&2
  exit 1
fi

echo "Planet: $PLANET_NAME"
echo "Path: $PLANET_DIR"

if [ ! -d "$PLANET_DIR/.git" ]; then
  echo "Initializing git repository..."
  git -C "$PLANET_DIR" init -b "$DEFAULT_BRANCH"
else
  echo "Git repository already exists."
fi

current_branch="$(git -C "$PLANET_DIR" branch --show-current || true)"
if [ -z "$current_branch" ]; then
  echo "Creating branch '$DEFAULT_BRANCH'..."
  git -C "$PLANET_DIR" checkout -b "$DEFAULT_BRANCH"
  current_branch="$DEFAULT_BRANCH"
fi

if ! git -C "$PLANET_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "Creating initial commit..."
  git -C "$PLANET_DIR" add -A
  if git -C "$PLANET_DIR" diff --cached --quiet; then
    echo "No files to commit."
  else
    git -C "$PLANET_DIR" commit -m "chore: initialize planet workspace"
  fi
else
  echo "Planet already has at least one commit."
fi

if [ -n "$REMOTE_URL" ]; then
  if git -C "$PLANET_DIR" remote get-url origin >/dev/null 2>&1; then
    existing_remote="$(git -C "$PLANET_DIR" remote get-url origin)"
    if [ "$existing_remote" = "$REMOTE_URL" ]; then
      echo "Origin already configured with requested URL."
    else
      echo "WARN: origin already exists with a different URL: $existing_remote"
      echo "Skipping remote update to avoid unexpected override."
    fi
  else
    echo "Adding origin remote..."
    git -C "$PLANET_DIR" remote add origin "$REMOTE_URL"
  fi
fi

if $PUSH_UPSTREAM; then
  if git -C "$PLANET_DIR" remote get-url origin >/dev/null 2>&1; then
    echo "Pushing branch '$current_branch' and setting upstream..."
    git -C "$PLANET_DIR" push -u origin "$current_branch"
  else
    echo "ERROR: --push requested but origin remote is missing." >&2
    exit 1
  fi
fi

echo
echo "Done."
echo "Current status:"
git -C "$PLANET_DIR" status --short --branch
