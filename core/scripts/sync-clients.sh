#!/usr/bin/env bash
# sync-clients.sh
# Sync Solar resources to local AI clients.
# Sources (if present):
# - core/skills/, core/agents/, core/commands/
# - planets/*/skills/, planets/*/agents/, planets/*/commands/
# Targets:
# - .codex/skills
# - .claude/{skills,agents,commands}
# - .cursor/{skills,agents,commands}
#
# Naming:
# - core/ resources: unprefixed (e.g. solar-router, solar-telegram)
# - planets/* resources: always prefixed <planet-name>:<resource-name> (e.g. uhorizon:linkedin-prospecting)
#
# Usage:
#   bash core/scripts/sync-clients.sh [--codex-only|--claude-only|--cursor-only]

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SRC_SKILLS="$ROOT_DIR/core/skills"
SRC_AGENTS="$ROOT_DIR/core/agents"
SRC_COMMANDS="$ROOT_DIR/core/commands"
PLANETS_DIR="$ROOT_DIR/planets"

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

GEMINI_DIR="$ROOT_DIR/.gemini"
GEMINI_SETTINGS="$GEMINI_DIR/settings.json"
GEMINI_SKILLS="$GEMINI_DIR/skills"
GEMINI_COMMANDS="$GEMINI_DIR/commands"

SYNC_CODEX=false
SYNC_CLAUDE=false
SYNC_CURSOR=false
SYNC_GEMINI=false

# Temp directory for tracking
TEMP_DIR="$(mktemp -d)"
trap "rm -rf '$TEMP_DIR'" EXIT

SKILLS_INDEX="$TEMP_DIR/skills.txt"
AGENTS_INDEX="$TEMP_DIR/agents.txt"
COMMANDS_INDEX="$TEMP_DIR/commands.txt"

for arg in "$@"; do
  case "$arg" in
    --codex-only) SYNC_CODEX=true ;;
    --claude-only) SYNC_CLAUDE=true ;;
    --cursor-only) SYNC_CURSOR=true ;;
    --gemini-only) SYNC_GEMINI=true ;;
    -h|--help)
      echo "Usage: $0 [--codex-only|--claude-only|--cursor-only|--gemini-only]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if ! $SYNC_CODEX && ! $SYNC_CLAUDE && ! $SYNC_CURSOR && ! $SYNC_GEMINI; then
  SYNC_CODEX=true
  SYNC_CLAUDE=true
  SYNC_CURSOR=true
  SYNC_GEMINI=true
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

log_conflict() {
  echo -e "${RED}⚠ CONFLICT:${NC} $1"
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

# Check if a resource name is already indexed
# Args: index_file resource_name
is_duplicate() {
  local index_file="$1"
  local name="$2"
  [ -f "$index_file" ] || return 1
  while IFS='|' read -r indexed_name _; do
    [ "$indexed_name" = "$name" ] && return 0
  done < "$index_file"
  return 1
}

# Add resource to index
# Args: index_file resource_name source_path
add_to_index() {
  local index_file="$1"
  local name="$2"
  local source="$3"
  echo "$name|$source" >> "$index_file"
}

# Get source path for a resource name
# Args: index_file resource_name
get_source() {
  local index_file="$1"
  local name="$2"
  [ -f "$index_file" ] || return 0
  while IFS='|' read -r indexed_name source_path; do
    [ "$indexed_name" = "$name" ] && { echo "$source_path"; return 0; }
  done < "$index_file"
  return 0
}

# Discover all resources from core/ and planets/*/
discover_resources() {
  log_section "🔍 Discovering resources..."

  # Discover core skills
  if [ -d "$SRC_SKILLS" ]; then
    for item in "$SRC_SKILLS"/*; do
      [ -d "$item" ] || continue
      [ -f "$item/SKILL.md" ] || continue
      local name
      name="$(basename "$item")"
      add_to_index "$SKILLS_INDEX" "$name" "$item"
      log_ok "core/skills/$name"
    done
  fi

  # Discover core agents
  if [ -d "$SRC_AGENTS" ]; then
    shopt -s nullglob
    for file in "$SRC_AGENTS"/*.md; do
      [ -f "$file" ] || continue
      local name
      name="$(basename "$file")"
      add_to_index "$AGENTS_INDEX" "$name" "$file"
      log_ok "core/agents/$name"
    done
    shopt -u nullglob
  fi

  # Discover core commands
  if [ -d "$SRC_COMMANDS" ]; then
    shopt -s nullglob
    for file in "$SRC_COMMANDS"/*.md; do
      [ -f "$file" ] || continue
      local name
      name="$(basename "$file")"
      add_to_index "$COMMANDS_INDEX" "$name" "$file"
      log_ok "core/commands/$name"
    done
    shopt -u nullglob
  fi

  # Discover planet resources
  if [ -d "$PLANETS_DIR" ]; then
    for planet_dir in "$PLANETS_DIR"/*; do
      [ -d "$planet_dir" ] || continue
      local planet_name
      planet_name="$(basename "$planet_dir")"

      # Planet skills (always prefixed)
      if [ -d "$planet_dir/skills" ]; then
        for item in "$planet_dir/skills"/*; do
          [ -d "$item" ] || continue
          [ -f "$item/SKILL.md" ] || continue
          local name
          name="$(basename "$item")"
          local prefixed_name="$planet_name:$name"
          add_to_index "$SKILLS_INDEX" "$prefixed_name" "$item"
          log_ok "$prefixed_name"
        done
      fi

      # Planet agents (always prefixed)
      if [ -d "$planet_dir/agents" ]; then
        shopt -s nullglob
        for file in "$planet_dir/agents"/*.md; do
          [ -f "$file" ] || continue
          local name
          name="$(basename "$file")"
          local prefixed_name="$planet_name:$name"
          add_to_index "$AGENTS_INDEX" "$prefixed_name" "$file"
          log_ok "$prefixed_name"
        done
        shopt -u nullglob
      fi

      # Planet commands (always prefixed)
      if [ -d "$planet_dir/commands" ]; then
        shopt -s nullglob
        for file in "$planet_dir/commands"/*.md; do
          [ -f "$file" ] || continue
          local name
          name="$(basename "$file")"
          local prefixed_name="$planet_name:$name"
          add_to_index "$COMMANDS_INDEX" "$prefixed_name" "$file"
          log_ok "$prefixed_name"
        done
        shopt -u nullglob
      fi
    done
  fi

  echo
}

sync_resources_as_symlink() {
  local index_file="$1"
  local target_dir="$2"

  ensure_dir "$target_dir"

  # Clean old symlinks from core and planets to handle deleted resources
  clean_symlinks_from_prefix "$target_dir" "$ROOT_DIR/core"
  clean_symlinks_from_prefix "$target_dir" "$ROOT_DIR/planets"

  [ -f "$index_file" ] || return 0

  while IFS='|' read -r name source; do
    # Robustness: Remove the destination path if it exists, regardless of type.
    # This prevents 'ln' from failing if a directory exists where a symlink should be.
    rm -rf "$target_dir/$name"
    ln -s "$source" "$target_dir/$name"
    log_ok "$name"
  done < "$index_file"
}

sync_resources_as_copy() {
  local index_file="$1"
  local target_dir="$2"
  local is_dir="${3:-false}"

  ensure_dir "$target_dir"

  [ -f "$index_file" ] || return 0

  while IFS='|' read -r name source; do
    if [ "$is_dir" = "true" ]; then
      rm -rf "$target_dir/$name"
      cp -R "$source" "$target_dir/$name"
      log_ok "$name (copy)"
    else
      cp "$source" "$target_dir/$name"
      log_ok "$name (copy)"
    fi
  done < "$index_file"
}

sync_codex() {
  log_section "🔄 Codex (.codex)"
  log_section "📦 Skills"
  sync_resources_as_symlink "$SKILLS_INDEX" "$CODEX_SKILLS"
  echo
}

sync_claude() {
  log_section "🔄 Claude (.claude)"
  log_section "📦 Skills"
  sync_resources_as_symlink "$SKILLS_INDEX" "$CLAUDE_SKILLS"
  log_section "🤖 Agents"
  sync_resources_as_symlink "$AGENTS_INDEX" "$CLAUDE_AGENTS"
  log_section "🧩 Commands"
  sync_resources_as_symlink "$COMMANDS_INDEX" "$CLAUDE_COMMANDS"
  echo
}

sync_cursor() {
  log_section "🔄 Cursor (.cursor)"
  log_section "📦 Skills"
  sync_resources_as_copy "$SKILLS_INDEX" "$CURSOR_SKILLS" true
  log_section "🤖 Agents"
  sync_resources_as_copy "$AGENTS_INDEX" "$CURSOR_AGENTS" false
  log_section "🧩 Commands"
  sync_resources_as_copy "$COMMANDS_INDEX" "$CURSOR_COMMANDS" false
  echo
}

# sync_gemini_commands
# Converts .md command definitions to .toml for Gemini.
# Assumes .md format: First line is description, the rest is the prompt.
sync_gemini_commands() {
  local index_file="$1"
  local target_dir="$2"

  ensure_dir "$target_dir"

  # Clean old generated toml files and old md symlinks
  find "$target_dir" -name "*.toml" -type f -delete
  clean_symlinks_from_prefix "$target_dir" "$ROOT_DIR/core"
  clean_symlinks_from_prefix "$target_dir" "$ROOT_DIR/planets"

  [ -f "$index_file" ] || return 0

  while IFS='|' read -r name source; do
    # Convert name like 'cmd.md' to 'cmd.toml' or 'planet:cmd.md' to 'planet:cmd.toml'
    local toml_name=$(echo "$name" | sed 's/\.md$/.toml/')
    # Read first line for description, escape double quotes for TOML
    local description
    description=$(head -n 1 "$source" | sed 's/"/\\"/g')
    # Read the rest of the file for the prompt
    local prompt
    prompt=$(tail -n +2 "$source")

    # Create the .toml file from the .md source
    cat > "$target_dir/$toml_name" <<EOF
# Auto-generated from $source by sync-clients.sh
description = "$description"
prompt = """
$prompt
"""
EOF
    log_ok "$toml_name (generated from .md)"
  done < "$index_file"
}

sync_gemini() {
  log_section "🔄 Gemini (.gemini)"
  ensure_dir "$GEMINI_DIR"

  if [ ! -f "$GEMINI_SETTINGS" ]; then
    log_ok "Creating $GEMINI_SETTINGS with Solar defaults"
    cat > "$GEMINI_SETTINGS" <<EOF
{
  "general": {
    "enablePromptCompletion": true
  },
  "context": {
    "fileFiltering": {
      "respectGitIgnore": true
    }
  }
}
EOF
  else
    log_warn "$GEMINI_SETTINGS already exists. (Manual update required if settings are missing)"
  fi

  log_section "📦 Skills"
  sync_resources_as_symlink "$SKILLS_INDEX" "$GEMINI_SKILLS"
  log_section "🧩 Commands"
  sync_gemini_commands "$COMMANDS_INDEX" "$GEMINI_COMMANDS"
  echo
}

# Main execution
discover_resources

$SYNC_CODEX && sync_codex
$SYNC_CLAUDE && sync_claude
$SYNC_CURSOR && sync_cursor
$SYNC_GEMINI && sync_gemini

echo -e "${GREEN}✅ Sync complete.${NC}"
