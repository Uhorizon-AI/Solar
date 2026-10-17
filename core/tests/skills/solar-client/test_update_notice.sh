#!/usr/bin/env bash
# test_update_notice.sh — update-available banner helpers
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
# shellcheck source=../../../../core/skills/solar-client/scripts/update_notice.sh
source "$ROOT/core/skills/solar-client/scripts/update_notice.sh"

PASS=0
FAIL=0
assert_ok() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}
assert_fail() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "FAIL: $name (expected failure)"
    FAIL=$((FAIL + 1))
  else
    echo "PASS: $name"
    PASS=$((PASS + 1))
  fi
}
assert_contains() {
  local name="$1" hay="$2" needle="$3"
  if [[ "$hay" == *"$needle"* ]]; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name (missing '$needle')"
    FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export SOLAR_UPDATE_CACHE="$TMP/update-check.json"
export SOLAR_NO_UPDATE_CHECK=""

assert_ok "0.19.3 < 0.20.0" solar_update_is_newer "0.19.3" "v0.20.0"
assert_ok "v0.19.3 < 0.20.0" solar_update_is_newer "v0.19.3" "0.20.0"
assert_fail "equal not newer" solar_update_is_newer "0.20.0" "v0.20.0"
assert_fail "current ahead" solar_update_is_newer "0.21.0" "v0.20.0"
assert_fail "dev current skipped" solar_update_is_newer "dev" "v0.20.0"

export SOLAR_UPDATE_LATEST_FOR_TEST="v9.9.9"
out="$(solar_update_notice_print "0.1.0" 2>&1 >/dev/null)" || true
assert_contains "banner shows versions" "$out" "0.1.0 → 9.9.9"
assert_contains "banner shows update cmd" "$out" "solar update"
assert_contains "banner shows release notes" "$out" "github.com/Uhorizon-AI/Solar/releases/latest"

out2="$(SOLAR_NO_UPDATE_CHECK=1 solar_update_notice_print "0.1.0" 2>&1 >/dev/null)" || true
if [[ -z "$out2" ]]; then
  echo "PASS: SOLAR_NO_UPDATE_CHECK suppresses banner"
  PASS=$((PASS + 1))
else
  echo "FAIL: SOLAR_NO_UPDATE_CHECK should suppress banner"
  FAIL=$((FAIL + 1))
fi

unset SOLAR_UPDATE_LATEST_FOR_TEST
export SOLAR_UPDATE_LATEST_FOR_TEST="v0.1.0"
out3="$(solar_update_notice_print "0.2.0" 2>&1 >/dev/null)" || true
if [[ -z "$out3" ]]; then
  echo "PASS: no banner when already newer"
  PASS=$((PASS + 1))
else
  echo "FAIL: should not banner when current newer"
  FAIL=$((FAIL + 1))
fi

# Cache write/read path (no network): force via SOLAR_STABLE_RELEASE_TAG + empty test override
unset SOLAR_UPDATE_LATEST_FOR_TEST
export SOLAR_STABLE_RELEASE_TAG="v8.8.8"
got="$(solar_update_resolve_latest)"
assert_ok "resolve uses SOLAR_STABLE_RELEASE_TAG" test "$got" = "v8.8.8"
unset SOLAR_STABLE_RELEASE_TAG

# Fresh cache must be reused without network (Codex review).
solar_update_write_cache "$SOLAR_UPDATE_CACHE" "v7.7.7" 86400
c_values="$(solar_update_read_cache "$SOLAR_UPDATE_CACHE")"
read -r c_latest c_checked c_ttl <<< "$c_values"
assert_ok "cache read parses latest" test "$c_latest" = "v7.7.7"
assert_ok "cache read parses checked_at" test -n "$c_checked"
assert_ok "cache read parses ttl" test "$c_ttl" = "86400"
# Poison PATH/curl and point API at a guaranteed-fail URL so network cannot succeed.
export PATH="$TMP/bin:$PATH"
mkdir -p "$TMP/bin"
cat >"$TMP/bin/curl" <<'EOF'
#!/bin/sh
echo "curl should not be called for fresh cache" >&2
exit 99
EOF
chmod +x "$TMP/bin/curl"
export SOLAR_RELEASES_API_URL="http://127.0.0.1:1/should-not-hit"
got_cache="$(solar_update_resolve_latest)"
assert_ok "fresh cache reused without network" test "$got_cache" = "v7.7.7"

# An absent or malformed cache must stay a cache miss when refresh fails.
rm -f "$SOLAR_UPDATE_CACHE"
assert_fail "missing cache and failed refresh stay unknown" solar_update_resolve_latest
printf '%s\n' '{invalid json' >"$SOLAR_UPDATE_CACHE"
assert_fail "malformed cache and failed refresh stay unknown" solar_update_resolve_latest
printf '%s\n' '{"latest":"v6.6.6","checked_at":1,"ttl":86400}' >"$SOLAR_UPDATE_CACHE"
got_stale="$(solar_update_resolve_latest)"
assert_ok "failed refresh preserves stale-cache fallback" test "$got_stale" = v6.6.6

# The reader emits a valid line before exiting. Publishing the resolved tag
# must wait for its completion, rather than just consuming the first line.
got_completed="$(
  solar_update_read_cache() {
    builtin printf '%s %s %s\n' v7.7.7 "$(date +%s)" 86400
    sleep 0.2
    : >"$TMP/cache-reader-finished"
  }
  printf() {
    if [[ "${2:-}" == v7.7.7 && ! -f "$TMP/cache-reader-finished" ]]; then
      return 1
    fi
    builtin printf "$@"
  }
  solar_update_resolve_latest
)"
assert_ok "resolved tag waits for cache reader completion" test "$got_completed" = v7.7.7

SOLAR="$ROOT/core/skills/solar-client/scripts/solar"
export SOLAR_UPDATE_LATEST_FOR_TEST="v9.9.9"
help_out="$(bash "$SOLAR" 2>&1)" || true
assert_contains "bare solar shows banner" "$help_out" "Update available!"
assert_contains "bare solar still shows usage" "$help_out" "Usage:"

echo ""
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
