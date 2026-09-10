#!/usr/bin/env bash
# The async-task helpers must not replace the feature timeout helper used by
# check_orchestrator.sh.
#
# Fully isolated: fake HOME, temporary SOLAR_APP_DATA, a fixture SOLAR_ROOT, and
# a stubbed host probe. This test must never touch a live console — with the
# real :9000 deliberately stopped during the store move, a test that probes it
# is red for a reason that has nothing to do with what it claims to measure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The queue is machine state under the framework runtime root, never inside the
# workspace.
export SOLAR_APP_DATA="$TMP/AppData"
mkdir -p "$TMP/workspace/.solar" "$TMP/home/Library/LaunchAgents" "$TMP/bin" \
  "$SOLAR_APP_DATA/Solar/runtime/async-tasks/queued"

cat >"$TMP/workspace/.solar/settings.json" <<'EOF'
{"layout":"solar-client-v1.2","core_source":"global","requires_global_client":true}
EOF
cat >"$TMP/workspace/.env" <<'EOF'
SOLAR_SYSTEM_FEATURES=async-tasks,host
EOF

# ---------------------------------------------------------------------------
# Fixture SOLAR_ROOT: the real skills under test, a stubbed host probe.
# ---------------------------------------------------------------------------
FIXTURE_ROOT="$TMP/solar-root"
mkdir -p "$FIXTURE_ROOT/core/skills/solar-app/scripts"
# Real code, because that is what the test measures.
ln -s "$ROOT/core/skills/solar-async-tasks" "$FIXTURE_ROOT/core/skills/solar-async-tasks"
ln -s "$ROOT/core/skills/solar-client" "$FIXTURE_ROOT/core/skills/solar-client"
ln -s "$ROOT/core/skills/solar-system" "$FIXTURE_ROOT/core/skills/solar-system"

# Stubbed probe: no sockets, no host_lib, no ports. Leaves a marker so the test
# can prove the real probe was never reached.
PROBE_MARKER="$TMP/host-probe-ran"
cat >"$FIXTURE_ROOT/core/skills/solar-app/scripts/check_host.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
echo ran >"$PROBE_MARKER"
echo "OK: stubbed console probe (no network)"
exit 0
EOF
chmod +x "$FIXTURE_ROOT/core/skills/solar-app/scripts/check_host.sh"

CHECK="$FIXTURE_ROOT/core/skills/solar-system/scripts/check_orchestrator.sh"

for stub in launchctl pgrep curl; do
  printf '#!/usr/bin/env bash\nexit %s\n' "$([[ $stub == pgrep ]] && echo 1 || echo 0)" >"$TMP/bin/$stub"
  chmod +x "$TMP/bin/$stub"
done

set +e
output="$(
  cd "$TMP/workspace"
  HOME="$TMP/home" \
  PATH="$TMP/bin:/usr/bin:/bin" \
  SOLAR_ROOT="$FIXTURE_ROOT" \
  SOLAR_WORKSPACE="$TMP/workspace" \
  SOLAR_APP_BASE_URL="stub://console.invalid" \
  bash "$CHECK" 2>&1
)"
set -e

fail() { printf 'FAIL: %s\n%s\n' "$1" "$output" >&2; exit 1; }

if grep -q "invalid duration" <<<"$output"; then
  fail "async task helpers replaced the feature timeout helper"
fi

if ! grep -A2 "Feature: host" <<<"$output" | grep -q "status: HEALTHY"; then
  fail "host health check did not run after async task inspection"
fi

# Isolation, asserted rather than assumed.
[[ -f "$PROBE_MARKER" ]] || fail "the stubbed probe never ran: the real one was used"

if grep -qE "127\.0\.0\.1:(9000|9434)|:9000|:9434" <<<"$output"; then
  fail "the run referenced a live local console port"
fi

if ! grep -q "queue_dir:   present" <<<"$output"; then
  fail "the queue did not resolve to the temporary runtime root"
fi

if grep -q "$TMP/workspace/sun" <<<"$output"; then
  fail "the queue resolved inside the workspace"
fi

echo "PASS: host timeout helper remains isolated after loading task_lib.sh"
echo "PASS: probe stubbed, no live console port referenced"
