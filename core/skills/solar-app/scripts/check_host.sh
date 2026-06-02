#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

if curl -fsS --max-time 3 "$SOLAR_HOST_BASE_URL/health" >/dev/null 2>&1; then
  [[ "$QUIET" != true ]] && echo "OK: Solar Host reachable at $SOLAR_HOST_BASE_URL"
  exit 0
fi
[[ "$QUIET" != true ]] && echo "FAIL: Solar Host not reachable at $SOLAR_HOST_BASE_URL"
exit 1
