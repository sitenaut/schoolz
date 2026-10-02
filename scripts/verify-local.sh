#!/usr/bin/env bash
# Self-verification script for schoolz local development stack.
# Usage:
#   ./scripts/verify-local.sh [all|health|auth|backend|frontend]
set -euo pipefail

TARGET=${1:-all}
BACKEND_URL=${SCHOOLZ_API_URL_LOCAL:-http://localhost:8000}
FRONTEND_URL=${SCHOOLZ_WEB_URL_LOCAL:-http://localhost:5173}
SCRAPER_URL=${SCHOOLZ_SCRAPER_URL_LOCAL:-http://localhost:8765}

pass() { echo -e "\033[32m[PASS] $1\033[0m"; }
fail() { echo -e "\033[31m[FAIL] $1\033[0m"; exit 1; }
step() { echo -e "\n\033[36m=== $1 ===\033[0m"; }

test_health() {
  step "Checking Running Local Stack Endpoints"
  curl -s -f "$BACKEND_URL/health" > /dev/null && pass "Backend API healthy ($BACKEND_URL/health)" || fail "Backend unreachable"
  curl -s -f "$FRONTEND_URL" > /dev/null && pass "Frontend Web healthy ($FRONTEND_URL)" || fail "Frontend unreachable"
  curl -s -f "$SCRAPER_URL/health" > /dev/null && pass "Scraper healthy ($SCRAPER_URL/health)" || fail "Scraper unreachable"
}

test_auth() {
  step "Testing Live Registration & Auth Flows ($BACKEND_URL)"
  TAG=$(head -c 8 /dev/urandom | xxd -p | head -c 8 || date +%s)
  EMAIL="verify_${TAG}@example.com"
  USER="verify_${TAG}"
  PASS="VerifyPass123!"

  REG_RES=$(curl -s -f -X POST "$BACKEND_URL/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"username\":\"$USER\",\"password\":\"$PASS\"}")
  TOKEN=$(echo "$REG_RES" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
  [ -n "$TOKEN" ] && pass "POST /auth/register: User created ($USER)" || fail "Registration failed"

  ME_RES=$(curl -s -f -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/auth/me")
  echo "$ME_RES" | grep -q "$EMAIL" && pass "GET /auth/me: Verified user profile" || fail "Failed /auth/me verification"

  LOGIN_RES=$(curl -s -f -X POST "$BACKEND_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username_or_email\":\"$EMAIL\",\"password\":\"$PASS\"}")
  echo "$LOGIN_RES" | grep -q "access_token" && pass "POST /auth/login: Verified credential exchange" || fail "Login failed"

  curl -s -f -X DELETE "$BACKEND_URL/auth/me" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"confirm\":\"DELETE\",\"password\":\"$PASS\"}" > /dev/null
  pass "DELETE /auth/me: Test account cleanly removed"
}

test_backend() {
  step "Running Backend Unit Tests (Docker container: schoolz-api-local)"
  docker exec schoolz-api-local pytest -q tests/test_account.py tests/test_students.py
  pass "Backend tests passed"
}

test_frontend() {
  step "Running Frontend Vitest"
  cd frontend && npx vitest run src/pages/LoginPage.test.ts src/authConfig.test.ts src/lib/pendingInvite.test.ts
  pass "Frontend tests passed"
}

case "$TARGET" in
  health) test_health ;;
  auth) test_auth ;;
  backend) test_backend ;;
  frontend) test_frontend ;;
  all)
    test_health
    test_auth
    test_backend
    test_frontend
    echo -e "\n\033[32mAll verification checks completed successfully!\033[0m\n"
    ;;
  *) echo "Unknown target: $TARGET"; exit 2 ;;
esac
