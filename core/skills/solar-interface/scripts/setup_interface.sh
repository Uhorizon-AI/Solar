#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/interface_lib.sh"

ensure_interface_dirs

MIGRATION_SOURCE="$SCRIPT_DIR/../references/001_initial.sql"
cp "$MIGRATION_SOURCE" "$SOLAR_INTERFACE_MIGRATIONS_DIR/001_initial.sql"

python3 "$SCRIPT_DIR/interface_server.py" --setup-only

echo "Solar Interface runtime ready at: $SOLAR_INTERFACE_RUNTIME_DIR_ABS"

# Install `solar` symlink into the first writable directory on PATH
install_solar_symlink() {
  local target="$SCRIPT_DIR/solar"
  local installed=""
  local dir
  while IFS= read -r dir; do
    [[ -z "$dir" ]] && continue
    if [[ -d "$dir" && -w "$dir" ]]; then
      ln -sf "$target" "$dir/solar"
      installed="$dir/solar"
      break
    fi
  done < <(echo "$PATH" | tr ':' '\n')

  if [[ -n "$installed" ]]; then
    echo "solar symlink installed → $installed"
  else
    echo "Warning: could not find a writable directory in PATH to install 'solar' symlink." >&2
    echo "  Run manually: ln -sf $target ~/.local/bin/solar" >&2
  fi
}

install_solar_symlink
