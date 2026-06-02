#!/usr/bin/env bash
# Shared uv venv for Solar voice Python deps (PEP 668 safe — no system pip).
set -euo pipefail

voice_uv_root() {
  local base="${SOLAR_APP_DATA:-$HOME/Library/Application Support}"
  base="${base%/}"
  printf '%s/Solar/voice-uv' "$base"
}

voice_uv_python() {
  local venv
  venv="$(voice_uv_root)/.venv/bin/python"
  if [[ -x "$venv" ]]; then
    printf '%s' "$venv"
    return 0
  fi
  return 1
}

voice_uv_ensure() {
  local root py
  root="$(voice_uv_root)"
  py="$root/.venv/bin/python"
  if [[ -x "$py" ]]; then
    printf '%s' "$py"
    return 0
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv required — brew install uv" >&2
    return 1
  fi
  mkdir -p "$root"
  uv venv "$root/.venv"
  printf '%s' "$py"
}

voice_uv_pip_install() {
  local py="$1"
  shift
  uv pip install --python "$py" "$@"
}

# Run: voice_uv_import_ok <module> [extra uv --with packages...]
voice_uv_import_ok() {
  local mod="$1"
  shift
  if command -v uv >/dev/null 2>&1; then
    uv run "$@" python3 -c "import ${mod}" 2>/dev/null
    return $?
  fi
  python3 -c "import ${mod}" 2>/dev/null
}
