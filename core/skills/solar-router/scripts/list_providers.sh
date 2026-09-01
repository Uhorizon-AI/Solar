#!/usr/bin/env bash
# List configured AI providers, one per line.
# Reads SOLAR_ROUTER_PROVIDER_PRIORITY (fallback: codex,claude,agy,agent).
#
# Usage:
#   bash core/skills/solar-router/scripts/list_providers.sh
#   bash core/skills/solar-router/scripts/list_providers.sh --exclude claude
#   bash core/skills/solar-router/scripts/list_providers.sh --exclude claude --format csv

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPT="$(cd "$SCRIPT_DIR/../../solar-client/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=/dev/null
source "$RESOLVE_SCRIPT"
solar_resolve_paths --quiet
SOLAR_WORKSPACE="${SOLAR_WORKSPACE:-$SOLAR_WORKSPACE}"
ROOT_ENV_FILE="$SOLAR_WORKSPACE/.env"

exclude=""
format="lines"  # lines | csv

while [[ $# -gt 0 ]]; do
  case "$1" in
    --exclude)
      exclude="${2:-}"
      shift 2
      ;;
    --format)
      format="${2:-lines}"
      shift 2
      ;;
    *)
      echo "Usage: list_providers.sh [--exclude <provider>] [--format lines|csv]" >&2
      exit 1
      ;;
  esac
done

# Load .env if present (picks up SOLAR_ROUTER_PROVIDER_PRIORITY)
if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-codex,claude,agy,agent}}"

# Deduplicate, trim whitespace, lowercase, optionally exclude one provider
result="$(echo "$priority" | awk -F',' -v excl="$exclude" '
  {
    for (i = 1; i <= NF; i++) {
      p = $i
      gsub(/^[ \t]+|[ \t]+$/, "", p)
      p = tolower(p)
      if (p == "" || p == excl) continue
      if (!(p in seen)) {
        seen[p] = 1
        list[++n] = p
      }
    }
  }
  END {
    for (i = 1; i <= n; i++) print list[i]
  }
')"

if [[ -z "$result" ]]; then
  echo "Error: no providers available (SOLAR_ROUTER_PROVIDER_PRIORITY empty or all excluded)" >&2
  exit 1
fi

if [[ "$format" == "csv" ]]; then
  echo "$result" | paste -sd ',' -
else
  echo "$result"
fi
