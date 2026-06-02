#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CLIENT_RESOLVE="$(cd "$SCRIPT_DIR/../../solar-client/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$_CLIENT_RESOLVE"
solar_resolve_paths --quiet

echo "SOLAR_WORKSPACE=$SOLAR_WORKSPACE"
echo "SOLAR_ROOT=$SOLAR_ROOT"
echo ""
echo "# IDE @path references (paths relative to workspace root)"

_paths_emit() {
  local rel="$1"
  if [[ -e "$SOLAR_WORKSPACE/$rel" ]]; then
    echo "@$rel"
  fi
}

_paths_emit "sun/"
_paths_emit "sun/preferences/profile.md"
_paths_emit "sun/MEMORY.md"
_paths_emit "sun/plans/"
_paths_emit "planets/"

if [[ -d "$(solar_core_dir)/skills" ]]; then
  echo "@core/skills/  -> $(solar_core_dir)/skills/"
fi
