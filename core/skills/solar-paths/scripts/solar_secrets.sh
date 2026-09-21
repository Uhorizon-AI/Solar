#!/usr/bin/env bash
# solar_secrets.sh — installation secrets, loaded by the process.
#
# The bash side of `solar_secrets.py`. Same single home, same rule:
#
#   <app data>/Solar/secrets/installation.env   (0600, inside a 0700 directory)
#
# Only Solar's own runtime loads this: the LaunchAgent, the transport gateway,
# the async-task notifier and the MCP server. A skill that an IDE can reach does
# not load it — that is the whole point of moving the keys out of the workspace.
#
# Usage: source this file, then call `solar_load_installation_secrets`.

_solar_secrets_scripts_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

solar_secrets_file() {
  if [[ -n "${SOLAR_SECRETS_FILE:-}" ]]; then
    printf '%s\n' "$SOLAR_SECRETS_FILE"
    return 0
  fi
  # shellcheck source=./solar_runtime_paths.sh
  source "$(_solar_secrets_scripts_dir)/solar_runtime_paths.sh"
  printf '%s/secrets/installation.env\n' "$(solar_global_dir)"
}

# Create the empty hole with the right permissions. Never overwrites a value.
solar_secrets_ensure() {
  python3 "$(_solar_secrets_scripts_dir)/solar_secrets.py" ensure
}

# The only names this store may put in the environment. Mirrors
# solar_secrets.KNOWN_SECRETS; anything else in the file is ignored.
SOLAR_KNOWN_SECRETS="TELEGRAM_BOT_TOKEN SOLAR_N8N_WEBHOOK_SECRET"

# Export the stored secrets into the current shell. The store wins over anything
# a workspace `.env` may still carry: it is the authority for these names.
# Returns 0 even when the store is absent — a machine without transports set up
# is a valid machine, and the callers already fail closed on a missing key.
#
# It parses; it does not `source`. Sourcing would hand the file's contents to
# the shell, so a value containing `$(...)` or backticks would run as a command
# in the one process that holds Solar's credentials. This reads KEY=VALUE the
# way `solar_secrets.parse_env_file` does — no interpolation, no substitution —
# and exports only the allowlisted names.
solar_load_installation_secrets() {
  local file line key value
  file="$(solar_secrets_file)"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Trim surrounding whitespace.
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    # Plain `if`, not `cond && action`: this file is sourced into callers that
    # run with `set -e`, where a false `&&` list would abort them.
    if [[ -z "$line" || "$line" == \#* ]]; then
      continue
    fi
    if [[ "$line" == export\ * ]]; then
      line="${line#export }"
    fi
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    # Strip one matching pair of surrounding quotes, like the python parser.
    if [[ ${#value} -ge 2 ]]; then
      case "$value" in
        \"*\") value="${value:1:${#value}-2}" ;;
        \'*\') value="${value:1:${#value}-2}" ;;
      esac
    fi
    case " $SOLAR_KNOWN_SECRETS " in
      *" $key "*) ;;
      *) continue ;;
    esac
    # Assignment, not evaluation: the value is never re-parsed by the shell.
    export "$key=$value"
  done <"$file"
  return 0
}
