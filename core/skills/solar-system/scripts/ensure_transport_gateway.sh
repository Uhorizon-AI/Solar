#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

check_cmd="bash core/skills/solar-transport-gateway/scripts/check_transport_gateway.sh"
setup_cmd="bash core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh"

set +e
check_out="$($check_cmd 2>&1)"
check_code=$?
set -e

if [[ -n "$check_out" ]]; then
  echo "$check_out"
fi

case "$check_code" in
  0)
    echo "✅ Transport gateway healthy. No action needed."
    exit 0
    ;;
  1)
    echo "⚠️  Transport gateway is down. Running setup recovery..."
    $setup_cmd
    ;;
  2)
    # check_transport_gateway.sh marks this as public tunnel degradation.
    # Using setup script here is safer than starting a foreground tunnel process.
    echo "⚠️  Transport gateway partial state detected. Running setup recovery..."
    $setup_cmd
    ;;
  *)
    echo "❌ Unexpected transport gateway check code: $check_code" >&2
    exit "$check_code"
    ;;
esac
