#!/usr/bin/env bash
# macOS voice platform imports — skip cleanly off darwin.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-host/scripts"
PASS=0
FAIL=0

assert_ok() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label" >&2
    FAIL=$((FAIL + 1))
  fi
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "SKIP: macOS-only voice imports"
  exit 0
fi

python3 - <<'PY' "$SCRIPTS" || exit 1
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from host_platform.macos.voice_tts import PhraseBuffer, avfoundation_available

buf = PhraseBuffer()
out = buf.feed("Hello. More ")
assert out == ["Hello."], out
tail = buf.flush_remaining()
assert tail == "More", tail

# Import may fail without PyObjC — must not crash module load.
_ = avfoundation_available()
print("OK: voice_tts")
PY
assert_ok "voice_tts PhraseBuffer" test $? -eq 0

python3 - <<'PY' "$SCRIPTS" || exit 1
import sys

sys.path.insert(0, sys.argv[1])
from host_platform.macos import hotkey

assert hasattr(hotkey, "quartz_available")
assert hasattr(hotkey, "GlobalHotkeyListener")
print("OK: hotkey module")
PY
assert_ok "hotkey module import" test $? -eq 0

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
