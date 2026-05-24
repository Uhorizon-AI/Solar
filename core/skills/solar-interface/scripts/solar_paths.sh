#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_home.sh
source "$SCRIPT_DIR/resolve_solar_home.sh"
solar_resolve_home --quiet

echo "SOLAR_HOME=$SOLAR_HOME"
echo "SOLAR_CORE_ROOT=$SOLAR_CORE_ROOT"
echo "REPO_ROOT=$REPO_ROOT"
echo ""
echo "# IDE @path references (paths relative to workspace root)"

_paths_emit() {
  local rel="$1"
  if [[ -e "$SOLAR_HOME/$rel" ]]; then
    echo "@$rel"
  fi
}

_paths_emit "sun/"
_paths_emit "sun/preferences/profile.md"
_paths_emit "sun/MEMORY.md"
_paths_emit "sun/plans/"
_paths_emit "planets/"

if [[ -d "$SOLAR_HOME/.solar/core/skills" ]]; then
  echo "@.solar/core/skills/  -> $SOLAR_CORE_ROOT/skills/"
elif [[ -d "$SOLAR_CORE_ROOT/skills" ]]; then
  echo "@core/skills/  -> $SOLAR_CORE_ROOT/skills/"
fi
