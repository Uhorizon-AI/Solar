#!/usr/bin/env bash
# Map deprecated workspace .env keys to SOLAR_APP_* (call after sourcing .env).
set -euo pipefail

solar_app_apply_legacy_env() {
  if [[ -z "${SOLAR_APP_HOST:-}" ]]; then
    if [[ -n "${SOLAR_HOST_HOST:-}" ]]; then
      export SOLAR_APP_HOST="${SOLAR_HOST_HOST}"
    elif [[ -n "${SOLAR_INTERFACE_HOST:-}" ]]; then
      export SOLAR_APP_HOST="${SOLAR_INTERFACE_HOST}"
    fi
  fi
  if [[ -z "${SOLAR_APP_PORT:-}" ]]; then
    if [[ -n "${SOLAR_HOST_PORT:-}" ]]; then
      export SOLAR_APP_PORT="${SOLAR_HOST_PORT}"
    elif [[ -n "${SOLAR_INTERFACE_PORT:-}" ]]; then
      export SOLAR_APP_PORT="${SOLAR_INTERFACE_PORT}"
    fi
  fi
}
