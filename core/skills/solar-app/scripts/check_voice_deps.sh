#!/usr/bin/env bash
# Deprecated — use solar voice doctor
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "NOTE: check_voice_deps.sh → use: solar voice doctor" >&2
exec bash "$SCRIPT_DIR/voice_doctor.sh" "$@"
