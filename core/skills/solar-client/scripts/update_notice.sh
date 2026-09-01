#!/usr/bin/env bash
# update_notice.sh — lightweight "update available" banner (Codex-style).
# Safe to source without workspace / Solar App. Network failures are silent.
# shellcheck shell=bash

solar_update_cache_path() {
  printf '%s\n' "${SOLAR_UPDATE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/solar/update-check.json}"
}

solar_update_releases_url() {
  printf '%s\n' "${SOLAR_RELEASES_API_URL:-https://api.github.com/repos/Uhorizon-AI/Solar/releases/latest}"
}

solar_update_notes_url() {
  printf '%s\n' "${SOLAR_RELEASE_NOTES_URL:-https://github.com/Uhorizon-AI/Solar/releases/latest}"
}

# Normalize tag/version to dotted semver without leading v (best-effort).
solar_update_normalize_version() {
  local raw="${1:-}"
  raw="${raw#v}"
  raw="${raw%%-*}" # drop -githash / -rc suffixes for compare baseline
  printf '%s\n' "$raw"
}

# Exit 0 if remote is strictly newer than current. Else 1.
solar_update_is_newer() {
  local current="$1"
  local remote="$2"
  python3 - "$current" "$remote" <<'PY'
import sys

def parts(v: str):
    v = (v or "").strip().lstrip("v")
    if not v or v.startswith("dev"):
        return None
    core = v.split("-", 1)[0]
    out = []
    for bit in core.split("."):
        if not bit.isdigit():
            return None
        out.append(int(bit))
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])

cur = parts(sys.argv[1])
rem = parts(sys.argv[2])
if cur is None or rem is None:
    sys.exit(1)
sys.exit(0 if rem > cur else 1)
PY
}

solar_update_read_cache() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  # One line: latest checked_at ttl — so callers can `read -r latest checked ttl`.
  python3 - "$path" <<'PY'
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
latest = (data.get("latest") or "").strip()
checked = int(data.get("checked_at") or 0)
ttl = int(data.get("ttl") or 0)
if not latest or checked <= 0:
    sys.exit(1)
print(f"{latest} {checked} {ttl}")
PY
}

solar_update_write_cache() {
  local path="$1"
  local latest="$2"
  local ttl="$3"
  mkdir -p "$(dirname "$path")"
  python3 - "$path" "$latest" "$ttl" <<'PY'
import json, sys, time
path, latest, ttl = sys.argv[1], sys.argv[2], int(sys.argv[3])
payload = {
    "checked_at": int(time.time()),
    "latest": latest,
    "ttl": ttl,
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY
}

# Resolve latest stable tag. Prefer test override, then fresh/stale cache, then network.
# Prints tag on stdout; exit 1 if unknown.
solar_update_resolve_latest() {
  if [[ -n "${SOLAR_UPDATE_LATEST_FOR_TEST:-}" ]]; then
    printf '%s\n' "$SOLAR_UPDATE_LATEST_FOR_TEST"
    return 0
  fi
  if [[ -n "${SOLAR_STABLE_RELEASE_TAG:-}" ]]; then
    printf '%s\n' "$SOLAR_STABLE_RELEASE_TAG"
    return 0
  fi

  local cache ttl now checked latest stale=1
  cache="$(solar_update_cache_path)"
  ttl="${SOLAR_UPDATE_CHECK_TTL:-86400}"
  now="$(date +%s)"

  if read -r latest checked _ttl < <(solar_update_read_cache "$cache" 2>/dev/null); then
    if [[ -n "$checked" && "$checked" =~ ^[0-9]+$ && $((now - checked)) -lt $ttl ]]; then
      stale=0
    fi
    if [[ "$stale" -eq 0 ]]; then
      printf '%s\n' "$latest"
      return 0
    fi
  else
    latest=""
  fi

  # Network refresh (short timeout). On failure, fall back to stale cache if any.
  if command -v curl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    local api body tag
    api="$(solar_update_releases_url)"
    if body="$(curl -fsSL --max-time "${SOLAR_UPDATE_CHECK_TIMEOUT:-2}" \
      -H 'Accept: application/vnd.github+json' \
      -H 'User-Agent: solar-cli-update-check' \
      "$api" 2>/dev/null)"; then
      tag="$(printf '%s' "$body" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if data.get("draft") or data.get("prerelease"):
    sys.exit(1)
tag = (data.get("tag_name") or "").strip()
if not tag:
    sys.exit(1)
print(tag)
' 2>/dev/null)" || tag=""
      if [[ -n "$tag" ]]; then
        solar_update_write_cache "$cache" "$tag" "$ttl" 2>/dev/null || true
        printf '%s\n' "$tag"
        return 0
      fi
    fi
  fi

  if [[ -n "$latest" ]]; then
    printf '%s\n' "$latest"
    return 0
  fi
  return 1
}

solar_update_print_banner() {
  local current_disp="$1"
  local remote_disp="$2"
  local notes
  notes="$(solar_update_notes_url)"
  python3 - "$current_disp" "$remote_disp" "$notes" <<'PY' >&2
import sys
cur, rem, notes = sys.argv[1:4]
lines = [
    f"Update available! {cur} → {rem}",
    "Run: solar update",
    "",
    "Release notes:",
    notes,
]
width = max(45, max(len(x) for x in lines))
bar = "─" * (width + 2)
print(f"╭{bar}╮")
for line in lines:
    print(f"│ {line:<{width}} │")
print(f"╰{bar}╯")
print()
PY
}

# Print update banner to stderr when a newer stable release exists. Never fails the caller.
solar_update_notice_print() {
  local current="${1:-}"
  [[ "${SOLAR_NO_UPDATE_CHECK:-}" == "1" ]] && return 0
  [[ -z "$current" ]] && return 0

  local latest
  latest="$(solar_update_resolve_latest 2>/dev/null)" || return 0
  [[ -z "$latest" ]] && return 0

  if solar_update_is_newer "$current" "$latest"; then
    local cur_n rem_n
    cur_n="$(solar_update_normalize_version "$current")"
    rem_n="$(solar_update_normalize_version "$latest")"
    solar_update_print_banner "$cur_n" "$rem_n"
  fi
  return 0
}
