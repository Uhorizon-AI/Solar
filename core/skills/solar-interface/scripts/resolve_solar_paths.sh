#!/usr/bin/env bash
# Shim (one release): canonical resolver lives in solar-client.
set -euo pipefail
_CLIENT_RESOLVE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-client/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$_CLIENT_RESOLVE"
