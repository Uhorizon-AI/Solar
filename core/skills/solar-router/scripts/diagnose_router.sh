#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$SCRIPT_DIR/../../solar-client/scripts/resolve_solar_paths.sh"
solar_resolve_paths --quiet
ROOT_ENV_FILE="$SOLAR_WORKSPACE/.env"
ROUTER_SCRIPT="$(solar_core_dir)/skills/solar-router/scripts/run_router.py"
PROMPT_DEFAULT="Respond with OK"

dry_run="false"
verbose="false"
prompt="$PROMPT_DEFAULT"

usage() {
  cat <<'EOF'
Usage:
  bash core/skills/solar-router/scripts/diagnose_router.sh [--dry-run] [--verbose] [--prompt "text"]

Options:
  --dry-run        Validate configured provider list and client binaries only (no API calls).
  --verbose        On provider failure, print full router error (+ raw capture). Default: short error + cmd.
  --prompt TEXT    Prompt used for provider test calls.
EOF
}

# Parse mixed run_router capture (stderr prompt logs + stdout JSON).
# Prints: error line, optional cmd line with placeholders.
_format_provider_failure() {
  local provider="$1"
  local capture="$2"
  local verbose_flag="$3"
  printf '%s' "$capture" | python3 -c '
import json, os, re, sys

provider = sys.argv[1]
workspace = sys.argv[2].rstrip("/")
verbose = sys.argv[3] == "true"
text = sys.stdin.read()

decoder = json.JSONDecoder()
payload = None
idx = 0
while True:
    start = text.find("{", idx)
    if start < 0:
        break
    try:
        obj, _end = decoder.raw_decode(text, start)
    except json.JSONDecodeError:
        idx = start + 1
        continue
    if isinstance(obj, dict) and "status" in obj:
        payload = obj
    idx = start + 1

err = ""
if isinstance(payload, dict):
    err = str(payload.get("error") or "").strip()
    code = str(payload.get("error_code") or "").strip()
    if code and err:
        err = f"[{code}] {err}"
    elif code and not err:
        err = f"[{code}]"
if not err:
    for line in reversed(text.splitlines()):
        s = line.strip()
        if not s or s.startswith("[") or s.startswith("{") or s.startswith("<"):
            continue
        if s.startswith("You are Solar") or s.startswith("## "):
            continue
        err = s
        break
if not err:
    err = "(no error message parsed)"

cmd = None
m = re.search(
    r"\[solar-router\]\[%s\] CMD: (.+?) <prompt>" % re.escape(provider),
    text,
)
if m:
    cmd = m.group(1).strip()
    if workspace:
        cmd = cmd.replace(workspace, "<SOLAR_WORKSPACE>")
    home = os.path.expanduser("~")
    if home and home in cmd:
        cmd = cmd.replace(home, "~")
    cmd = cmd + " <prompt>"

shown = err if verbose else (err[:300] + ("…" if len(err) > 300 else ""))
print(f"    error: {shown}")
if cmd:
    print(f"    cmd:   {cmd}")
elif verbose:
    print("    cmd:   (not logged; set SOLAR_ROUTER_LOG_PROMPTS=true to capture)")
if verbose:
    print("    (raw capture):")
    for line in text.splitlines():
        print(f"    {line}")
' "$provider" "$SOLAR_WORKSPACE" "$verbose_flag"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run="true"
      shift
      ;;
    --verbose)
      verbose="true"
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

if [[ ! -f "$SOLAR_WORKSPACE/AGENTS.md" ]]; then
  echo "ERROR: Repo root not found (missing $SOLAR_WORKSPACE/AGENTS.md). Run this script from the Solar repo root or set SOLAR_WORKSPACE." >&2
  exit 1
fi

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-codex,claude,agy,agent}}"

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
echo "  verbose:  $verbose"
echo ""

failures=0
IFS=',' read -r -a providers <<< "$unique_providers"
for provider in "${providers[@]}"; do
  provider="$(echo "$provider" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -z "$provider" ]] && continue

  if [[ "$dry_run" == "true" ]]; then
    if python3 - <<PY "$provider" "$SOLAR_WORKSPACE"
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
    "agent": f"agent -p -f --approve-mcps --trust --workspace {repo_root}",
    "codex": codex_default,
    "claude": "claude -p --permission-mode bypassPermissions",
    "agy": "agy -p --dangerously-skip-permissions",
    "ollama": "ollama run solar --hidethinking --nowordwrap",
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
    preview="$(
      printf '%s' "$result" | python3 -c '
import json, sys
text = sys.stdin.read()
dec = json.JSONDecoder()
payload = None
i = 0
while True:
    j = text.find("{", i)
    if j < 0:
        break
    try:
        obj, _ = dec.raw_decode(text, j)
    except json.JSONDecodeError:
        i = j + 1
        continue
    if isinstance(obj, dict) and obj.get("status") == "success":
        payload = obj
    i = j + 1
reply = (payload or {}).get("reply_text") or ""
print((reply[:80] + ("…" if len(reply) > 80 else "")).replace("\n", " "))
'
    )"
    echo "  - $provider: OK (${preview})"
  else
    echo "  - $provider: FAIL"
    _format_provider_failure "$provider" "$result" "$verbose"
    failures=$((failures + 1))
  fi
done

echo ""
if [[ "$failures" -gt 0 ]]; then
  echo "Preflight result: FAIL ($failures provider(s) failed)"
  exit 1
fi

echo "Preflight result: OK"
