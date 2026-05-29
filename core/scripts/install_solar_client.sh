#!/usr/bin/env bash
# install_solar_client.sh — global Solar Client install (Fase 3D).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash install_solar_client.sh [--install-dir <path>] [--tag <ref>] [--yes]

Installs Solar framework to ~/Solar/solar (or --install-dir) and adds a solar wrapper to PATH.

Options:
  --install-dir <path>  Install root (default: ~/Solar/solar)
  --tag <ref>           Git tag/ref to checkout (default: latest origin/main tag)
  --yes, -y             Non-interactive
  --help                Show help

After install:
  export PATH="$INSTALL_DIR/core/skills/solar-interface/scripts:$PATH"
  cd ~/your-workspace && solar client init && solar client sync
EOF
}

INSTALL_DIR="${SOLAR_ROOT:-$HOME/Solar/solar}"
TAG=""
YES=false
REPO_URL="${SOLAR_REPO_URL:-https://github.com/louisjimenezp/solar.git}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --yes|-y) YES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

INSTALL_DIR="$(cd "$(dirname "$INSTALL_DIR")" && pwd)/$(basename "$INSTALL_DIR")"
WRAPPER_DIR="${SOLAR_BIN_DIR:-$HOME/.local/bin}"
SOLAR_BIN="$WRAPPER_DIR/solar"
SOLAR_CLI="$INSTALL_DIR/core/skills/solar-interface/scripts/solar"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "INFO: existing install at $INSTALL_DIR — updating"
  if [[ -n "$TAG" ]]; then
    git -C "$INSTALL_DIR" fetch --tags origin
    git -C "$INSTALL_DIR" checkout "$TAG"
  else
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" pull --ff-only origin main 2>/dev/null \
      || git -C "$INSTALL_DIR" pull --ff-only origin master 2>/dev/null \
      || true
  fi
elif [[ -d "$INSTALL_DIR/core" ]]; then
  echo "ERROR: $INSTALL_DIR exists but is not a git repo — move aside or use --install-dir" >&2
  exit 1
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
  if [[ -n "$TAG" ]]; then
    git -C "$INSTALL_DIR" checkout "$TAG"
  fi
fi

[[ -f "$SOLAR_CLI" ]] || { echo "ERROR: solar CLI missing after install: $SOLAR_CLI" >&2; exit 1; }

mkdir -p "$WRAPPER_DIR"
cat > "$SOLAR_BIN" <<EOF
#!/usr/bin/env bash
export SOLAR_ROOT="$INSTALL_DIR"
exec "$SOLAR_CLI" "\$@"
EOF
chmod +x "$SOLAR_BIN"

read -r ver commit < <(bash -c "source \"$INSTALL_DIR/core/skills/solar-interface/scripts/client_lib.sh\" && solar_client_git_identity \"$INSTALL_DIR\"")

echo "OK: Solar Client installed"
echo "  SOLAR_ROOT=$INSTALL_DIR"
echo "  version=$ver commit=${commit:0:12}"
echo "  wrapper=$SOLAR_BIN"
echo ""
echo "Add to shell profile if needed:"
echo "  export PATH=\"$WRAPPER_DIR:\$PATH\""
echo "  export SOLAR_ROOT=\"$INSTALL_DIR\""
echo ""
echo "Quick start:"
echo "  mkdir -p ~/Solar && cd ~/Solar"
echo "  solar client init"
echo "  solar client sync"
