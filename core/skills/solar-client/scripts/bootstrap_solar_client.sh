#!/usr/bin/env bash
# bootstrap_solar_client.sh — curl-friendly installer entrypoint.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# When bootstrapping from a remote shallow clone, client_lib may not exist yet
# in the temp tree until after clone. Prefer sourcing from local override path.
_source_lib() {
  if [[ -f "$SCRIPT_DIR/client_lib.sh" ]]; then
    # shellcheck source=client_lib.sh
    source "$SCRIPT_DIR/client_lib.sh"
  fi
}
_source_lib

REF="${SOLAR_CLIENT_TAG:-${SOLAR_CLIENT_REF:-}}"
INSTALL_DIR="${SOLAR_INSTALL_DIR:-$HOME/Solar/solar}"
if declare -F solar_client_canonical_repo_url >/dev/null 2>&1; then
  REPO_URL="$(solar_client_canonical_repo_url)"
else
  REPO_URL="${SOLAR_REPO_URL:-https://github.com/Uhorizon-AI/Solar.git}"
fi

usage() {
  cat <<'EOF'
Usage:
  bash bootstrap_solar_client.sh [--install-dir <path>] [--ref <ref>] [--tag <ref>] [--yes]

Downloads the installer from the canonical Solar repo and runs it.
--ref accepts a tag, branch, or commit SHA ( --tag is an alias ).
Default ref = latest GitHub Release (API + curl), not main.
EOF
}

require_value() {
  local opt="$1"
  if [[ $# -lt 2 || -z "${2:-}" || "$2" == -* ]]; then
    echo "ERROR: $opt requires a value" >&2
    exit 2
  fi
}

YES=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir)
      require_value "$1" "${2:-}"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --ref|--tag)
      require_value "$1" "${2:-}"
      REF="$2"
      shift 2
      ;;
    --yes|-y) YES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for cmd in git bash curl python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: missing required tool: $cmd" >&2; exit 1; }
done

if [[ -z "$REF" ]]; then
  if declare -F solar_client_resolve_stable_release_tag >/dev/null 2>&1; then
    REF="$(solar_client_resolve_stable_release_tag)" || exit 1
  else
    # Shallow bootstrap without local lib: fetch API directly
    api="${SOLAR_RELEASES_API_URL:-https://api.github.com/repos/Uhorizon-AI/Solar/releases/latest}"
    body="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api")" || {
      echo "ERROR: failed to resolve stable release from $api" >&2
      exit 1
    }
    REF="$(printf '%s' "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if d.get("prerelease") or d.get("draft"):
    sys.exit("ERROR: latest release is not stable")
t=(d.get("tag_name") or "").strip()
assert t, "missing tag_name"
print(t)
')" || exit 1
  fi
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ -n "${SOLAR_BOOTSTRAP_FROM_LOCAL:-}" && -f "$SOLAR_BOOTSTRAP_FROM_LOCAL" ]]; then
  bash "$SOLAR_BOOTSTRAP_FROM_LOCAL" --install-dir "$INSTALL_DIR" --ref "$REF" --yes
  exit $?
fi

# Clone installer sources at $REF (tag, branch, or commit).
# Fast path: shallow clone when Git can treat REF as a remote branch/tag tip.
# Fallback: full clone + checkout (required for arbitrary commit SHAs).
clone_bootstrap_tree() {
  local dest="$1"
  if git -c core.hooksPath=/dev/null clone --depth 1 --branch "$REF" "$REPO_URL" "$dest" \
      >"$TMP/clone.out" 2>"$TMP/clone.err"; then
    return 0
  fi
  rm -rf "$dest"
  echo "INFO: shallow --branch $REF failed; cloning and checking out commit/ref" >&2
  if ! git -c core.hooksPath=/dev/null clone "$REPO_URL" "$dest" >"$TMP/clone.out" 2>"$TMP/clone.err"; then
    echo "ERROR: failed to clone $REPO_URL" >&2
    cat "$TMP/clone.err" >&2 || true
    return 1
  fi
  if ! git -C "$dest" checkout --detach "$REF" >"$TMP/checkout.out" 2>"$TMP/checkout.err"; then
    echo "ERROR: failed to checkout ref $REF in cloned repo" >&2
    cat "$TMP/checkout.err" >&2 || true
    return 1
  fi
  return 0
}

if ! clone_bootstrap_tree "$TMP/solar"; then
  exit 1
fi

INSTALLER="$TMP/solar/core/skills/solar-client/scripts/install_solar_client.sh"
[[ -f "$INSTALLER" ]] || { echo "ERROR: installer not found in repo checkout" >&2; exit 1; }

bash "$INSTALLER" --install-dir "$INSTALL_DIR" --ref "$REF" --yes
