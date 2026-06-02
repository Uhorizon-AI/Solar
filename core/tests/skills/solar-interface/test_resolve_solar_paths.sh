#!/usr/bin/env bash
# Deprecated location — canonical tests live in solar-client.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/../solar-client/test_resolve_solar_paths.sh"
