#!/usr/bin/env bash
# smoke_test.sh — verify all TriageCopilot API endpoints return expected status codes.
# Usage: ./scripts/smoke_test.sh [BASE_URL]
# Default BASE_URL: http://localhost:8000

set -euo pipefail

BASE="${1:-http://localhost:8000}"
PASS=0
FAIL=0

check() {
    local desc="$1"
    local method="$2"
    local url="$3"
    local body="${4:-}"
    local expected="$5"

    if [ -n "$body" ]; then
        status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X "$method" \
            -H "Content-Type: application/json" \
            -d "$body" "$url") || status="000"
    else
        status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X "$method" "$url") || status="000"
    fi

    if [ "$status" = "$expected" ]; then
        echo "  PASS  [$status] $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  [got $status, want $expected] $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "TriageCopilot smoke test — $BASE"
echo "========================================"

check "GET /health returns 200"              GET  "$BASE/health"              "" 200
check "GET /dashboard/repos returns 200"     GET  "$BASE/dashboard/repos"     "" 200
check "POST /search missing body → 422"     POST "$BASE/search"              "" 422
check "POST /search invalid k → 422"        POST "$BASE/search" \
    '{"repo_id":1,"query":"crash","k":0}' 422
check "POST /triage missing field → 422"    POST "$BASE/triage"              "" 422
check "POST /triage invalid number → 422"   POST "$BASE/triage" \
    '{"repo_id":1,"issue_github_number":0}' 422
check "GET /dashboard/repos/999/results → 200 (empty list)" \
    GET "$BASE/dashboard/repos/999/results" "" 200
check "GET /dashboard/repos/999/results/1 → 404" \
    GET "$BASE/dashboard/repos/999/results/1" "" 404

echo "========================================"
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
