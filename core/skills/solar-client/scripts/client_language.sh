#!/usr/bin/env bash
# Set or print the console language in .solar/settings.json.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

usage_language() {
  cat <<'EOF'
Usage:
  solar client language
  solar client language set en|es

Prints or sets "language" in .solar/settings.json. English is the default
when the key is missing. This is the supported way to select Spanish for
the console. Do not edit .solar/settings.json by hand.

Aliases accepted by set: english, es-ES, es_ES, spanish.
The stored value is en or es. solar client update keeps the key.
EOF
}

if [[ -n "${SOLAR_WORKSPACE:-}" ]]; then
  solar_resolve_paths --workspace "$SOLAR_WORKSPACE" --quiet
else
  solar_resolve_paths --quiet
fi

case "${1:-}" in
  ""|get)
    solar_client_read_language "$SOLAR_WORKSPACE"
    ;;
  set)
    shift
    requested="${1:-}"
    if [[ -z "$requested" || "$requested" == -* ]]; then
      echo "ERROR: language set requires en or es" >&2
      usage_language >&2
      exit 2
    fi
    language="$(solar_client_write_language "$SOLAR_WORKSPACE" "$requested")"
    echo "OK: console language set to $language"
    ;;
  -h|--help)
    usage_language
    ;;
  *)
    echo "ERROR: unknown language command: $1" >&2
    usage_language >&2
    exit 2
    ;;
esac
