#!/usr/bin/env bash
# solar_setup.sh — onboarding facade (preflight → init → sync → doctor).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  solar setup [--workspace <path>]

Onboarding facade (does not edit shell profiles):
  1. Preflight: git, bash, python3, curl
  2. solar client init (in workspace)
  3. solar client sync
  4. solar client doctor --strict
  5. solar workspace doctor
  6. Summary of optional capabilities

Options:
  --workspace <path>  Workspace directory (default: cwd)
  -h, --help          Show help
EOF
}

WORKSPACE="$(pwd -P)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: --workspace requires a path" >&2; exit 2; }
      WORKSPACE="$(cd "$1" && pwd -P)"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

echo "Solar setup"
echo "  workspace=$WORKSPACE"
echo ""

missing=()
for cmd in git bash python3 curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing+=("$cmd")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: missing required tools: ${missing[*]}" >&2
  exit 1
fi
echo "OK: base tools present (git, bash, python3, curl)"

wrapper_dir="${SOLAR_BIN_DIR:-$HOME/.local/bin}"
case ":$PATH:" in
  *":$wrapper_dir:"*) echo "OK: $wrapper_dir is on PATH" ;;
  *)
    echo "NOTE: $wrapper_dir is not on PATH."
    echo "Add to ~/.zshrc or ~/.bashrc (setup will not edit it for you):"
    echo "  export PATH=\"$wrapper_dir:\$PATH\""
    echo "Then open a new shell and re-run solar setup if needed."
    ;;
esac
echo ""

cd "$WORKSPACE"
bash "$SCRIPT_DIR/client_init.sh"
bash "$SCRIPT_DIR/client_sync.sh"
bash "$SCRIPT_DIR/client_doctor.sh" --strict
ws_scripts="$(cd "$SCRIPT_DIR/../../solar-workspace/scripts" && pwd)"
bash "$ws_scripts/workspace_doctor.sh"

echo ""
echo "Optional capabilities (not required for base Solar):"
echo "  - AI provider CLI authenticated (claude / codex / agy)"
echo "  - uv, Ollama, Telegram, gateway, voice, LaunchAgent"
echo "  - Solar App: solar app start"
echo ""
echo "OK: setup finished"
echo "Next: complete sun/preferences/profile.md and create a planet when needed."
