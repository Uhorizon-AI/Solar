#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"
solar_resolve_paths --quiet
bash "$(solar_core_dir)/scripts/sync-clients.sh" "$@"
solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
global_ver="$(solar_client_git_identity "$SOLAR_ROOT" | awk '{print $1}')"
python3 - <<PY "$SOLAR_WORKSPACE/.solar/manifest.json" "$global_ver"
import json, sys
path, gv = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except FileNotFoundError:
    sys.exit(0)
data["core_version"] = gv
data["client_version"] = gv
data["core_source"] = "global"
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
