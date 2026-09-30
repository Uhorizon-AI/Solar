#!/usr/bin/env bash
# solar client language reads and writes .solar/settings.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
# shellcheck source=../../../../core/skills/solar-client/scripts/client_lib.sh
source "$ROOT/core/skills/solar-client/scripts/client_lib.sh"

PASS=0
FAIL=0
assert_eq() {
  local name="$1" got="$2" want="$3"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name (got='$got' want='$want')"
    FAIL=$((FAIL + 1))
  fi
}
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
    echo "FAIL: $name (expected non-zero)"
    FAIL=$((FAIL + 1))
  else
    echo "PASS: $name"
    PASS=$((PASS + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
WS="$TMP/ws"
mkdir -p "$WS/.solar"
printf '%s\n' '{"scope":"workspace","layout":"solar-client-v1.2","custom_user":"keep"}' \
  >"$WS/.solar/settings.json"

assert_eq "missing key is english" "$(solar_client_read_language "$WS")" "en"

got="$(solar_client_write_language "$WS" "es-ES")"
assert_eq "alias es-ES stores es" "$got" "es"
stored="$(python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/settings.json"))["language"])')"
assert_eq "settings language is es" "$stored" "es"
kept="$(python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/settings.json"))["custom_user"])')"
assert_eq "other settings stay" "$kept" "keep"

before="$(cat "$WS/.solar/settings.json")"
assert_fail "rejects an unknown language" solar_client_write_language "$WS" "fr"
after="$(cat "$WS/.solar/settings.json")"
assert_eq "rejected set does not write" "$after" "$before"

export SOLAR_WORKSPACE="$WS"
export SOLAR_ROOT="$ROOT"
lang_script="$ROOT/core/skills/solar-client/scripts/client_language.sh"
assert_eq "cli prints es" "$(bash "$lang_script")" "es"
bash "$lang_script" set en >/dev/null
assert_eq "cli set en" "$(bash "$lang_script")" "en"
bash "$lang_script" set spanish >/dev/null
assert_eq "cli alias spanish" "$(bash "$lang_script")" "es"

solar_client_write_settings_v12 "$WS" "$ROOT"
assert_eq "update keeps language" "$(solar_client_read_language "$WS")" "es"

echo
echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
