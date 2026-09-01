#!/usr/bin/env bash
# workspace_doctor.sh — sun/ + planets/ health (solar workspace doctor).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CLIENT_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-client/scripts" && pwd)"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$_CLIENT_SCRIPTS/resolve_solar_paths.sh"

STRICT=false
CHECK_GIT=false
CHECK_PLANS=false
NO_SUMMARY=false
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Usage: solar workspace doctor [--strict] [--check-git] [--check-plans] [--no-summary]

Checks sun/ and planets/ layout (not manifest, bundle, or IDE sync — use solar client doctor).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict) STRICT=true; shift ;;
    --check-git) CHECK_GIT=true; shift ;;
    --check-plans) CHECK_PLANS=true; shift ;;
    --no-summary) NO_SUMMARY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  echo "Unknown option(s): ${EXTRA_ARGS[*]}" >&2
  exit 2
fi

solar_resolve_paths --quiet

SUN_DOCTOR="$SCRIPT_DIR/sun-workspace-doctor.sh"
PLANETS_DOCTOR="$SCRIPT_DIR/planets-workspace-doctor.sh"

err_count=0
warn_count=0

if [[ ! -f "$SUN_DOCTOR" ]]; then
  echo "ERROR: sun-workspace-doctor.sh not found under $(solar_core_dir)/scripts" >&2
  exit 1
fi

_sun_args=(--no-summary)
[[ "$CHECK_GIT" == true ]] && _sun_args+=(--check-git)
[[ "$CHECK_PLANS" == true ]] && _sun_args+=(--check-plans)
[[ "$NO_SUMMARY" == true ]] && _sun_args+=(--no-summary)

echo "=== sun/ workspace ==="
if ! bash "$SUN_DOCTOR" "${_sun_args[@]}"; then
  err_count=$((err_count + 1))
fi

if [[ -f "$PLANETS_DOCTOR" ]]; then
  echo ""
  echo "=== planets/ workspace ==="
  _planets_args=()
  [[ "$CHECK_GIT" == true ]] && _planets_args+=(--check-git)
  if [[ ${#_planets_args[@]} -gt 0 ]]; then
    _planets_run=(bash "$PLANETS_DOCTOR" "${_planets_args[@]}")
  else
    _planets_run=(bash "$PLANETS_DOCTOR")
  fi
  if ! "${_planets_run[@]}"; then
    err_count=$((err_count + 1))
  fi
else
  echo "WARN: planets-workspace-doctor.sh not found" >&2
  warn_count=$((warn_count + 1))
fi

if [[ "$NO_SUMMARY" != true ]]; then
  echo ""
  echo "Summary: $err_count error(s), $warn_count warning(s)"
fi

[[ "$err_count" -eq 0 ]]
