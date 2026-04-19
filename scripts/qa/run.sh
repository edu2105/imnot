#!/usr/bin/env bash
# imnot end-to-end QA suite
#
# Runs five phases against a fresh project directory:
#   Phase 1 — CLI commands (no server required)
#   Phase 2 — Default partner endpoint flows (staylink + bookingco)
#   Phase 3 — imnot generate testingpartner + hot reload
#   Phase 4 — testingpartner endpoint flows (all 5 patterns)
#   Phase 5 — Stop / restart / persistence check
#
# Usage:
#   ./scripts/qa/run.sh
#
# Requirements: imnot installed and on PATH, python3, curl, jq

set -euo pipefail

QA_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE="http://127.0.0.1:8000"
CALLBACK_PORT=9998
CALLBACK_BASE="http://127.0.0.1:${CALLBACK_PORT}"
CALLBACK_FILE="/tmp/imnot-qa-callback-$$.json"

PASS=0
FAIL=0
PHASE_FAILS=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ok()   { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); PHASE_FAILS=$((PHASE_FAILS + 1)); }

assert_status() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" -eq "$expected" ]; then
    ok "$label (HTTP $actual)"
  else
    fail "$label — expected HTTP $expected, got $actual"
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -q "$needle"; then
    ok "$label"
  else
    fail "$label — expected to find '$needle'"
  fi
}

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if ! echo "$haystack" | grep -q "$needle"; then
    ok "$label"
  else
    fail "$label — did not expect to find '$needle'"
  fi
}

phase() {
  PHASE_FAILS=0
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Phase $1: $2"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

phase_result() {
  if [ "$PHASE_FAILS" -eq 0 ]; then
    echo ""
    echo "  Phase $1 passed."
  else
    echo ""
    echo "  Phase $1 had $PHASE_FAILS failure(s) — continuing to next phase."
  fi
}

wait_for_server() {
  local retries=40
  while [ $retries -gt 0 ]; do
    if curl -s -o /dev/null -w "%{http_code}" "$BASE/healthz" 2>/dev/null | grep -q "200"; then
      return 0
    fi
    sleep 0.5
    retries=$((retries - 1))
  done
  echo "ERROR: server did not become ready within 20 seconds" >&2
  return 1
}

jq_field() { echo "$1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d$2)" 2>/dev/null; }

SERVER_PID_FILE=""
stop_server() {
  imnot stop 2>/dev/null || true
}

cleanup() {
  stop_server || true
  [ -n "${CALLBACK_SERVER_PID:-}" ] && kill "$CALLBACK_SERVER_PID" 2>/dev/null || true
  rm -f "$CALLBACK_FILE"
  if [ -n "${TEST_DIR:-}" ] && [ -d "$TEST_DIR" ]; then
    rm -rf "$TEST_DIR"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Setup — fresh project directory
# ---------------------------------------------------------------------------

echo ""
echo "imnot QA suite"
echo "============================================================"

TEST_DIR=$(mktemp -d /tmp/imnot-qa-XXXXXX)
echo "  Test directory : $TEST_DIR"
echo "  imnot version  : $(imnot --version 2>&1)"
echo ""

cd "$TEST_DIR"

# ---------------------------------------------------------------------------
# Phase 1 — CLI commands (no server)
# ---------------------------------------------------------------------------

phase 1 "CLI commands (no server)"

# --version
VERSION_OUT=$(imnot --version 2>&1)
assert_contains "imnot --version prints version string" "." "$VERSION_OUT"

# init
imnot init > /dev/null 2>&1
[ -f "partners/staylink/partner.yaml" ]  && ok "imnot init — staylink/partner.yaml exists"  || fail "imnot init — staylink/partner.yaml missing"
[ -f "partners/bookingco/partner.yaml" ] && ok "imnot init — bookingco/partner.yaml exists" || fail "imnot init — bookingco/partner.yaml missing"

# init again → fails with clear error
INIT_AGAIN=$(imnot init 2>&1 || true)
assert_contains "imnot init (second time) — exits with already-exists message" "already exists" "$INIT_AGAIN"

# routes (reads YAML, no server needed)
ROUTES_OUT=$(imnot routes 2>&1)
assert_contains "imnot routes — shows staylink"  "staylink"  "$ROUTES_OUT"
assert_contains "imnot routes — shows bookingco" "bookingco" "$ROUTES_OUT"
assert_contains "imnot routes — shows admin section" "ADMIN"  "$ROUTES_OUT"
assert_contains "imnot routes — shows infra endpoints" "INFRA"  "$ROUTES_OUT"

# export postman (reads YAML, no server needed)
imnot export postman --out postman.json > /dev/null 2>&1
[ -f "postman.json" ] && ok "imnot export postman — file written" || fail "imnot export postman — file missing"
python3 -c "import json; json.load(open('postman.json'))" 2>/dev/null \
  && ok "imnot export postman — valid JSON" \
  || fail "imnot export postman — invalid JSON"
POSTMAN_PARTNERS=$(python3 -c "import json; c=json.load(open('postman.json')); print([i['name'] for i in c['item']])")
assert_contains "imnot export postman — contains staylink"  "staylink"  "$POSTMAN_PARTNERS"
assert_contains "imnot export postman — contains bookingco" "bookingco" "$POSTMAN_PARTNERS"

# generate invalid YAML → exit non-zero
echo "not: valid: imnot: yaml" > /tmp/bad.yaml
GENERATE_BAD=$(imnot generate --file /tmp/bad.yaml 2>&1 || true)
if ! imnot generate --file /tmp/bad.yaml > /dev/null 2>&1; then
  ok "imnot generate (invalid YAML) — exits non-zero"
else
  fail "imnot generate (invalid YAML) — expected non-zero exit"
fi

# generate dry-run (valid YAML, no write)
GENERATE_DRY=$(imnot generate --file "$QA_DIR/testingpartner.yaml" --dry-run 2>&1)
assert_contains "imnot generate --dry-run — output mentions testingpartner" "testingpartner" "$GENERATE_DRY"
[ ! -f "partners/testingpartner/partner.yaml" ] \
  && ok "imnot generate --dry-run — no file written" \
  || fail "imnot generate --dry-run — file was written (should not be)"

phase_result 1

# ---------------------------------------------------------------------------
# Phase 2 — Default partner endpoint flows
# ---------------------------------------------------------------------------

phase 2 "Default partner endpoint flows (staylink + bookingco)"

imnot start --db "$TEST_DIR/imnot.db" > /tmp/imnot-qa-server-$$.log 2>&1 &
wait_for_server && ok "Server started and /healthz ready" || { fail "Server failed to start"; exit 1; }

echo ""
echo "  ── healthz ──"
HEALTH=$(curl -s "$BASE/healthz")
assert_contains "/healthz — version present" "version" "$HEALTH"

echo ""
echo "  ── staylink: oauth ──"
TOKEN_BODY=$(curl -s -X POST "$BASE/oauth/token")
TOKEN=$(echo "$TOKEN_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
[ -n "$TOKEN" ] && ok "POST /oauth/token — access_token present" || fail "POST /oauth/token — access_token missing"
assert_contains "POST /oauth/token — token_type Bearer" "Bearer" "$TOKEN_BODY"
assert_contains "POST /oauth/token — expires_in present" "expires_in" "$TOKEN_BODY"

echo ""
echo "  ── staylink: async (global payload) ──"
ASYNC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  "$BASE/imnot/admin/staylink/reservation/payload" \
  -H "Content-Type: application/json" \
  -d '{"reservationId":"QA001","guestName":"QA User"}')
assert_status "POST /imnot/admin/staylink/reservation/payload" 200 "$ASYNC_STATUS"

LOCATION=$(curl -s -D - -o /dev/null -X POST "$BASE/staylink/reservations" \
  | grep -i "^location:" | tr -d '\r' | awk '{print $2}')
[ -n "$LOCATION" ] && ok "POST /staylink/reservations — Location header present" || { fail "POST /staylink/reservations — no Location header"; exit 1; }
ASYNC_UUID="${LOCATION##*/}"

assert_status "HEAD /staylink/reservations/{id}" 201 \
  "$(curl -s -o /dev/null -w "%{http_code}" -X HEAD "$BASE/staylink/reservations/$ASYNC_UUID")"

POLL_STATUS=$(curl -s -I "$BASE/staylink/reservations/$ASYNC_UUID" \
  | grep -i "^Status:" | tr -d '\r' | awk '{print $2}')
[ "$POLL_STATUS" = "COMPLETED" ] \
  && ok "HEAD /staylink/reservations/{id} — Status: COMPLETED" \
  || fail "HEAD /staylink/reservations/{id} — expected Status: COMPLETED, got: '$POLL_STATUS'"

FETCH_BODY=$(curl -s "$BASE/staylink/reservations/$ASYNC_UUID")
assert_contains "GET /staylink/reservations/{id} — payload matches" "QA001" "$FETCH_BODY"
assert_status "GET /staylink/reservations/{id}" 200 \
  "$(curl -s -o /dev/null -w "%{http_code}" "$BASE/staylink/reservations/$ASYNC_UUID")"

echo ""
echo "  ── staylink: async (session isolation) ──"
SESSION_ID=$(curl -s -X POST \
  "$BASE/imnot/admin/staylink/reservation/payload/session" \
  -H "Content-Type: application/json" \
  -d '{"reservationId":"QA002","guestName":"Session User"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
[ -n "$SESSION_ID" ] && ok "POST .../payload/session — session_id returned" || { fail "session_id missing"; exit 1; }

SESSION_LOCATION=$(curl -s -D - -o /dev/null -X POST "$BASE/staylink/reservations" \
  -H "X-Imnot-Session: $SESSION_ID" \
  | grep -i "^location:" | tr -d '\r' | awk '{print $2}')
SESSION_UUID="${SESSION_LOCATION##*/}"

SESSION_BODY=$(curl -s -H "X-Imnot-Session: $SESSION_ID" "$BASE/staylink/reservations/$SESSION_UUID")
assert_contains "GET with session header — returns session payload" "QA002" "$SESSION_BODY"

NO_SESSION_BODY=$(curl -s "$BASE/staylink/reservations/$SESSION_UUID")
assert_contains "GET without session header — falls back to global payload" "QA001" "$NO_SESSION_BODY"

echo ""
echo "  ── bookingco: static ──"
STATIC_BODY=$(curl -s -X POST "$BASE/bookingco/auth/token")
STATIC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/bookingco/auth/token")
assert_status "POST /bookingco/auth/token" 200 "$STATIC_STATUS"
assert_contains "POST /bookingco/auth/token — token field present" "token" "$STATIC_BODY"

echo ""
echo "  ── bookingco: fetch ──"
FETCH_BEFORE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/bookingco/v1/charges")
assert_status "GET /bookingco/v1/charges (no payload) — 404" 404 "$FETCH_BEFORE"

curl -s -X POST "$BASE/imnot/admin/bookingco/charges/payload" \
  -H "Content-Type: application/json" \
  -d '{"total":150.00,"currency":"USD","items":[{"desc":"Night 1","amount":150.00}]}' > /dev/null

FETCH_AFTER=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/bookingco/v1/charges")
assert_status "GET /bookingco/v1/charges (after payload upload) — 200" 200 "$FETCH_AFTER"
FETCH_BODY=$(curl -s "$BASE/bookingco/v1/charges")
assert_contains "GET /bookingco/v1/charges — payload matches" "USD" "$FETCH_BODY"

echo ""
echo "  ── admin infra ──"
PARTNERS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/imnot/admin/partners")
assert_status "GET /imnot/admin/partners" 200 "$PARTNERS_STATUS"
PARTNERS_BODY=$(curl -s "$BASE/imnot/admin/partners")
assert_contains "GET /imnot/admin/partners — staylink listed"  "staylink"  "$PARTNERS_BODY"
assert_contains "GET /imnot/admin/partners — bookingco listed" "bookingco" "$PARTNERS_BODY"

SESSIONS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/imnot/admin/sessions")
assert_status "GET /imnot/admin/sessions" 200 "$SESSIONS_STATUS"

POSTMAN_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/imnot/admin/postman")
assert_status "GET /imnot/admin/postman" 200 "$POSTMAN_STATUS"

phase_result 2

# ---------------------------------------------------------------------------
# Phase 3 — imnot generate testingpartner + hot reload
# ---------------------------------------------------------------------------

phase 3 "Generate testingpartner and hot reload"

GENERATE_OUT=$(imnot generate --file "$QA_DIR/testingpartner.yaml" 2>&1)
[ -f "partners/testingpartner/partner.yaml" ] \
  && ok "imnot generate — partners/testingpartner/partner.yaml written" \
  || { fail "imnot generate — partner.yaml not written"; exit 1; }
assert_contains "imnot generate — output lists oauth endpoint"  "/testingpartner/oauth/token" "$GENERATE_OUT"
assert_contains "imnot generate — output lists async step 1"    "/testingpartner/jobs"        "$GENERATE_OUT"
assert_contains "imnot generate — output lists static endpoint" "/testingpartner/config"      "$GENERATE_OUT"
assert_contains "imnot generate — output lists fetch endpoint"  "/testingpartner/records"     "$GENERATE_OUT"
assert_contains "imnot generate — output lists push endpoint"   "/testingpartner/notifications" "$GENERATE_OUT"

# Second generate without --force → should fail
if ! imnot generate --file "$QA_DIR/testingpartner.yaml" > /dev/null 2>&1; then
  ok "imnot generate (duplicate, no --force) — exits non-zero"
else
  fail "imnot generate (duplicate, no --force) — expected non-zero exit"
fi

# Hot reload — testingpartner routes should now be live
RELOAD_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/imnot/admin/reload")
assert_status "POST /imnot/admin/reload" 200 "$RELOAD_STATUS"

# imnot routes reflects all three partners
ROUTES_OUT=$(imnot routes 2>&1)
assert_contains "imnot routes — testingpartner present after reload" "testingpartner" "$ROUTES_OUT"

# Admin partners endpoint also lists testingpartner
PARTNERS_BODY=$(curl -s "$BASE/imnot/admin/partners")
assert_contains "GET /imnot/admin/partners — testingpartner listed after reload" "testingpartner" "$PARTNERS_BODY"

phase_result 3

# ---------------------------------------------------------------------------
# Phase 4 — testingpartner endpoint flows (all 5 patterns)
# ---------------------------------------------------------------------------

phase 4 "testingpartner endpoint flows (all 5 patterns)"

echo ""
echo "  ── oauth ──"
TP_TOKEN_BODY=$(curl -s -X POST "$BASE/testingpartner/oauth/token")
TP_TOKEN=$(echo "$TP_TOKEN_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
[ -n "$TP_TOKEN" ] && ok "POST /testingpartner/oauth/token — access_token present" || fail "POST /testingpartner/oauth/token — access_token missing"
assert_contains "POST /testingpartner/oauth/token — token_type Bearer" "Bearer" "$TP_TOKEN_BODY"

echo ""
echo "  ── async ──"
curl -s -X POST "$BASE/imnot/admin/testingpartner/job/payload" \
  -H "Content-Type: application/json" \
  -d '{"jobResult":"processed","recordCount":42}' > /dev/null

JOB_BODY=$(curl -s -X POST "$BASE/testingpartner/jobs" -H "Content-Type: application/json" -d '{}')
JOB_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/testingpartner/jobs" -H "Content-Type: application/json" -d '{}')
assert_status "POST /testingpartner/jobs" 202 "$JOB_STATUS"

JOB_ID=$(echo "$JOB_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('jobId',''))" 2>/dev/null)
[ -n "$JOB_ID" ] && ok "POST /testingpartner/jobs — jobId present in response body" || { fail "POST /testingpartner/jobs — jobId missing"; exit 1; }

assert_status "GET /testingpartner/jobs/{id}/status" 200 \
  "$(curl -s -o /dev/null -w "%{http_code}" "$BASE/testingpartner/jobs/$JOB_ID/status")"

JOB_RESULT=$(curl -s "$BASE/testingpartner/jobs/$JOB_ID/result")
assert_status "GET /testingpartner/jobs/{id}/result" 200 \
  "$(curl -s -o /dev/null -w "%{http_code}" "$BASE/testingpartner/jobs/$JOB_ID/result")"
assert_contains "GET /testingpartner/jobs/{id}/result — payload matches" "42" "$JOB_RESULT"

echo ""
echo "  ── static ──"
STATIC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/testingpartner/config")
assert_status "GET /testingpartner/config" 200 "$STATIC_STATUS"
STATIC_BODY=$(curl -s "$BASE/testingpartner/config")
assert_contains "GET /testingpartner/config — version field" "1.0"      "$STATIC_BODY"
assert_contains "GET /testingpartner/config — env field"     "qa"       "$STATIC_BODY"
assert_contains "GET /testingpartner/config — features list" "feature-a" "$STATIC_BODY"

echo ""
echo "  ── fetch ──"
FETCH_BEFORE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/testingpartner/records/rec-001")
assert_status "GET /testingpartner/records/{id} (no payload) — 404" 404 "$FETCH_BEFORE"

curl -s -X POST "$BASE/imnot/admin/testingpartner/record/payload" \
  -H "Content-Type: application/json" \
  -d '{"id":"rec-001","name":"QA Record","status":"active"}' > /dev/null

FETCH_AFTER=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/testingpartner/records/rec-001")
assert_status "GET /testingpartner/records/{id} (after payload upload) — 200" 200 "$FETCH_AFTER"
FETCH_BODY=$(curl -s "$BASE/testingpartner/records/rec-001")
assert_contains "GET /testingpartner/records/{id} — payload matches" "QA Record" "$FETCH_BODY"

echo ""
echo "  ── push ──"
# Start a minimal callback capture server
python3 - <<'PYEOF' &
import http.server, os

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        path = os.environ.get("CALLBACK_FILE", "/tmp/imnot-qa-callback.json")
        with open(path, "wb") as f:
            f.write(body)
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args): pass

http.server.HTTPServer(("127.0.0.1", int(os.environ.get("CALLBACK_PORT", "9998"))), Handler).serve_forever()
PYEOF
CALLBACK_SERVER_PID=$!
# Give the callback server a moment to bind
sleep 0.5

curl -s -X POST "$BASE/imnot/admin/testingpartner/notification/payload" \
  -H "Content-Type: application/json" \
  -d '{"event":"qa.triggered","severity":"info"}' > /dev/null

PUSH_BODY=$(curl -s -X POST "$BASE/testingpartner/notifications" \
  -H "Content-Type: application/json" \
  -H "X-Callback-Url: ${CALLBACK_BASE}/callback" \
  -d '{"type":"test"}')
PUSH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE/testingpartner/notifications" \
  -H "Content-Type: application/json" \
  -H "X-Callback-Url: ${CALLBACK_BASE}/callback" \
  -d '{"type":"test"}')
assert_status "POST /testingpartner/notifications" 202 "$PUSH_STATUS"

REQUEST_ID=$(echo "$PUSH_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('request_id',''))" 2>/dev/null)
[ -n "$REQUEST_ID" ] && ok "POST /testingpartner/notifications — request_id returned" || fail "POST /testingpartner/notifications — request_id missing"

# Wait briefly for async callback delivery
sleep 1.5
CALLBACK_FILE_ENV="$CALLBACK_FILE" CALLBACK_PORT="$CALLBACK_PORT" python3 -c "
import os, json
f = os.environ.get('CALLBACK_FILE_ENV', '/tmp/imnot-qa-callback.json')
try:
    d = json.load(open(f))
    print('ok')
except Exception as e:
    print('fail: ' + str(e))
" | grep -q "ok" \
  && ok "Push callback — payload delivered to callback URL" \
  || fail "Push callback — callback not received within 1.5 s"

CALLBACK_BODY=$(cat "$CALLBACK_FILE" 2>/dev/null || echo "{}")
assert_contains "Push callback — payload contains event field" "qa.triggered" "$CALLBACK_BODY"

kill "$CALLBACK_SERVER_PID" 2>/dev/null || true
unset CALLBACK_SERVER_PID

phase_result 4

# ---------------------------------------------------------------------------
# Phase 5 — Stop / restart / persistence check
# ---------------------------------------------------------------------------

phase 5 "Stop, restart, persistence check"

# Record current session count before stopping
SESSIONS_BEFORE=$(curl -s "$BASE/imnot/admin/sessions" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

echo ""
echo "  ── stop ──"
imnot stop
sleep 0.5

[ ! -f "imnot.pid" ] && ok "imnot stop — imnot.pid removed" || fail "imnot stop — imnot.pid still exists"

# Verify server is down
if ! curl -s -o /dev/null -w "%{http_code}" "$BASE/healthz" 2>/dev/null | grep -q "200"; then
  ok "imnot stop — server no longer responds"
else
  fail "imnot stop — server still responding after stop"
fi

echo ""
echo "  ── restart ──"
imnot start --db "$TEST_DIR/imnot.db" > /tmp/imnot-qa-server2-$$.log 2>&1 &
wait_for_server && ok "imnot start (restart) — server ready" || { fail "Server failed to restart"; exit 1; }

echo ""
echo "  ── all three partners present ──"
ROUTES_RESTART=$(imnot routes 2>&1)
assert_contains "imnot routes after restart — staylink present"       "staylink"       "$ROUTES_RESTART"
assert_contains "imnot routes after restart — bookingco present"      "bookingco"      "$ROUTES_RESTART"
assert_contains "imnot routes after restart — testingpartner present" "testingpartner" "$ROUTES_RESTART"

echo ""
echo "  ── DB persistence ──"
PARTNERS_RESTART=$(curl -s "$BASE/imnot/admin/partners")
assert_contains "GET /imnot/admin/partners after restart — staylink"       "staylink"       "$PARTNERS_RESTART"
assert_contains "GET /imnot/admin/partners after restart — bookingco"      "bookingco"      "$PARTNERS_RESTART"
assert_contains "GET /imnot/admin/partners after restart — testingpartner" "testingpartner" "$PARTNERS_RESTART"

# Sessions survived restart
SESSIONS_AFTER=$(curl -s "$BASE/imnot/admin/sessions" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
[ "$SESSIONS_AFTER" -ge "$SESSIONS_BEFORE" ] \
  && ok "Sessions survived restart (before: $SESSIONS_BEFORE, after: $SESSIONS_AFTER)" \
  || fail "Sessions lost on restart (before: $SESSIONS_BEFORE, after: $SESSIONS_AFTER)"

# Payload survived restart
PAYLOAD_AFTER=$(curl -s "$BASE/imnot/admin/bookingco/charges/payload" 2>/dev/null || echo "{}")
assert_contains "bookingco/charges payload survived restart" "USD" "$PAYLOAD_AFTER"

PAYLOAD_TP=$(curl -s "$BASE/imnot/admin/testingpartner/record/payload" 2>/dev/null || echo "{}")
assert_contains "testingpartner/record payload survived restart" "QA Record" "$PAYLOAD_TP"

echo ""
echo "  ── final stop ──"
imnot stop
sleep 0.3
[ ! -f "imnot.pid" ] && ok "Final stop — imnot.pid cleaned up" || fail "Final stop — imnot.pid still exists"

phase_result 5

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "============================================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================================"

[ "$FAIL" -eq 0 ] && echo "  All checks passed." && exit 0 || exit 1
