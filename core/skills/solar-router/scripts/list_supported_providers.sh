#!/usr/bin/env bash
# List providers registered in solar-router PROVIDERS (canonical source of truth).
# Parses providers/__init__.py without importing BaseProvider (avoids path resolve).
#
# Usage:
#   bash core/skills/solar-router/scripts/list_supported_providers.sh
#   bash core/skills/solar-router/scripts/list_supported_providers.sh --format csv
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

format="lines"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --format)
      format="${2:-lines}"
      shift 2
      ;;
    -h|--help)
      echo "Usage: list_supported_providers.sh [--format lines|csv]" >&2
      exit 0
      ;;
    *)
      echo "Usage: list_supported_providers.sh [--format lines|csv]" >&2
      exit 1
      ;;
  esac
done

PROVIDERS_INIT="$SCRIPT_DIR/providers/__init__.py"
export PROVIDERS_INIT
providers="$(python3 -c '
import os, re, pathlib
path = pathlib.Path(os.environ["PROVIDERS_INIT"])
text = path.read_text()
block = re.search(r"PROVIDERS\s*=\s*\{([^}]+)\}", text, re.S)
if not block:
    raise SystemExit("PROVIDERS dict not found in providers/__init__.py")
keys = re.findall(r"[\"'"'"'](\w+)[\"'"'"']\s*:", block.group(1))
if not keys:
    raise SystemExit("no provider keys found in PROVIDERS")
print("\n".join(sorted(keys)))
')"

if [[ "$format" == "csv" ]]; then
  echo "$providers" | paste -sd, -
else
  echo "$providers"
fi
