#!/usr/bin/env bash
# sync-clients.sh
# Sync Solar core resources to local AI clients.
# Sources (if present):
# - core/skills/
# - core/agents/
# - core/commands/
# Targets:
# - .codex/skills
# - .claude/{skills,agents,commands}
# - .cursor/{skills,agents,commands}
#
# Usage:
#   bash core/scripts/sync-clients.sh [--codex-only|--claude-only|--cursor-only]

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SRC_SKILLS="$ROOT_DIR/core/skills"
SRC_AGENTS="$ROOT_DIR/core/agents"
SRC_COMMANDS="$ROOT_DIR/core/commands"

CODEX_DIR="${CODEX_HOME:-$ROOT_DIR/.codex}"
CODEX_SKILLS="$CODEX_DIR/skills"

CLAUDE_DIR="$ROOT_DIR/.claude"
CLAUDE_SKILLS="$CLAUDE_DIR/skills"
CLAUDE_AGENTS="$CLAUDE_DIR/agents"
CLAUDE_COMMANDS="$CLAUDE_DIR/commands"

CURSOR_DIR="$ROOT_DIR/.cursor"
CURSOR_SKILLS="$CURSOR_DIR/skills"
CURSOR_AGENTS="$CURSOR_DIR/agents"
CURSOR_COMMANDS="$CURSOR_DIR/commands"

SYNC_CODEX=false
SYNC_CLAUDE=false
SYNC_CURSOR=false

for arg in "$@"; do
  case "$arg" in
    --codex-only) SYNC_CODEX=true ;;
    --claude-only) SYNC_CLAUDE=true ;;
    --cursor-only) SYNC_CURSOR=true ;;
    -h|--help)
      echo "Usage: $0 [--codex-only|--claude-only|--cursor-only]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if ! $SYNC_CODEX && ! $SYNC_CLAUDE && ! $SYNC_CURSOR; then
  SYNC_CODEX=true
  SYNC_CLAUDE=true
  SYNC_CURSOR=true
fi

log_section() {
  echo -e "${BLUE}$1${NC}"
}

log_ok() {
  echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}⚠${NC} $1"
}

ensure_dir() {
  mkdir -p "$1"
}

clean_symlinks_from_prefix() {
  local target_dir="$1"
  local prefix="$2"
  [ -d "$target_dir" ] || return 0
  for item in "$target_dir"/*; do
    [ -L "$item" ] || continue
    local link_target
    link_target="$(readlink "$item")"
    if [[ "$link_target" == "$prefix"* ]]; then
      rm -f "$item"
    fi
  done
}

sync_dirs_as_symlink() {
  local source_dir="$1"
  local target_dir="$2"
  local require_skill_md="${3:-false}"

  [ -d "$source_dir" ] || { log_warn "Missing source dir: $source_dir"; return 0; }
  ensure_dir "$target_dir"
  clean_symlinks_from_prefix "$target_dir" "$source_dir"

  for item in "$source_dir"/*; do
    [ -d "$item" ] || continue
    if [ "$require_skill_md" = "true" ] && [ ! -f "$item/SKILL.md" ]; then
      log_warn "Skipping $(basename "$item") (missing SKILL.md)"
      continue
    fi
    ln -snf "$item" "$target_dir/$(basename "$item")"
    log_ok "$(basename "$item")"
  done
}

sync_md_files_as_symlink() {
  local source_dir="$1"
  local target_dir="$2"

  [ -d "$source_dir" ] || { log_warn "Missing source dir: $source_dir"; return 0; }
  ensure_dir "$target_dir"
  clean_symlinks_from_prefix "$target_dir" "$source_dir"

  shopt -s nullglob
  for file in "$source_dir"/*.md; do
    [ -f "$file" ] || continue
    ln -snf "$file" "$target_dir/$(basename "$file")"
    log_ok "$(basename "$file")"
  done
  shopt -u nullglob
}

sync_dirs_as_copy() {
  local source_dir="$1"
  local target_dir="$2"
  local require_skill_md="${3:-false}"

  [ -d "$source_dir" ] || { log_warn "Missing source dir: $source_dir"; return 0; }
  ensure_dir "$target_dir"

  for item in "$source_dir"/*; do
    [ -d "$item" ] || continue
    if [ "$require_skill_md" = "true" ] && [ ! -f "$item/SKILL.md" ]; then
      log_warn "Skipping $(basename "$item") (missing SKILL.md)"
      continue
    fi
    rm -rf "$target_dir/$(basename "$item")"
    cp -R "$item" "$target_dir/$(basename "$item")"
    log_ok "$(basename "$item") (copy)"
  done
}

sync_md_files_as_copy() {
  local source_dir="$1"
  local target_dir="$2"

  [ -d "$source_dir" ] || { log_warn "Missing source dir: $source_dir"; return 0; }
  ensure_dir "$target_dir"

  shopt -s nullglob
  for file in "$source_dir"/*.md; do
    [ -f "$file" ] || continue
    cp "$file" "$target_dir/$(basename "$file")"
    log_ok "$(basename "$file") (copy)"
  done
  shopt -u nullglob
}

sync_codex() {
  log_section "🔄 Codex (.codex)"
  log_section "📦 Skills"
  sync_dirs_as_symlink "$SRC_SKILLS" "$CODEX_SKILLS" true
  echo
}

sync_claude() {
  log_section "🔄 Claude (.claude)"
  log_section "📦 Skills"
  sync_dirs_as_symlink "$SRC_SKILLS" "$CLAUDE_SKILLS" true
  log_section "🤖 Agents"
  sync_md_files_as_symlink "$SRC_AGENTS" "$CLAUDE_AGENTS"
  log_section "🧩 Commands"
  sync_md_files_as_symlink "$SRC_COMMANDS" "$CLAUDE_COMMANDS"
  echo
}

sync_cursor() {
  log_section "🔄 Cursor (.cursor)"
  log_section "📦 Skills"
  sync_dirs_as_copy "$SRC_SKILLS" "$CURSOR_SKILLS" true
  log_section "🤖 Agents"
  sync_md_files_as_copy "$SRC_AGENTS" "$CURSOR_AGENTS"
  log_section "🧩 Commands"
  sync_md_files_as_copy "$SRC_COMMANDS" "$CURSOR_COMMANDS"
  echo
}

$SYNC_CODEX && sync_codex
$SYNC_CLAUDE && sync_claude
$SYNC_CURSOR && sync_cursor

echo -e "${GREEN}✅ Sync complete.${NC}"
