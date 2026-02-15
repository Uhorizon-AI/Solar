#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# From core/skills/solar-router/scripts/ -> 4 levels up to repo root
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
ROOT_ENV_FILE="$REPO_ROOT/.env"
ROUTER_SCRIPT="$REPO_ROOT/core/skills/solar-router/scripts/run_router.py"
PROMPT_DEFAULT="Respond with OK"

dry_run="false"
prompt="$PROMPT_DEFAULT"

usage() {
  cat <<'EOF'
Usage:
  bash core/skills/solar-router/scripts/check_providers.sh [--dry-run] [--prompt "text"]

Options:
  --dry-run        Validate configured provider list and client binaries only (no API calls).
  --prompt TEXT    Prompt used for provider test calls.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run="true"
      shift
      ;;
    --prompt)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Missing value for --prompt"
        exit 1
      fi
      prompt="$1"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f "$REPO_ROOT/AGENTS.md" ]]; then
  echo "ERROR: Repo root not found (missing $REPO_ROOT/AGENTS.md). Run this script from the Solar repo root or set REPO_ROOT." >&2
  exit 1
fi

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-codex,claude,gemini}}"

unique_providers="$(echo "$priority" | awk -F',' '
  {
    for (i = 1; i <= NF; i++) {
      p = $i
      gsub(/^[ \t]+|[ \t]+$/, "", p)
      p = tolower(p)
      if (p == "") continue
      if (!(p in seen)) {
        seen[p] = 1
        if (out == "") out = p
        else out = out "," p
      }
    }
  }
  END { print out }
')"

if [[ -z "$unique_providers" ]]; then
  echo "ERROR: SOLAR_ROUTER_PROVIDER_PRIORITY is empty."
  exit 1
fi

if [[ ! -f "$ROUTER_SCRIPT" ]]; then
  echo "ERROR: router script not found: $ROUTER_SCRIPT"
  exit 1
fi

echo "AI provider preflight:"
echo "  priority: $unique_providers"
echo "  dry_run:  $dry_run"
echo ""

failures=0
IFS=',' read -r -a providers <<< "$unique_providers"
for provider in "${providers[@]}"; do
  provider="$(echo "$provider" | xargs)"
  [[ -z "$provider" ]] && continue

  if [[ "$dry_run" == "true" ]]; then
    if python3 - <<PY "$provider" "$REPO_ROOT"
import os
import shlex
import shutil
import sys

provider = sys.argv[1]
repo_root = sys.argv[2]
codex_default = (
    f"codex exec --skip-git-repo-check --full-auto -C {repo_root} "
    f"--add-dir {os.path.expanduser('~/.codex')} --"
)
defaults = {
    "codex": codex_default,
    "claude": "claude -p --permission-mode bypassPermissions",
    "gemini": "gemini -y",
}
if provider not in defaults:
    print(f"unsupported provider in priority: {provider}")
    raise SystemExit(1)
new_key = f"SOLAR_ROUTER_{provider.upper()}_CMD"
old_key = f"SOLAR_AI_{provider.upper()}_CMD"
raw = (os.getenv(new_key) or os.getenv(old_key) or defaults[provider]).strip()
cmd = shlex.split(raw)
if not cmd:
    print(f"{new_key} is empty")
    raise SystemExit(1)
if shutil.which(cmd[0]) is None:
    print(f"client binary not found: {cmd[0]} (provider={provider})")
    raise SystemExit(1)
print(f"cmd={raw}")
PY
    then
      echo "  - $provider: OK"
    else
      echo "  - $provider: FAIL"
      failures=$((failures + 1))
    fi
    continue
  fi

  payload="$(printf '{"provider":"%s","text":"%s","request_id":"preflight_%s","session_id":"preflight","user_id":"preflight"}' \
    "$provider" "$prompt" "$provider")"

  if result="$(printf '%s' "$payload" | python3 "$ROUTER_SCRIPT" 2>&1)"; then
    preview="$(echo "$result" | head -n1 | cut -c1-80)"
    echo "  - $provider: OK (${preview})"
  else
    echo "  - $provider: FAIL"
    echo "    $(echo "$result" | tr '\n' ' ' | cut -c1-220)"
    failures=$((failures + 1))
  fi
done

echo ""
if [[ "$failures" -gt 0 ]]; then
  echo "Preflight result: FAIL ($failures provider(s) failed)"
  exit 1
fi

echo "Preflight result: OK"
