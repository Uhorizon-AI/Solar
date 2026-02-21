#!/bin/bash
# check_router.sh — solar-router v3 smoke tests
# Validates router contract v3, bridge delegation, and execute_active.py JSON parsing.
# Run from repo root: bash core/skills/solar-router/scripts/check_router.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
ROUTER_SCRIPT="$SCRIPT_DIR/run_router.py"
PYTHON="${SOLAR_AI_ROUTER_PYTHON:-python3}"

PASS=0
FAIL=0
SKIP=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

pass() { echo "  ✅ PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ FAIL: $1"; echo "     → $2"; FAIL=$((FAIL + 1)); }
skip() { echo "  ⏭  SKIP: $1 — $2"; SKIP=$((SKIP + 1)); }

assert_json_field() {
    local label="$1"
    local json="$2"
    local field="$3"
    local expected="$4"
    local actual
    actual="$($PYTHON -c "import json,sys; d=json.loads(sys.argv[1]); print(d$field)" "$json" 2>/dev/null || echo "__parse_error__")"
    if [[ "$actual" == "$expected" ]]; then
        pass "$label"
    else
        fail "$label" "expected '$expected', got '$actual'"
    fi
}

assert_json_valid() {
    local label="$1"
    local json="$2"
    if $PYTHON -c "import json,sys; json.loads(sys.argv[1])" "$json" 2>/dev/null; then
        pass "$label"
    else
        fail "$label" "output is not valid JSON: $json"
    fi
}

call_router() {
    local payload="$1"
    printf "%s" "$payload" | $PYTHON "$ROUTER_SCRIPT" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Test 1: missing input → valid JSON failed response
# ---------------------------------------------------------------------------
echo ""
echo "── Test 1: missing stdin → JSON failed"
out="$(echo "" | $PYTHON "$ROUTER_SCRIPT" 2>/dev/null || true)"
assert_json_valid "missing stdin returns valid JSON" "$out"
assert_json_field "status=failed on missing stdin" "$out" "['status']" "failed"

# ---------------------------------------------------------------------------
# Test 2: invalid JSON input → valid JSON failed response
# ---------------------------------------------------------------------------
echo ""
echo "── Test 2: invalid JSON input → JSON failed"
out="$(echo "not-json" | $PYTHON "$ROUTER_SCRIPT" 2>/dev/null || true)"
assert_json_valid "invalid JSON input returns valid JSON" "$out"
assert_json_field "status=failed on invalid JSON" "$out" "['status']" "failed"

# ---------------------------------------------------------------------------
# Test 3: missing text field → JSON failed
# ---------------------------------------------------------------------------
echo ""
echo "── Test 3: missing text → JSON failed"
payload='{"request_id":"t3","session_id":"s","user_id":"u","channel":"other","mode":"direct_only"}'
out="$(call_router "$payload")"
assert_json_valid "missing text returns valid JSON" "$out"
assert_json_field "status=failed on missing text" "$out" "['status']" "failed"
assert_json_field "error_code=missing_text" "$out" "['error_code']" "missing_text"

# ---------------------------------------------------------------------------
# Test 4: mode=direct_only → decision.kind=direct_reply (no AI call needed for routing)
# ---------------------------------------------------------------------------
echo ""
echo "── Test 4: mode=direct_only → decision.kind=direct_reply (if provider available)"
payload='{"request_id":"t4","session_id":"s","user_id":"u","text":"hello","channel":"async-task","mode":"direct_only"}'
out="$(call_router "$payload")"
if [[ -z "$out" ]]; then
    skip "mode=direct_only decision.kind check" "no output (provider may not be available)"
else
    assert_json_valid "mode=direct_only returns valid JSON" "$out"
    status="$($PYTHON -c "import json,sys; print(json.loads(sys.argv[1])['status'])" "$out" 2>/dev/null || echo "unknown")"
    if [[ "$status" == "success" ]]; then
        assert_json_field "mode=direct_only → decision.kind=direct_reply" "$out" "['decision']['kind']" "direct_reply"
    else
        skip "mode=direct_only decision.kind" "provider not available (status=$status)"
    fi
fi

# ---------------------------------------------------------------------------
# Test 5: unsupported provider → JSON failed with error_code
# ---------------------------------------------------------------------------
echo ""
echo "── Test 5: unsupported provider → JSON failed"
payload='{"request_id":"t5","session_id":"s","user_id":"u","text":"hello","channel":"other","mode":"auto","provider":"fakeai"}'
out="$(call_router "$payload")"
assert_json_valid "unsupported provider returns valid JSON" "$out"
assert_json_field "status=failed on unsupported provider" "$out" "['status']" "failed"
assert_json_field "error_code=unsupported_provider" "$out" "['error_code']" "unsupported_provider"

# ---------------------------------------------------------------------------
# Test 6: invalid mode → JSON failed
# ---------------------------------------------------------------------------
echo ""
echo "── Test 6: invalid mode → JSON failed"
payload='{"request_id":"t6","session_id":"s","user_id":"u","text":"hello","channel":"other","mode":"invalid_mode"}'
out="$(call_router "$payload")"
assert_json_valid "invalid mode returns valid JSON" "$out"
assert_json_field "status=failed on invalid mode" "$out" "['status']" "failed"
assert_json_field "error_code=invalid_mode" "$out" "['error_code']" "invalid_mode"

# ---------------------------------------------------------------------------
# Test 7: mode=async_only + async-tasks disabled → JSON failed
# ---------------------------------------------------------------------------
echo ""
echo "── Test 7: mode=async_only + async-tasks disabled → JSON failed"
out="$(SOLAR_SYSTEM_FEATURES="" call_router '{"request_id":"t7","session_id":"s","user_id":"u","text":"hello","channel":"other","mode":"async_only"}')"
assert_json_valid "async_only without feature returns valid JSON" "$out"
assert_json_field "status=failed when async-tasks not enabled" "$out" "['status']" "failed"

# ---------------------------------------------------------------------------
# Test 8: execute_active.py JSON parsing — simulate router v3 response
# ---------------------------------------------------------------------------
echo ""
echo "── Test 8: execute_active.py parses router v3 JSON correctly"
EXECUTE_PY="$REPO_ROOT/core/skills/solar-async-tasks/scripts/execute_active.py"
if [[ ! -f "$EXECUTE_PY" ]]; then
    skip "execute_active.py parse test" "script not found: $EXECUTE_PY"
else
    # Test that the module imports and the helper functions work
    parse_result="$($PYTHON -c "
import sys
sys.argv = ['test']
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location('execute_active', '$EXECUTE_PY')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Test read_frontmatter_key with a temp file
import tempfile, pathlib
tmp = pathlib.Path(tempfile.mktemp(suffix='.md'))
tmp.write_text('---\nid: test-123\ntitle: Test Task\nprovider: claude\n---\n\nBody here.')
assert mod.read_frontmatter_key(tmp, 'id') == 'test-123', 'id mismatch'
assert mod.read_frontmatter_key(tmp, 'provider') == 'claude', 'provider mismatch'
assert mod.strip_frontmatter(tmp).strip() == 'Body here.', 'body mismatch'
tmp.unlink()
print('ok')
" 2>&1 || echo "error")"
    if [[ "$parse_result" == "ok" ]]; then
        pass "execute_active.py: frontmatter parsing works"
    else
        fail "execute_active.py: frontmatter parsing" "$parse_result"
    fi
fi

# ---------------------------------------------------------------------------
# Test 9: parse_ai_decision_output — direct_reply degradation
# ---------------------------------------------------------------------------
echo ""
echo "── Test 9: parse_ai_decision_output degradation to direct_reply"
degrade_result="$($PYTHON -c "
import sys, pathlib
sys.path.insert(0, '$SCRIPT_DIR')
import importlib.util
spec = importlib.util.spec_from_file_location('run_router', '$ROUTER_SCRIPT')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Non-JSON output should degrade to direct_reply with reply_text preserved
result = mod.parse_ai_decision_output('This is a plain text response')
assert result['decision']['kind'] == 'direct_reply', f\"expected direct_reply, got {result['decision']['kind']}\"
assert result['reply_text'] == 'This is a plain text response', 'reply_text not preserved'
assert result.get('_degraded') == True, 'degraded flag missing'
print('ok')
" 2>&1 || echo "error")"
if [[ "$degrade_result" == "ok" ]]; then
    pass "parse_ai_decision_output: degrades to direct_reply with reply_text"
else
    fail "parse_ai_decision_output degradation" "$degrade_result"
fi

# ---------------------------------------------------------------------------
# Test 10: parse_ai_decision_output — valid JSON with decision.kind
# ---------------------------------------------------------------------------
echo ""
echo "── Test 10: parse_ai_decision_output parses valid JSON"
parse_result="$($PYTHON -c "
import sys
import importlib.util
spec = importlib.util.spec_from_file_location('run_router', '$ROUTER_SCRIPT')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

import json
valid_output = json.dumps({'decision': {'kind': 'async_draft_created', 'priority_suggested': 'normal'}, 'reply_text': 'Creating async task'})
result = mod.parse_ai_decision_output(valid_output)
assert result['decision']['kind'] == 'async_draft_created', f\"expected async_draft_created, got {result['decision']['kind']}\"
assert result['reply_text'] == 'Creating async task', 'reply_text mismatch'
print('ok')
" 2>&1 || echo "error")"
if [[ "$parse_result" == "ok" ]]; then
    pass "parse_ai_decision_output: parses valid JSON with decision.kind"
else
    fail "parse_ai_decision_output valid JSON" "$parse_result"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "══════════════════════════════════════"
echo "  Smoke test results"
echo "  PASS: $PASS  FAIL: $FAIL  SKIP: $SKIP"
echo "══════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    echo "  ❌ Smoke test FAILED — do not run sync-clients.sh"
    exit 1
else
    echo "  ✅ Smoke test PASSED"
    exit 0
fi
