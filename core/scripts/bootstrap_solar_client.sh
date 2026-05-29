#!/usr/bin/env bash
# bootstrap_solar_client.sh — curl-friendly installer entrypoint (Fase 3D).
set -euo pipefail

TAG="${SOLAR_CLIENT_TAG:-v0.14.0}"
INSTALL_DIR="${SOLAR_INSTALL_DIR:-$HOME/Solar/solar}"
REPO_URL="${SOLAR_REPO_URL:-https://github.com/louisjimenezp/solar.git}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ -n "${SOLAR_BOOTSTRAP_FROM_LOCAL:-}" && -f "$SOLAR_BOOTSTRAP_FROM_LOCAL" ]]; then
  bash "$SOLAR_BOOTSTRAP_FROM_LOCAL" --install-dir "$INSTALL_DIR" --tag "$TAG" --yes
  exit $?
fi

git clone --depth 1 --branch "$TAG" "$REPO_URL" "$TMP/solar" 2>/dev/null \
  || git clone --depth 1 "$REPO_URL" "$TMP/solar"

INSTALLER="$TMP/solar/core/scripts/install_solar_client.sh"
[[ -f "$INSTALLER" ]] || { echo "ERROR: installer not found in repo checkout" >&2; exit 1; }

bash "$INSTALLER" --install-dir "$INSTALL_DIR" --tag "$TAG" --yes
