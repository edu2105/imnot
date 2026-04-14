#!/usr/bin/env bash
# Smoke test — runs the full OHIP reservation flow against a live imnot server.
# Usage: ./scripts/smoke_test.sh [BASE_URL]
# Default BASE_URL: http://127.0.0.1:8000
#
# Start the server first:
#   imnot start
#
# Then in another terminal:
#   ./scripts/smoke_test.sh

set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
PASS=0
FAIL=0

ok()   { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

assert_status() {
  local label="$1" expected="$2" actual="$3"
  [ "$actual" -eq "$expected" ] && ok "$label (HTTP $actual)" || fail "$label — expected $expected, got $actual"
}

echo ""
echo "imnot smoke test → $BASE"
echo "=============================================="

# ------------------------------------------------------------------------------
echo ""
echo "1. OAuth token"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/oauth/token")
assert_status "POST /oauth/token" 200 "$STATUS"

TOKEN=$(curl -s -X POST "$BASE/oauth/token" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
[ -n "$TOKEN" ] && ok "access_token present" || fail "access_token missing"

# ------------------------------------------------------------------------------
echo ""
echo "2. Admin — upload global payload"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/imnot/admin/staylink/reservation/payload" \
  -H "Content-Type: application/json" \
  -d '{"reservationId":"SMOKE001","status":"CONFIRMED","guestName":"Alice"}')
assert_status "POST /imnot/admin/staylink/reservation/payload" 200 "$STATUS"

# ------------------------------------------------------------------------------
echo ""
echo "3. Poll flow — global payload"
LOCATION=$(curl -s -D - -o /dev/null -X POST "$BASE/staylink/reservations" \
  | grep -i "^location:" | tr -d '\r' | awk '{print $2}')
[ -n "$LOCATION" ] && ok "POST /staylink/reservations — Location: $LOCATION" || { fail "No Location header"; exit 1; }

UUID="${LOCATION##*/}"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X HEAD "$BASE/staylink/reservations/$UUID")
assert_status "HEAD /staylink/reservations/$UUID" 201 "$STATUS"

POLL_STATUS=$(curl -s -I "$BASE/staylink/reservations/$UUID" | grep -i "^Status:" | tr -d '\r' | awk '{print $2}')
[ "$POLL_STATUS" = "COMPLETED" ] && ok "Status header = COMPLETED" || fail "Status header missing or wrong: '$POLL_STATUS'"

BODY=$(curl -s "$BASE/staylink/reservations/$UUID")
echo "$BODY" | grep -q "SMOKE001" && ok "GET /staylink/reservations/$UUID — payload matches" || fail "Payload mismatch: $BODY"

# ------------------------------------------------------------------------------
echo ""
echo "4. Poll flow — session payload"
SESSION_ID=$(curl -s -X POST "$BASE/imnot/admin/staylink/reservation/payload/session" \
  -H "Content-Type: application/json" \
  -d '{"reservationId":"SMOKE002","guestName":"Bob"}' \
  | grep -o '"session_id":"[^"]*"' | cut -d'"' -f4)
[ -n "$SESSION_ID" ] && ok "session_id returned: $SESSION_ID" || { fail "No session_id"; exit 1; }

SESSION_LOCATION=$(curl -s -D - -o /dev/null -X POST "$BASE/staylink/reservations" \
  -H "X-Imnot-Session: $SESSION_ID" \
  | grep -i "^location:" | tr -d '\r' | awk '{print $2}')
SESSION_UUID="${SESSION_LOCATION##*/}"

BODY=$(curl -s -H "X-Imnot-Session: $SESSION_ID" "$BASE/staylink/reservations/$SESSION_UUID")
echo "$BODY" | grep -q "SMOKE002" && ok "GET with session header — payload matches" || fail "Session payload mismatch: $BODY"

BODY_NO_SESSION=$(curl -s "$BASE/staylink/reservations/$SESSION_UUID")
echo "$BODY_NO_SESSION" | grep -q "SMOKE001" && ok "GET without session header — falls back to global payload" \
  || fail "GET without session header — expected global payload (SMOKE001), got: $BODY_NO_SESSION"

# ------------------------------------------------------------------------------
echo ""
echo "5. Admin endpoints"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/imnot/admin/partners")
assert_status "GET /imnot/admin/partners" 200 "$STATUS"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/imnot/admin/sessions")
assert_status "GET /imnot/admin/sessions" 200 "$STATUS"

# ------------------------------------------------------------------------------
echo ""
echo "=============================================="
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "All checks passed." && exit 0 || exit 1
