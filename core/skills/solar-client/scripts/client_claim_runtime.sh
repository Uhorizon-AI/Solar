#!/usr/bin/env bash
# solar client claim-runtime — rebind a moved workspace, or repair divergent ids.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

REBIND=false
REPAIR=false
KEEP=""

usage() {
  cat <<'EOF'
Usage:
  solar client claim-runtime [--rebind]
  solar client claim-runtime --repair [--keep owner|settings]

--rebind updates the recorded path when it still exists and the id matches.
--repair shows both ids and writes nothing unless --keep names which one wins.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebind) REBIND=true; shift ;;
    --repair) REPAIR=true; shift ;;
    --keep)
      if [[ $# -lt 2 || -z "${2:-}" || "$2" == -* ]]; then
        echo "ERROR: --keep needs a value: owner or settings" >&2
        usage >&2
        exit 2
      fi
      KEEP="$2"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$REPAIR" == true && "$REBIND" == true ]]; then
  echo "ERROR: --repair and --rebind are different operations" >&2
  exit 2
fi

if [[ -n "$KEEP" && "$REPAIR" != true ]]; then
  echo "ERROR: --keep requires --repair" >&2
  usage >&2
  exit 2
fi

solar_resolve_paths --quiet
INSTALL_ROOT="$SOLAR_ROOT"
state_py="$(solar_client_state_py "$INSTALL_ROOT")"

if [[ "$REPAIR" == true ]]; then
  settings_id="$(solar_client_settings_workspace_id "$SOLAR_WORKSPACE")"
  if ! owner_json="$(python3 "$state_py" owner show 2>/dev/null)"; then
    echo "ERROR: cannot read the workspace owner" >&2
    exit 1
  fi
  owner_id="$(printf '%s' "$owner_json" | python3 -c 'import json,sys; data=json.load(sys.stdin); print("" if not data else data.get("workspace_id",""))')"
  if [[ -z "$owner_id" || -z "$settings_id" ]]; then
    echo "owner: ${owner_id:-<missing>}"
    echo "settings: ${settings_id:-<missing>}"
    echo "ERROR: repair needs both ids. Nothing was written." >&2
    exit 1
  fi
  if [[ -z "$KEEP" ]]; then
    echo "owner: $owner_id"
    echo "settings: $settings_id"
    if [[ "$owner_id" == "$settings_id" ]]; then
      echo "OK: both ids already match. Nothing was written."
      exit 0
    fi
    echo "Refusing to write. Re-run with --keep owner or --keep settings." >&2
    exit 1
  fi
  case "$KEEP" in
    owner)
      solar_client_settings_set_workspace_id "$SOLAR_WORKSPACE" "$owner_id"
      echo "OK: settings workspace_id is now the owner id $owner_id"
      ;;
    settings)
      python3 "$state_py" owner replace-id --id "$settings_id" >/dev/null
      echo "OK: workspace-owner.json id is now the settings id $settings_id"
      ;;
    *)
      echo "ERROR: --keep must be owner or settings" >&2
      exit 2
      ;;
  esac
  exit 0
fi

if [[ "$REBIND" == true ]]; then
  solar_client_claim_workspace "$SOLAR_WORKSPACE" true "$INSTALL_ROOT"
else
  solar_client_claim_workspace "$SOLAR_WORKSPACE" false "$INSTALL_ROOT"
fi
