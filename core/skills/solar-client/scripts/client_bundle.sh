#!/usr/bin/env bash
# client_bundle.sh — workspace portable bundle (opt-in, Fase 3B).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

CHECK_ONLY=false
VERIFY_ONLY=false

usage() {
  cat <<'EOF'
Usage:
  solar client bundle create [--check]
  solar client bundle verify

Creates .solar/bundle/ with allowlisted core runtime for machines without SOLAR_ROOT.
Updates manifest to core_source=workspace-snapshot.

Options:
  --check   Dry-run: report size and skill count without writing
  --verify  Validate existing bundle (alias of focused doctor checks)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    create) shift; continue ;;
    verify) VERIFY_ONLY=true; shift; continue ;;
    --check) CHECK_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

solar_resolve_paths --quiet
WORKSPACE="$SOLAR_WORKSPACE"
CORE_SRC="$(solar_global_core_dir 2>/dev/null || true)"
if [[ -z "$CORE_SRC" || ! -d "$CORE_SRC/skills" ]]; then
  echo "ERROR: global Solar framework core/ not found — set SOLAR_ROOT or run from primary machine" >&2
  exit 1
fi
BUNDLE_DIR="$(solar_client_bundle_dir "$WORKSPACE")"

if [[ "$VERIFY_ONLY" == true ]]; then
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
echo "Next: solar client sync  (IDE targets; optional on secondary machines)"
