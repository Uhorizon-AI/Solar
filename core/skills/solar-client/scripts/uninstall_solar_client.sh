#!/usr/bin/env bash
# uninstall_solar_client.sh — remove global wrapper + optional install tree.
# Never deletes user workspaces (sun/, planets/) unless they live inside --install-dir
# and you pass --remove-install (still does not scan ~/Solar workspace by default).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  bash uninstall_solar_client.sh [--remove-install] [--yes]

Removes:
  - wrapper at $SOLAR_BIN_DIR/solar (default ~/.local/bin/solar)
  - optional LaunchAgent label ai.uhorizon.solar (macOS) if present
  - with --remove-install: the global install dir (default ~/.local/share/solar)

Preserves by default:
  - workspace dirs (sun/, planets/) anywhere, including ~/Solar
  - user .env / credentials outside the install tree

Options:
  --remove-install  Also delete SOLAR_ROOT / ~/.local/share/solar
  --yes, -y         Non-interactive
  -h, --help        Show help
EOF
}

REMOVE_INSTALL=false
YES=false
WRAPPER_DIR="${SOLAR_BIN_DIR:-$HOME/.local/bin}"
SOLAR_BIN="$WRAPPER_DIR/solar"
if declare -F solar_client_default_install_dir >/dev/null 2>&1; then
  INSTALL_DIR="$(solar_client_default_install_dir)"
else
  INSTALL_DIR="${SOLAR_ROOT:-$HOME/.local/share/solar}"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove-install) REMOVE_INSTALL=true; shift ;;
    --yes|-y) YES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$REMOVE_INSTALL" == true && -d "$INSTALL_DIR" ]]; then
  install_parent="$(dirname "$INSTALL_DIR")"
  INSTALL_DIR="$(cd "$install_parent" && pwd -P)/$(basename "$INSTALL_DIR")"
  case "$INSTALL_DIR" in
    "/"|"$HOME"|"$HOME/Solar")
      echo "ERROR: refusing to delete broad or workspace path: $INSTALL_DIR" >&2
      exit 1
      ;;
  esac
  if [[ ! -d "$INSTALL_DIR/.git" \
     || ! -f "$INSTALL_DIR/core/skills/solar-client/scripts/solar" \
     || ! -f "$INSTALL_DIR/core/skills/solar-client/scripts/client_lib.sh" ]]; then
    echo "ERROR: refusing to delete path that is not a managed Solar install: $INSTALL_DIR" >&2
    exit 1
  fi
fi

echo "Solar uninstall"
echo "  wrapper=$SOLAR_BIN"
echo "  install=$INSTALL_DIR"
echo "  remove_install=$REMOVE_INSTALL"
echo ""

if [[ "$YES" != true ]]; then
  if [[ ! -t 0 ]]; then
    echo "ERROR: non-interactive shell requires --yes" >&2
    exit 2
  fi
  read -r -p "Proceed with uninstall? [y/N]: " -n 1 REPLY
  echo ""
  [[ "$REPLY" =~ ^[Yy]$ ]] || { echo "Cancelled"; exit 1; }
fi

if [[ -f "$SOLAR_BIN" ]]; then
  rm -f "$SOLAR_BIN"
  echo "OK: removed wrapper $SOLAR_BIN"
else
  echo "SKIP: wrapper not found"
fi

# Best-effort LaunchAgent cleanup (macOS)
if [[ "$(uname -s)" == "Darwin" ]]; then
  label="ai.uhorizon.solar"
  plist="$HOME/Library/LaunchAgents/${label}.plist"
  if [[ -f "$plist" ]]; then
    launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
    rm -f "$plist"
    echo "OK: removed LaunchAgent $plist"
  fi
fi

if [[ "$REMOVE_INSTALL" == true ]]; then
  if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    echo "OK: removed install $INSTALL_DIR"
  else
    echo "SKIP: install dir not found"
  fi
else
  echo "NOTE: install tree preserved at $INSTALL_DIR (pass --remove-install to delete)"
fi

echo ""
echo "Workspaces under ~/Solar (or elsewhere) were not deleted."
echo "OK: uninstall finished"
