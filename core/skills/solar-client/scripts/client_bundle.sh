#!/usr/bin/env bash
# client_bundle.sh — workspace portable bundle (opt-in, Fase 3B).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

CHECK_ONLY=false

usage() {
  cat <<'EOF'
Usage:
  solar client bundle create [--check]
  solar client bundle verify
  solar client bundle remove

create writes .solar/bundle/ with the allowlisted core runtime so IDEs read the
snapshot instead of the global install. Settings become core_source=workspace-snapshot.
The LaunchAgent and solar client update keep using the global install.

remove returns settings to core_source=global through the canonical settings
writer, republishes IDE links from the global install, and moves .solar/bundle
aside when that directory exists. A missing or invalid snapshot does not block
this. It refuses before either step when no global install exists. If the
links cannot be rebuilt, the bundle stays and the command tells you to run
solar client sync.

Options:
  --check   Dry-run: report size and skill count without writing (create only)
  --verify  Validate existing bundle (alias of focused doctor checks)
EOF
}

ACTION=create
while [[ $# -gt 0 ]]; do
  case "$1" in
    create) ACTION=create; shift ;;
    verify) ACTION=verify; shift ;;
    remove) ACTION=remove; shift ;;
    --check) CHECK_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$ACTION" == "remove" && "$CHECK_ONLY" == true ]]; then
  echo "ERROR: bundle remove does not take --check" >&2
  exit 2
fi

if [[ "$ACTION" == "remove" ]]; then
  # Same shell as the resolver, so SOLAR_WORKSPACE stays exported. A SOLAR_ROOT
  # that still points at .solar/bundle is then excluded when locating the global
  # install. --skip-snapshot-check only skips the missing-bundle refusal.
  solar_resolve_paths --quiet --skip-snapshot-check
  solar_client_leave_portable "$SOLAR_WORKSPACE"
  exit $?
fi

solar_resolve_paths --quiet
WORKSPACE="$SOLAR_WORKSPACE"

CORE_SRC="$(solar_global_core_dir 2>/dev/null || true)"
if [[ -z "$CORE_SRC" || ! -d "$CORE_SRC/skills" ]]; then
  echo "ERROR: global Solar framework core/ not found — set SOLAR_ROOT to this machine's install" >&2
  exit 1
fi
BUNDLE_DIR="$(solar_client_bundle_dir "$WORKSPACE")"

if [[ "$ACTION" == "verify" ]]; then
  if solar_client_bundle_validate "$WORKSPACE" true; then
    echo "OK: workspace bundle valid"
    exit 0
  fi
  echo "ERROR: bundle validation failed" >&2
  exit 1
fi

META="$(python3 "$SCRIPT_DIR/client_bundle_build.py" \
  --workspace "$WORKSPACE" \
  --core-src "$CORE_SRC" \
  --bundle-dir "$BUNDLE_DIR" \
  $([[ "$CHECK_ONLY" == true ]] && echo --check-only))"

if [[ "$CHECK_ONLY" == true ]]; then
  echo "$META"
  exit 0
fi

BUNDLE_HASH="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["checksum"])' "$META")"
FILE_COUNT="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["file_count"])' "$META")"
SKILL_COUNT="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["skill_count"])' "$META")"
CAPS="$(python3 -c 'import json,sys; print(",".join(json.loads(sys.argv[1])["skills"]))' "$META")"

MAX_MB="$(solar_client_max_bundle_mb)"
SIZE_MB="$(solar_client_bundle_size_mb "$BUNDLE_DIR")"
if python3 - <<PY "$SIZE_MB" "$MAX_MB"
import sys
sys.exit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)
PY
then
  :
else
  echo "ERROR: bundle size ${SIZE_MB}MB exceeds max ${MAX_MB}MB (set SOLAR_MAX_BUNDLE_MB to override)" >&2
  exit 1
fi

if ! solar_client_bundle_validate "$WORKSPACE" false; then
  echo "ERROR: bundle validation failed after create" >&2
  exit 1
fi

solar_client_write_manifest_portable "$WORKSPACE" "$BUNDLE_HASH" "$CAPS"

echo "OK: workspace bundle created at $BUNDLE_DIR"
echo "  files=$FILE_COUNT skills=$SKILL_COUNT size=${SIZE_MB}MB checksum=${BUNDLE_HASH:0:16}..."
echo "  core_source=workspace-snapshot (portable)"
echo "Next: solar client sync  (IDE targets on this machine)"
