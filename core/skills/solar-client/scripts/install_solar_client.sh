#!/usr/bin/env bash
# install_solar_client.sh — global Solar Client install.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  bash install_solar_client.sh [--install-dir <path>] [--ref <ref>] [--tag <ref>] [--yes]

Installs Solar framework to ~/Solar/solar (or --install-dir) and adds a solar wrapper
under ~/.local/bin (or SOLAR_BIN_DIR).

Options:
  --install-dir <path>  Install root (default: ~/Solar/solar)
  --ref <ref>           Git tag/branch/commit to checkout (default: latest GitHub Release)
  --tag <ref>           Alias for --ref
  --yes, -y             Non-interactive
  --help                Show help

Stable default resolves via GitHub Releases API (curl), not main.
Smoke test uses the absolute wrapper path; missing PATH is an instruction, not a failure.

After install (if needed):
  export PATH="$HOME/.local/bin:$PATH"
  mkdir -p ~/Solar && cd ~/Solar
  solar client init && solar client sync && solar client doctor --strict
EOF
}

require_value() {
  local opt="$1"
  if [[ $# -lt 2 || -z "${2:-}" || "$2" == -* ]]; then
    echo "ERROR: $opt requires a value" >&2
    exit 2
  fi
}

preflight_deps() {
  local missing=()
  local cmd
  for cmd in git bash python3 curl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: missing required tools: ${missing[*]}" >&2
    exit 1
  fi
}

has_only_managed_cli_mode_repair() {
  local root="$1"
  local cli_rel="core/skills/solar-client/scripts/solar"
  local changed
  git -C "$root" diff --cached --quiet 2>/dev/null || return 1
  changed="$(git -C "$root" diff --name-only 2>/dev/null)" || return 1
  [[ "$changed" == "$cli_rel" ]] || return 1
  git -C "$root" show "HEAD:$cli_rel" 2>/dev/null | cmp -s - "$root/$cli_rel"
}

INSTALL_DIR="${SOLAR_ROOT:-$HOME/Solar/solar}"
REF=""
YES=false
REPO_URL="$(solar_client_canonical_repo_url)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir)
      require_value "$1" "${2:-}"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --ref|--tag)
      opt="$1"
      require_value "$opt" "${2:-}"
      REF="$2"
      shift 2
      ;;
    --yes|-y) YES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

preflight_deps

# Resolve install dir parent even if path does not exist yet
_parent="$(dirname "$INSTALL_DIR")"
mkdir -p "$_parent"
INSTALL_DIR="$(cd "$_parent" && pwd)/$(basename "$INSTALL_DIR")"
WRAPPER_DIR="${SOLAR_BIN_DIR:-$HOME/.local/bin}"
SOLAR_BIN="$WRAPPER_DIR/solar"
SOLAR_CLI="$INSTALL_DIR/core/skills/solar-client/scripts/solar"

if [[ -z "$REF" ]]; then
  REF="$(solar_client_resolve_stable_release_tag)" \
    || { echo "ERROR: could not resolve stable release tag (pass --ref explicitly)" >&2; exit 1; }
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "INFO: existing install at $INSTALL_DIR — updating to $REF"
  if ! solar_client_git_dirty "$INSTALL_DIR"; then
    if has_only_managed_cli_mode_repair "$INSTALL_DIR"; then
      echo "INFO: existing mode-only CLI repair is safe to refresh"
    else
      echo "ERROR: existing install has local modifications: $INSTALL_DIR" >&2
      echo "Commit, stash, or discard them explicitly before reinstalling." >&2
      exit 1
    fi
  fi
  git -C "$INSTALL_DIR" fetch --tags origin
  if ! git -C "$INSTALL_DIR" rev-parse "$REF^{commit}" >/dev/null 2>&1; then
    echo "ERROR: ref not found after fetch: $REF" >&2
    exit 1
  fi
  git -C "$INSTALL_DIR" checkout "$REF"
elif [[ -d "$INSTALL_DIR/core" ]]; then
  echo "ERROR: $INSTALL_DIR exists but is not a git repo — move aside or use --install-dir" >&2
  exit 1
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git -c core.hooksPath=/dev/null clone "$REPO_URL" "$INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --tags origin 2>/dev/null || true
  if ! git -C "$INSTALL_DIR" rev-parse "$REF^{commit}" >/dev/null 2>&1; then
    echo "ERROR: ref not found in cloned repo: $REF" >&2
    exit 1
  fi
  git -C "$INSTALL_DIR" checkout "$REF"
fi

[[ -f "$SOLAR_CLI" ]] || { echo "ERROR: solar CLI missing after install: $SOLAR_CLI" >&2; exit 1; }
chmod +x "$SOLAR_CLI"

if [[ ! -d "$WRAPPER_DIR" ]]; then
  mkdir -p "$WRAPPER_DIR" || { echo "ERROR: cannot create wrapper dir: $WRAPPER_DIR" >&2; exit 1; }
fi
if [[ ! -w "$WRAPPER_DIR" ]]; then
  echo "ERROR: wrapper directory not writable: $WRAPPER_DIR" >&2
  exit 1
fi

cat > "$SOLAR_BIN" <<EOF
#!/usr/bin/env bash
export SOLAR_ROOT="$INSTALL_DIR"
exec "$SOLAR_CLI" "\$@"
EOF
chmod +x "$SOLAR_BIN"

if ! "$SOLAR_BIN" --version >/dev/null 2>&1; then
  echo "ERROR: smoke failed: $SOLAR_BIN --version" >&2
  echo "HINT: ensure $SOLAR_CLI is executable (chmod +x)" >&2
  exit 1
fi

read -r ver commit < <(solar_client_git_identity "$INSTALL_DIR")

echo "OK: Solar Client installed"
echo "  SOLAR_ROOT=$INSTALL_DIR"
echo "  version=$ver commit=${commit:0:12}"
echo "  ref=$REF"
echo "  wrapper=$SOLAR_BIN"
echo ""

path_ok=false
case ":$PATH:" in
  *":$WRAPPER_DIR:"*) path_ok=true ;;
esac
if [[ "$path_ok" != true ]]; then
  echo "NOTE: $WRAPPER_DIR is not in PATH for this shell."
  echo "Add to ~/.zshrc or ~/.bashrc, then open a new shell:"
  echo "  export PATH=\"$WRAPPER_DIR:\$PATH\""
  echo ""
fi

echo "Quick start:"
echo "  mkdir -p ~/Solar && cd ~/Solar"
echo "  \"$SOLAR_BIN\" client init"
echo "  \"$SOLAR_BIN\" client sync"
echo "  \"$SOLAR_BIN\" client doctor --strict"
