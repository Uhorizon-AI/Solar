#!/bin/bash
# check_router.sh — solar-router v3 smoke tests
# Validates router contract v3, bridge delegation, and execute_active.py JSON parsing.
# Run from repo root: bash core/skills/solar-router/scripts/check_router.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$SCRIPT_DIR/../../solar-client/scripts/resolve_solar_paths.sh"
solar_resolve_paths --quiet
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
# Test 4: mode=direct_only → decision.kind=direct_reply
# Uses a mock provider (bash -c 'echo mock-response') to avoid any real AI
# call or network dependency. decision_engine always returns direct_reply
# for direct_only regardless of provider output.
# ---------------------------------------------------------------------------
echo ""
echo "── Test 4: mode=direct_only → decision.kind=direct_reply (mock provider)"
out="$(SOLAR_ROUTER_CLAUDE_CMD="bash -c 'echo mock-response'" SOLAR_ROUTER_PROVIDER_PRIORITY=claude \
    call_router '{"request_id":"t4","session_id":"s","user_id":"u","text":"hello","channel":"async-task","mode":"direct_only"}')"
assert_json_valid "mode=direct_only returns valid JSON" "$out"
assert_json_field "status=success on direct_only" "$out" "['status']" "success"
assert_json_field "mode=direct_only → decision.kind=direct_reply" "$out" "['decision']['kind']" "direct_reply"

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
EXECUTE_PY="$(solar_core_dir)/skills/solar-async-tasks/scripts/execute_active.py"
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
# Test 10: parse_ai_decision_output — solar tags (async_draft_created)
# ---------------------------------------------------------------------------
echo ""
echo "── Test 10: parse_ai_decision_output parses solar_decision tags"
parse_result="$($PYTHON -c "
import sys
import importlib.util
spec = importlib.util.spec_from_file_location('run_router', '$ROUTER_SCRIPT')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

out = '''Creating async task
<solar_decision>async_draft_created</solar_decision>
<solar_summary>summary</solar_summary>'''
result = mod.parse_ai_decision_output(out)
assert result['decision']['kind'] == 'async_draft_created', f\"expected async_draft_created, got {result['decision']['kind']}\"
assert 'Creating async task' in result['reply_text'], 'reply_text should strip tags but keep body'
print('ok')
" 2>&1 || echo "error")"
if [[ "$parse_result" == "ok" ]]; then
    pass "parse_ai_decision_output: parses solar_decision tags"
else
    fail "parse_ai_decision_output solar tags" "$parse_result"
fi

# ---------------------------------------------------------------------------
# Test 11: provider locked + failing → provider_locked_failed
# Uses SOLAR_ROUTER_CLAUDE_CMD=false to force the provider to fail without
# a real AI call. /usr/bin/false exits 1, triggering the strict-mode error path.
# ---------------------------------------------------------------------------
echo ""
echo "── Test 11: provider locked + fails → provider_locked_failed"
out="$(SOLAR_ROUTER_CLAUDE_CMD=false call_router '{"request_id":"t11","session_id":"s","user_id":"u","text":"hello","channel":"other","mode":"auto","provider":"claude"}')"
assert_json_valid "provider_locked_failed returns valid JSON" "$out"
assert_json_field "status=failed on provider_locked_failed" "$out" "['status']" "failed"
assert_json_field "error_code=provider_locked_failed" "$out" "['error_code']" "provider_locked_failed"

# ---------------------------------------------------------------------------
# Test 12: all providers fail → all_providers_failed
# Restricts priority to one provider (claude) and forces it to fail.
# The fallback loop exhausts all candidates and emits all_providers_failed.
# ---------------------------------------------------------------------------
echo ""
echo "── Test 12: all providers fail → all_providers_failed"
out="$(SOLAR_ROUTER_CLAUDE_CMD=false SOLAR_ROUTER_PROVIDER_PRIORITY=claude call_router '{"request_id":"t12","session_id":"s","user_id":"u","text":"hello","channel":"other","mode":"auto"}')"
assert_json_valid "all_providers_failed returns valid JSON" "$out"
assert_json_field "status=failed on all_providers_failed" "$out" "['status']" "failed"
assert_json_field "error_code=all_providers_failed" "$out" "['error_code']" "all_providers_failed"

# ---------------------------------------------------------------------------
# Test 13: mode=async_only + feature enabled → async_draft_created
# Runs only if solar-async-tasks create.sh is present (side effect: creates a
# real draft task). Skips otherwise to avoid false failures in bare envs.
# ---------------------------------------------------------------------------
echo ""
echo "── Test 13: mode=async_only + async-tasks enabled → async_draft_created"
CREATE_SH="$(solar_core_dir)/skills/solar-async-tasks/scripts/create.sh"
if [[ ! -f "$CREATE_SH" ]]; then
    skip "async_only success path" "create.sh not found: $CREATE_SH"
else
    # Mock provider (no real AI); create.sh still runs and must return an ID line.
    out="$(SOLAR_SYSTEM_FEATURES=async-tasks SOLAR_ROUTER_CLAUDE_CMD="bash -c 'echo mock-async-body'" SOLAR_ROUTER_PROVIDER_PRIORITY=claude \
        call_router '{"request_id":"t13","session_id":"s","user_id":"u","text":"smoke test async draft","channel":"other","mode":"async_only"}')"
    assert_json_valid "async_only success returns valid JSON" "$out"
    status13="$($PYTHON -c "import json,sys; print(json.loads(sys.argv[1]).get('status',''))" "$out" 2>/dev/null || echo "unknown")"
    if [[ "$status13" == "success" ]]; then
        assert_json_field "async_only success → status=success" "$out" "['status']" "success"
        assert_json_field "async_only success → decision.kind=async_draft_created" "$out" "['decision']['kind']" "async_draft_created"
    else
        fail "async_only success path" "expected status=success, got status=$status13 — output: $out"
    fi
fi

# ---------------------------------------------------------------------------
# Test 14: audit early exit — start and end both written (Fase 2 fix)
# Triggers async_tasks_disabled early exit in an isolated temp runtime dir.
# ---------------------------------------------------------------------------
echo ""
echo "── Test 14: audit early exit — start and end written on failure"
AUDIT_TMP="$(mktemp -d)"
SOLAR_ROUTER_RUNTIME_DIR="$AUDIT_TMP" SOLAR_SYSTEM_FEATURES="" \
    call_router '{"request_id":"t14","session_id":"s","user_id":"u","text":"hello","channel":"other","mode":"async_only"}' > /dev/null
AUDIT_FILE="$AUDIT_TMP/audit.jsonl"
if [[ ! -f "$AUDIT_FILE" ]]; then
    fail "audit early exit: start event" "audit.jsonl not created at $AUDIT_FILE"
else
    start_count="$($PYTHON -c "
import json, sys
lines = open('$AUDIT_FILE').readlines()
print(sum(1 for l in lines if json.loads(l).get('event') == 'start'))
" 2>/dev/null || echo "0")"
    end_count="$($PYTHON -c "
import json, sys
lines = open('$AUDIT_FILE').readlines()
print(sum(1 for l in lines if json.loads(l).get('event') == 'end'))
" 2>/dev/null || echo "0")"
    if [[ "$start_count" -ge 1 ]]; then
        pass "audit early exit: start event written"
    else
        fail "audit early exit: start event" "expected ≥1 start event, got $start_count"
    fi
    if [[ "$end_count" -ge 1 ]]; then
        pass "audit early exit: end event written on failure"
    else
        fail "audit early exit: end event" "expected ≥1 end event after failed route, got $end_count"
    fi
fi
rm -rf "$AUDIT_TMP"

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
