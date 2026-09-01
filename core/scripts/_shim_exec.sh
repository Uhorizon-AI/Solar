#!/usr/bin/env bash
# Internal helper for deprecated core/scripts shims.
set -euo pipefail
_REL="$1"
shift
_TARGET="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$_REL"
if [[ ! -f "$_TARGET" ]]; then
  echo "ERROR: relocated script missing: $_TARGET" >&2
  exit 1
fi
echo "DEPRECATED: use $_REL (moved from core/scripts/)" >&2
exec bash "$_TARGET" "$@"
