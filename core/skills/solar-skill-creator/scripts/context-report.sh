#!/usr/bin/env bash
set -euo pipefail

_RESOLVE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-client/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=/dev/null
source "$_RESOLVE_SCRIPT"
solar_resolve_paths --quiet

ROOT_DIR="$SOLAR_WORKSPACE"
TARGET_INPUT="${1:-}"
LIMIT="${2:-25}"

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Usage: bash core/scripts/context-report.sh [target_path] [limit]" >&2
  exit 2
fi

TARGET_PATH=""
if [[ -n "$TARGET_INPUT" ]]; then
  if [[ -e "$TARGET_INPUT" ]]; then
    if [[ -d "$TARGET_INPUT" ]]; then
      TARGET_PATH="$(cd "$TARGET_INPUT" && pwd)"
    else
      TARGET_PATH="$(cd "$(dirname "$TARGET_INPUT")" && pwd)/$(basename "$TARGET_INPUT")"
    fi
  else
    TARGET_PATH="$TARGET_INPUT"
  fi
fi

TMP_FILE="$(mktemp "${TMPDIR:-/tmp}/context-report.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT

add_file() {
  local file="$1"
  local rel lines chars tokens status

  [[ -f "$file" ]] || return 0
  rel="${file#$ROOT_DIR/}"

  if [[ -n "$TARGET_PATH" ]]; then
    if [[ "$TARGET_PATH" == /* ]]; then
      if [[ "$file" != "$TARGET_PATH" && "$file" != "$TARGET_PATH"/* ]]; then
        return 0
      fi
    else
      if [[ "$rel" != *"$TARGET_PATH"* ]]; then
        return 0
      fi
    fi
  fi

  read -r lines chars < <(wc -lm < "$file")
  tokens=$(( (chars + 3) / 4 ))
  status="ok"

  if [[ "$rel" == *"/SKILL.md" || "$rel" == "AGENTS.md" || "$rel" == *"/AGENTS.md" || "$rel" == *"/MEMORY.md" || "$rel" == planets/*/agents/* || "$rel" == planets/*/commands/* ]]; then
    if (( lines > 500 )); then
      status="large"
    elif (( lines > 300 )); then
      status="watch"
    fi
  fi

  local status_weight=3
  if [[ "$status" == "large" ]]; then
    status_weight=1
  elif [[ "$status" == "watch" ]]; then
    status_weight=2
  fi

  local group_name="core"
  if [[ "$rel" =~ ^planets/([^/]+) ]]; then
    group_name="planets/${BASH_REMATCH[1]}"
  fi

  printf "%d\t%s\t%d\t%d\t%d\t%s\t%s\n" "$status_weight" "$group_name" "$tokens" "$lines" "$chars" "$status" "$rel" >> "$TMP_FILE"
}

collect_find() {
  local base="$1"
  shift
  local file

  while IFS= read -r -d '' file; do
    add_file "$file"
  done < <(find "$base" "$@" -type f -print0 2>/dev/null)
}

collect_planet_top_level_dir() {
  local dir_name="$1"
  local planet_dir resource_dir file

  while IFS= read -r -d '' planet_dir; do
    resource_dir="$planet_dir/$dir_name"
    [[ -d "$resource_dir" ]] || continue
    while IFS= read -r -d '' file; do
      add_file "$file"
    done < <(find "$resource_dir" -maxdepth 1 -type f -print0 2>/dev/null)
  done < <(find "$ROOT_DIR/planets" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
}

add_file "$ROOT_DIR/AGENTS.md"
add_file "$ROOT_DIR/core/AGENTS.md"
add_file "$ROOT_DIR/core/templates/planet-AGENTS.md"
add_file "$ROOT_DIR/sun/MEMORY.md"
add_file "$ROOT_DIR/sun/preferences/profile.md"

collect_find "$ROOT_DIR/core/skills" -mindepth 2 -maxdepth 2 -name "SKILL.md"
collect_find "$ROOT_DIR/planets" -mindepth 2 -maxdepth 2 \( -name "AGENTS.md" -o -name "MEMORY.md" \)
collect_find "$ROOT_DIR/planets" -mindepth 4 -maxdepth 4 -path "*/skills/*/SKILL.md"
collect_planet_top_level_dir "agents"
collect_planet_top_level_dir "commands"

echo "Solar context report"
echo "Root: $ROOT_DIR"
if [[ -n "$TARGET_INPUT" ]]; then
  echo "Filter: $TARGET_INPUT"
fi
echo "Estimate: tokens ~= characters / 4; directional only, not billing."
echo
printf "%8s  %7s  %9s  %-6s  %s\n" "tokens" "lines" "chars" "status" "file"
printf "%8s  %7s  %9s  %-6s  %s\n" "------" "-----" "-----" "------" "----"

sort -t$'\t' -k1,1n -k2,2 -k3,3rn "$TMP_FILE" | head -n "$LIMIT" | while IFS=$'\t' read -r weight group tokens lines chars status rel; do
  printf "%8d  %7d  %9d  %-6s  %s\n" "$tokens" "$lines" "$chars" "$status" "$rel"
done

echo
echo "Status thresholds for active context files: watch >300 lines, large >500 lines."
