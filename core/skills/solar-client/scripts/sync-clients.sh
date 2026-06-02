#!/usr/bin/env bash
# sync-clients.sh
# Sync Solar resources to local AI clients.
# Sources (if present):
# - core/skills/, core/agents/, core/commands/
# - planets/* → any */skills/*/SKILL.md under planets/*; planets/*/agents/, planets/*/commands/
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
#   bash core/scripts/sync-clients.sh [--codex-only|--claude-only|--cursor-only|--gemini-only|--vscode-only]

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

RESOLVE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve_solar_paths.sh"
# shellcheck source=/dev/null
source "$RESOLVE_SCRIPT"
solar_resolve_paths --quiet

ROOT_DIR="$SOLAR_WORKSPACE"
SRC_SKILLS="$(solar_core_dir)/skills"
SRC_AGENTS="$(solar_core_dir)/agents"
SRC_COMMANDS="$(solar_core_dir)/commands"
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
SYNC_VSCODE=false

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
    --vscode-only) SYNC_VSCODE=true ;;
    -h|--help)
      echo "Usage: $0 [--codex-only|--claude-only|--cursor-only|--gemini-only|--vscode-only]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if ! $SYNC_CODEX && ! $SYNC_CLAUDE && ! $SYNC_CURSOR && ! $SYNC_GEMINI && ! $SYNC_VSCODE; then
  SYNC_CODEX=true
  SYNC_CLAUDE=true
  SYNC_CURSOR=true
  SYNC_GEMINI=true
  SYNC_VSCODE=true
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

log_tree_mid() {
  local label="$1"
  local message="$2"
  echo -e " ├─ ${BLUE}${label}${NC}: ${message}"
}

log_tree_end() {
  local label="$1"
  local message="$2"
  echo -e " └─ ${BLUE}${label}${NC}: ${message}"
}

ensure_dir() {
  mkdir -p "$1"
}

index_has_name() {
  local index_file="$1"
  local wanted="$2"
  [ -f "$index_file" ] || return 1
  while IFS='|' read -r indexed_name _; do
    [ "$indexed_name" = "$wanted" ] && return 0
  done < "$index_file"
  return 1
}

index_has_toml_name() {
  local index_file="$1"
  local wanted="$2"
  [ -f "$index_file" ] || return 1
  while IFS='|' read -r indexed_name _; do
    local toml_name="${indexed_name%.md}.toml"
    [ "$toml_name" = "$wanted" ] && return 0
  done < "$index_file"
  return 1
}

prune_target_dir_to_index() {
  local index_file="$1"
  local target_dir="$2"
  local mode="${3:-direct}" # direct | md-to-toml

  [ -d "$target_dir" ] || return 0

  local removed=0
  shopt -s nullglob dotglob
  for item in "$target_dir"/*; do
    [ -e "$item" ] || continue
    local name
    name="$(basename "$item")"

    local should_keep=false
    if [ "$mode" = "md-to-toml" ]; then
      if index_has_toml_name "$index_file" "$name"; then
        should_keep=true
      fi
    else
      if index_has_name "$index_file" "$name"; then
        should_keep=true
      fi
    fi

    if [ "$should_keep" = false ]; then
      rm -rf "$item"
      removed=$((removed + 1))
    fi
  done
  shopt -u dotglob nullglob

  if [ "$removed" -gt 0 ]; then
    log_ok "Pruned $removed stale entries from $target_dir"
  fi
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

# Discover planet skills via find */skills/*/SKILL.md (supports nested structures like phuryn)
discover_planet_skills() {
  local planet_dir="$1"
  local planet_name="$2"
  while IFS= read -r skill_md; do
    local skill_dir
    skill_dir="$(dirname "$skill_md")"
    local name
    name="$(basename "$skill_dir")"
    local prefixed_name="$planet_name:$name"
    if is_duplicate "$SKILLS_INDEX" "$prefixed_name"; then
      log_warn "Duplicate skill $prefixed_name, skipping (first match wins)"
      continue
    fi
    add_to_index "$SKILLS_INDEX" "$prefixed_name" "$skill_dir"
  done < <(find "$planet_dir" -path "*/skills/*/SKILL.md" -type f 2>/dev/null | LC_ALL=C sort)
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
    done
    shopt -u nullglob
  fi

  # Discover planet resources
  if [ -d "$PLANETS_DIR" ]; then
    for planet_dir in "$PLANETS_DIR"/*; do
      [ -d "$planet_dir" ] || continue
      local planet_name
      planet_name="$(basename "$planet_dir")"

      # Planet skills (any */skills/*/SKILL.md under planet, always prefixed)
      discover_planet_skills "$planet_dir" "$planet_name"

      # Planet agents (always prefixed)
      if [ -d "$planet_dir/agents" ]; then
        shopt -s nullglob
        for file in "$planet_dir/agents"/*.md; do
          [ -f "$file" ] || continue
          local name
          name="$(basename "$file")"
          local prefixed_name="$planet_name:$name"
          add_to_index "$AGENTS_INDEX" "$prefixed_name" "$file"
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
        done
        shopt -u nullglob
      fi
    done
  fi

  local sc=0
  local ac=0
  local cc=0
  [ -f "$SKILLS_INDEX" ] && sc=$(wc -l < "$SKILLS_INDEX" | tr -d ' ')
  [ -f "$AGENTS_INDEX" ] && ac=$(wc -l < "$AGENTS_INDEX" | tr -d ' ')
  [ -f "$COMMANDS_INDEX" ] && cc=$(wc -l < "$COMMANDS_INDEX" | tr -d ' ')
  log_ok "Found $sc skills, $ac agents, $cc commands"
  echo
}

sync_resources_as_symlink() {
  local index_file="$1"
  local target_dir="$2"
  local label="$3"
  local branch="${4:-mid}"

  ensure_dir "$target_dir"

  # Strict mirror for managed folders: remove everything not in current index.
  prune_target_dir_to_index "$index_file" "$target_dir" "direct"

  [ -f "$index_file" ] || return 0

  local count=0
  while IFS='|' read -r name source; do
    # Robustness: Remove the destination path if it exists, regardless of type.
    # This prevents 'ln' from failing if a directory exists where a symlink should be.
    rm -rf "$target_dir/$name"
    ln -s "$source" "$target_dir/$name"
    count=$((count + 1))
  done < "$index_file"
  if [ "$branch" = "end" ]; then
    log_tree_end "$label" "${GREEN}✓${NC} $count (link)"
  else
    log_tree_mid "$label" "${GREEN}✓${NC} $count (link)"
  fi
}

sync_resources_as_copy() {
  local index_file="$1"
  local target_dir="$2"
  local is_dir="${3:-false}"
  local label="$4"
  local branch="${5:-mid}"

  ensure_dir "$target_dir"
  # Strict mirror for managed folders: remove everything not in current index.
  prune_target_dir_to_index "$index_file" "$target_dir" "direct"

  [ -f "$index_file" ] || return 0

  local count=0
  while IFS='|' read -r name source; do
    if [ "$is_dir" = "true" ]; then
      rm -rf "$target_dir/$name"
      cp -R "$source" "$target_dir/$name"
    else
      cp "$source" "$target_dir/$name"
    fi
    count=$((count + 1))
  done < "$index_file"
  if [ "$branch" = "end" ]; then
    log_tree_end "$label" "${GREEN}✓${NC} $count (copy)"
  else
    log_tree_mid "$label" "${GREEN}✓${NC} $count (copy)"
  fi
}

sync_codex() {
  log_section "🔄 Codex (.codex)"
  sync_resources_as_symlink "$SKILLS_INDEX" "$CODEX_SKILLS" "📦 Skills" "end"
  echo
}

sync_claude() {
  log_section "🔄 Claude (.claude)"
  sync_resources_as_symlink "$SKILLS_INDEX" "$CLAUDE_SKILLS" "📦 Skills" "mid"
  sync_resources_as_symlink "$AGENTS_INDEX" "$CLAUDE_AGENTS" "🤖 Agents" "mid"
  sync_resources_as_symlink "$COMMANDS_INDEX" "$CLAUDE_COMMANDS" "🧩 Commands" "end"
  echo
}

sync_cursor() {
  log_section "🔄 Cursor (.cursor)"
  sync_resources_as_copy "$SKILLS_INDEX" "$CURSOR_SKILLS" true "📦 Skills" "mid"
  sync_resources_as_copy "$AGENTS_INDEX" "$CURSOR_AGENTS" false "🤖 Agents" "mid"
  sync_resources_as_copy "$COMMANDS_INDEX" "$CURSOR_COMMANDS" false "🧩 Commands" "end"
  echo
}

# sync_gemini_commands
# Converts .md command definitions to .toml for Gemini.
# Assumes .md format: First line is description, the rest is the prompt.
sync_gemini_commands() {
  local index_file="$1"
  local target_dir="$2"
  local label="$3"
  local branch="${4:-mid}"

  ensure_dir "$target_dir"

  # Strict mirror for managed folders: keep only expected .toml command files.
  prune_target_dir_to_index "$index_file" "$target_dir" "md-to-toml"

  [ -f "$index_file" ] || return 0

  local count=0
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
    count=$((count + 1))
  done < "$index_file"
  if [ "$branch" = "end" ]; then
    log_tree_end "$label" "${GREEN}✓${NC} $count (toml)"
  else
    log_tree_mid "$label" "${GREEN}✓${NC} $count (toml)"
  fi
}

sync_gemini() {
  log_section "🔄 Gemini (.gemini)"
  ensure_dir "$GEMINI_DIR"

  if [ ! -f "$GEMINI_SETTINGS" ]; then
    log_tree_mid "⚙️  Settings" "${GREEN}✓${NC} Created settings.json"
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
    log_tree_mid "⚙️  Settings" "${YELLOW}⚠${NC} $GEMINI_SETTINGS already exists."
  fi

  sync_resources_as_symlink "$SKILLS_INDEX" "$GEMINI_SKILLS" "📦 Skills" "mid"
  sync_gemini_commands "$COMMANDS_INDEX" "$GEMINI_COMMANDS" "🧩 Commands" "end"
  echo
}

sync_vscode() {
  log_section "🔄 VS Code / Cursor Workspace Settings (.vscode)"
  local vscode_dir="$ROOT_DIR/.vscode"
  local vscode_settings="$vscode_dir/settings.json"

  if ! python3 -c "
import json
import os
import glob
import sys

workspace_root = sys.argv[1]
vscode_settings = sys.argv[2]
planets_dir = sys.argv[3]

def repo_has_git(rel_path: str) -> bool:
    return os.path.isdir(os.path.join(workspace_root, rel_path, '.git'))

discovered_repos = []
for name in ('sun', 'solar'):
    if repo_has_git(name):
        discovered_repos.append(name)

if os.path.isdir(planets_dir):
    for planet_path in glob.glob(os.path.join(planets_dir, '*')):
        if not os.path.isdir(planet_path):
            continue
        rel = f'planets/{os.path.basename(planet_path)}'
        if repo_has_git(rel):
            discovered_repos.append(rel)

discovered_repos = sorted(discovered_repos)

if os.path.exists(vscode_settings):
    try:
        with open(vscode_settings, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
else:
    data = {}

existing_scan_repos = data.get('git.scanRepositories', [])
if not isinstance(existing_scan_repos, list):
    existing_scan_repos = []

merged_scan_repos = []
seen = set()
for repo in discovered_repos + existing_scan_repos:
    if not isinstance(repo, str):
        continue
    repo = repo.strip().strip('/')
    if not repo or repo in seen:
        continue
    if not repo_has_git(repo):
        continue
    merged_scan_repos.append(repo)
    seen.add(repo)

data['explorer.excludeGitIgnore'] = False
data['search.useIgnoreFiles'] = False
data['git.autoRepositoryDetection'] = 'subFolders'
data['git.repositoryScanMaxDepth'] = 2
data['git.scanRepositories'] = merged_scan_repos
data['python.terminal.activateEnvironment'] = False

for exclude_key in ('files.exclude', 'search.exclude'):
    existing = data.get(exclude_key)
    if isinstance(existing, dict):
        existing.pop('.solar', None)
        if existing:
            data[exclude_key] = existing
        else:
            data.pop(exclude_key, None)

ignored_folders = data.get('git.repositoryScanIgnoredFolders')
if isinstance(ignored_folders, list):
    filtered_ignored_folders = [
        item for item in ignored_folders
        if item not in ('planets', 'sun', 'solar')
    ]
    if filtered_ignored_folders:
        data['git.repositoryScanIgnoredFolders'] = filtered_ignored_folders
    else:
        data.pop('git.repositoryScanIgnoredFolders', None)
else:
    data.pop('git.repositoryScanIgnoredFolders', None)

os.makedirs(os.path.dirname(vscode_settings), exist_ok=True)
with open(vscode_settings, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
" "$ROOT_DIR" "$vscode_settings" "$PLANETS_DIR"; then
    log_tree_mid "⚙️  Settings" "${RED}✗${NC} Failed to update $vscode_settings"
    return 1
  fi

  local git_repo_count=0
  git_repo_count="$(python3 -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
repos = data.get('git.scanRepositories', [])
print(len(repos) if isinstance(repos, list) else 0)
" "$vscode_settings" 2>/dev/null || echo 0)"
  log_tree_mid "⚙️  Settings" "${GREEN}✓${NC} Updated $vscode_settings"
  log_tree_end "📁 Git scan" "${GREEN}✓${NC} ${git_repo_count} subfolder repositories (sun, solar, planets/*)"
  echo
}

# Main execution
discover_resources

$SYNC_CLAUDE && sync_claude
$SYNC_CODEX && sync_codex
$SYNC_GEMINI && sync_gemini

$SYNC_VSCODE && sync_vscode
$SYNC_CURSOR && sync_cursor

echo -e "${GREEN}✅ Sync complete.${NC}"
