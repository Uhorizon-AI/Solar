#!/usr/bin/env bash
# check-mcp.sh
# Check whether MCP requirements declared in a SKILL.md are present
# in local Codex config.
#
# Usage:
#   bash core/scripts/check-mcp.sh --skill path/to/SKILL.md

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$ROOT_DIR/.codex}"

usage() {
  echo "Usage: $0 --skill path/to/SKILL.md"
}

SKILL_PATH=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skill)
      SKILL_PATH="${2:-}"
      shift 2
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

if [[ -z "$SKILL_PATH" ]]; then
  usage
  exit 1
fi

if [[ ! -f "$SKILL_PATH" ]]; then
  echo "ERROR: SKILL.md not found: $SKILL_PATH" >&2
  exit 1
fi

extract_required_mcp() {
  local file="$1"
  awk '
    BEGIN { in_section=0 }
    /^## Required MCP[[:space:]]*$/ { in_section=1; next }
    /^## / && in_section==1 { exit }
    in_section==1 {
      line=$0
      gsub(/^[[:space:]]*[-*][[:space:]]*/, "", line)
      gsub(/`/, "", line)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      if (length(line) > 0) print line
    }
  ' "$file"
}

normalize_mcp_list() {
  awk '
    {
      l=tolower($0)
      if (l=="none" || l=="n/a" || l=="not required") next
      print $0
    }
  '
}

collect_config_files() {
  local files=()
  [[ -f "$CODEX_HOME_DIR/config.toml" ]] && files+=("$CODEX_HOME_DIR/config.toml")
  [[ -f "$ROOT_DIR/.codex/config.toml" ]] && files+=("$ROOT_DIR/.codex/config.toml")
  [[ -f "$HOME/.codex/config.toml" ]] && files+=("$HOME/.codex/config.toml")
  printf '%s\n' "${files[@]}" | awk 'NF' | awk '!seen[$0]++'
}

extract_configured_mcp_names() {
  local file="$1"
  awk '
    # Pattern: [mcp_servers.name]
    match($0, /^\[mcp_servers\.([^\]]+)\]/, a) { print a[1]; next }

    # Pattern: [[mcp.servers]] then name = "..."
    /^\[\[mcp\.servers\]\]/ { in_mcp_block=1; next }
    /^\[/ && $0 !~ /^\[\[mcp\.servers\]\]/ { in_mcp_block=0 }
    in_mcp_block && match($0, /^[[:space:]]*name[[:space:]]*=[[:space:]]*"([^"]+)"/, b) {
      print b[1]
    }
  ' "$file"
}

REQUIRED_RAW="$(extract_required_mcp "$SKILL_PATH" || true)"
if [[ -z "${REQUIRED_RAW// }" ]]; then
  echo "WARN: '## Required MCP' section is missing or empty in $SKILL_PATH"
  exit 2
fi

REQUIRED_MCP="$(printf '%s\n' "$REQUIRED_RAW" | normalize_mcp_list | awk '!seen[$0]++')"
if [[ -z "${REQUIRED_MCP// }" ]]; then
  echo "OK: Skill does not require MCP (Required MCP = None)"
  exit 0
fi

CONFIG_FILES="$(collect_config_files || true)"
if [[ -z "${CONFIG_FILES// }" ]]; then
  echo "WARN: No Codex config.toml found. Cannot validate MCP availability."
  echo "Required MCP:"
  printf ' - %s\n' $REQUIRED_MCP
  exit 2
fi

CONFIGURED_MCP=""
while IFS= read -r cfg; do
  [[ -z "$cfg" ]] && continue
  names="$(extract_configured_mcp_names "$cfg" || true)"
  if [[ -n "${names// }" ]]; then
    CONFIGURED_MCP+=$'\n'"$names"
  fi
done <<< "$CONFIG_FILES"

CONFIGURED_MCP="$(printf '%s\n' "$CONFIGURED_MCP" | awk 'NF' | awk '!seen[$0]++')"

if [[ -z "${CONFIGURED_MCP// }" ]]; then
  echo "WARN: No MCP server names detected in config files:"
  while IFS= read -r cfg; do
    [[ -n "$cfg" ]] && echo " - $cfg"
  done <<< "$CONFIG_FILES"
  echo "Required MCP:"
  printf ' - %s\n' $REQUIRED_MCP
  exit 2
fi

missing=0
while IFS= read -r required; do
  [[ -z "$required" ]] && continue
  if ! printf '%s\n' "$CONFIGURED_MCP" | grep -Fxq "$required"; then
    if [[ $missing -eq 0 ]]; then
      echo "MISSING MCP:"
    fi
    echo " - $required"
    missing=1
  fi
done <<< "$REQUIRED_MCP"

if [[ $missing -eq 1 ]]; then
  echo ""
  echo "Configured MCP found:"
  printf ' - %s\n' $CONFIGURED_MCP
  echo ""
  echo "Action: install/configure missing MCP or use the skill fallback mode."
  exit 3
fi

echo "OK: all required MCP servers are configured for this skill."
